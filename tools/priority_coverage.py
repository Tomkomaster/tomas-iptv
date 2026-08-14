#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from research_priority import compile_research_priority_policy, priority_rank
from tools.research_exports import (
    derive_channel_status,
    display_channel,
    display_tvg_id,
    group_channels,
    load_audit_rows,
    match_wanted_channels,
    normalize_name,
    normalize_tvg_id,
    row_country,
    target_priority,
)
from wanted_channels import load_wanted_channels


TRACKED_PRIORITIES = ("P1", "P2")
STATUS_LABELS = {
    "PARTIAL": "Partial — compatibility still incomplete",
    "CANDIDATES TO TEST": "Candidates still need testing",
    "NO WORKING FEED": "No working feed",
    "NOT RESEARCHED": "Not researched yet",
}
FLAG_BY_COUNTRY = {
    "HU": "🇭🇺",
    "SK": "🇸🇰",
    "CZ": "🇨🇿",
    "RO": "🇷🇴",
    "AT": "🇦🇹",
}
STYLE_START = "<!-- priority-coverage:style:start -->"
STYLE_END = "<!-- priority-coverage:style:end -->"
SECTION_START = "<!-- priority-coverage:section:start -->"
SECTION_END = "<!-- priority-coverage:section:end -->"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _target_identity(country: str, channel: str, tvg_id: str) -> tuple[str, str, str]:
    return (
        str(country or "").strip().upper(),
        normalize_name(channel),
        normalize_tvg_id(tvg_id),
    )


def _same_target(left: dict, right: dict) -> bool:
    left_country, left_name, left_id = _target_identity(
        left.get("country", ""), left.get("channel", ""), left.get("tvg_id", "")
    )
    right_country, right_name, right_id = _target_identity(
        right.get("country", ""), right.get("channel", ""), right.get("tvg_id", "")
    )
    if not left_country or left_country != right_country:
        return False
    if left_id and right_id and left_id == right_id:
        return True
    return bool(left_name and right_name and left_name == right_name)


def _status_rank(status: str) -> int:
    return {
        "WORKING": 0,
        "PARTIAL": 1,
        "CANDIDATES TO TEST": 2,
        "NO WORKING FEED": 3,
        "NOT RESEARCHED": 4,
    }.get(str(status or ""), 9)


def _logo_match_name(value: object) -> str:
    name = normalize_name(value)
    # Research labels can retain a harmless provider/feed discriminator even when
    # publication has already collapsed it to the logical channel identity.
    name = re.sub(r"\bfeed\s+\d+\b", " ", name, flags=re.I)
    return " ".join(name.split())


def _best_logo_row(rows: list[dict]) -> dict | None:
    if not rows:
        return None
    quality_rank = {"Canonical": 2, "Source fallback": 1, "Missing": 0}
    return max(rows, key=lambda row: quality_rank.get(str(row.get("quality_category") or ""), -1))


def _logo_row_for_target(target: dict, logo_rows: list[dict]) -> dict | None:
    country = str(target.get("country") or "").strip().upper()
    same_country = [
        row for row in logo_rows
        if str(row.get("country_code") or "").strip().upper() == country
    ]
    target_id = normalize_tvg_id(target.get("tvg_id", ""))
    if target_id:
        exact_same_country = [
            row for row in same_country
            if normalize_tvg_id(row.get("tvg_id", "")) == target_id
        ]
        if exact_same_country:
            return _best_logo_row(exact_same_country)

        # Priority coverage follows the research/audit geography, while logo quality
        # follows the final published geography. An explicit routing can therefore
        # move the same logical service between country buckets. Exact tvg-id remains
        # strong enough identity evidence to bridge that reporting boundary.
        exact_any_country = [
            row for row in logo_rows
            if normalize_tvg_id(row.get("tvg_id", "")) == target_id
        ]
        if exact_any_country:
            return _best_logo_row(exact_any_country)

    target_name = _logo_match_name(target.get("channel", ""))
    if target_name:
        same_name_country = [
            row for row in same_country
            if _logo_match_name(row.get("channel", "")) == target_name
        ]
        if same_name_country:
            return _best_logo_row(same_name_country)
    return None


def _priority_logo_summary(targets: list[dict], logo_quality: dict | None) -> dict:
    stable = [target for target in targets if target.get("status") == "WORKING"]
    logo_rows = list((logo_quality or {}).get("channels") or [])
    canonical = 0
    source = 0
    missing = 0
    for target in stable:
        row = _logo_row_for_target(target, logo_rows)
        quality = str((row or {}).get("quality_category") or "Missing")
        if quality == "Canonical":
            canonical += 1
        elif quality == "Source fallback":
            source += 1
        else:
            missing += 1
    total = len(stable)
    available = canonical + source
    return {
        "stable_targets": total,
        "with_logo": available,
        "canonical_logo": canonical,
        "source_fallback": source,
        "missing_logo": missing,
        "logo_availability_percent": round(100.0 * available / total if total else 0.0, 1),
        "canonical_logo_coverage_percent": round(100.0 * canonical / total if total else 0.0, 1),
    }


def _add_target(targets: list[dict], candidate: dict) -> None:
    candidate = dict(candidate)
    candidate["country"] = str(candidate.get("country") or "").strip().upper()
    candidate["channel"] = str(candidate.get("channel") or "").strip()
    candidate["tvg_id"] = str(candidate.get("tvg_id") or "").strip()
    candidate["priority"] = str(candidate.get("priority") or "").strip().upper()
    candidate["status"] = str(candidate.get("status") or "NOT RESEARCHED").strip().upper()

    if candidate["priority"] not in TRACKED_PRIORITIES or not candidate["country"]:
        return

    for existing in targets:
        if not _same_target(existing, candidate):
            continue

        if priority_rank(candidate["priority"]) < priority_rank(existing["priority"]):
            existing["priority"] = candidate["priority"]
        if _status_rank(candidate["status"]) < _status_rank(existing["status"]):
            existing["status"] = candidate["status"]
        if not existing.get("channel") or existing.get("channel") == existing.get("tvg_id"):
            existing["channel"] = candidate.get("channel") or existing.get("channel", "")
        if not existing.get("tvg_id"):
            existing["tvg_id"] = candidate.get("tvg_id", "")
        return

    targets.append(candidate)


def _policy_targets(priority_policy: dict) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    for raw in priority_policy.get("entries") or []:
        if not isinstance(raw, dict):
            continue
        priority = str(raw.get("priority") or "").strip().upper()
        if priority not in TRACKED_PRIORITIES:
            continue
        country = str(raw.get("country") or "").strip().upper()
        channel = str(raw.get("channel") or "").strip()
        tvg_id = str(raw.get("tvg_id") or "").strip()
        label = channel or tvg_id
        if not country or not label:
            continue
        targets.append(
            {
                "country_code": country,
                "channel": label,
                "tvg_id": tvg_id,
                "priority": priority,
                "reason": str(raw.get("reason") or "").strip(),
            }
        )
    return targets


def build_priority_coverage(
    audit_rows: list[dict[str, str]],
    *,
    config: dict,
    priority_policy: dict,
    wanted_channels: list[dict[str, str]],
    logo_quality: dict | None = None,
) -> dict:
    grouped = group_channels(audit_rows)
    compiled_priority = compile_research_priority_policy(priority_policy)
    matched_wanted, unmatched_wanted = match_wanted_channels(grouped, wanted_channels)
    policy_targets = _policy_targets(priority_policy)
    unmatched_policy_targets: list[dict[str, str]] = []
    for policy_target in policy_targets:
        _, unmatched = match_wanted_channels(grouped, [policy_target])
        unmatched_policy_targets.extend(unmatched)

    targets: list[dict] = []

    for group_key, rows in grouped.items():
        if not rows:
            continue
        country = row_country(rows[0])
        channel = display_channel(rows)
        tvg_id = display_tvg_id(rows)
        wanted = matched_wanted.get(group_key)
        priority = target_priority(
            {"country": country, "channel": channel, "tvg_id": tvg_id},
            compiled_priority,
            wanted,
        )["priority"]
        _add_target(
            targets,
            {
                "country": country,
                "channel": channel,
                "tvg_id": tvg_id,
                "priority": priority,
                "status": derive_channel_status(rows),
            },
        )

    for wanted in unmatched_wanted:
        priority = str(wanted.get("priority") or "").strip().upper()
        if not priority:
            priority = target_priority(
                {
                    "country": wanted.get("country_code", ""),
                    "channel": wanted.get("channel", ""),
                    "tvg_id": wanted.get("tvg_id", ""),
                },
                compiled_priority,
                wanted,
            )["priority"]
        _add_target(
            targets,
            {
                "country": wanted.get("country_code", ""),
                "channel": wanted.get("channel", "") or wanted.get("tvg_id", ""),
                "tvg_id": wanted.get("tvg_id", ""),
                "priority": priority,
                "status": "NOT RESEARCHED",
            },
        )

    for target in unmatched_policy_targets:
        _add_target(
            targets,
            {
                "country": target.get("country_code", ""),
                "channel": target.get("channel", "") or target.get("tvg_id", ""),
                "tvg_id": target.get("tvg_id", ""),
                "priority": target.get("priority", ""),
                "status": "NOT RESEARCHED",
            },
        )

    configured_names = config.get("country_names") or {}
    configured_outputs = config.get("country_outputs") or {}
    country_order = [
        str(code or "").strip().upper()
        for code in configured_outputs
        if str(code or "").strip()
    ]
    for country in sorted({target["country"] for target in targets}):
        if country not in country_order:
            country_order.append(country)

    countries: dict[str, dict] = {}
    for country in country_order:
        country_targets = [target for target in targets if target["country"] == country]
        priorities: dict[str, dict] = {}
        for priority in TRACKED_PRIORITIES:
            items = [target for target in country_targets if target["priority"] == priority]
            items.sort(key=lambda item: (normalize_name(item.get("channel")), item.get("tvg_id", "")))
            missing = [item for item in items if item.get("status") != "WORKING"]
            priorities[priority] = {
                "found": len(items) - len(missing),
                "total": len(items),
                "logo_coverage": _priority_logo_summary(items, logo_quality),
                "missing": [
                    {
                        "channel": item.get("channel") or item.get("tvg_id") or "Unnamed channel",
                        "tvg_id": item.get("tvg_id", ""),
                        "status": item.get("status", "NOT RESEARCHED"),
                    }
                    for item in missing
                ],
            }
        countries[country] = {
            "name": str(configured_names.get(country) or country),
            "priorities": priorities,
        }

    return {
        "schema_version": 1,
        "definition": "found means at least one stable family feed (WORKING)",
        "logo_metric": {
            "definition": (
                "Among stable tracked P1/P2 targets only, logo availability counts Canonical plus "
                "Source fallback; canonical coverage counts reviewed logo overrides only."
            ),
            "denominator": "stable tracked P1/P2 targets",
        },
        "logo_summary": _priority_logo_summary(targets, logo_quality),
        "priorities": list(TRACKED_PRIORITIES),
        "countries": countries,
    }


def _esc(value: object) -> str:
    return html.escape(str(value or ""))


def _render_priority(priority: str, data: dict) -> str:
    found = int(data.get("found") or 0)
    total = int(data.get("total") or 0)
    missing = list(data.get("missing") or [])
    pct = (100.0 * found / total) if total else 0.0

    if missing:
        items = "".join(
            "<li><strong>"
            + _esc(item.get("channel"))
            + "</strong><span>"
            + _esc(STATUS_LABELS.get(item.get("status"), item.get("status") or "Missing"))
            + "</span></li>"
            for item in missing
        )
        detail = (
            '<details class="priority-coverage-missing">'
            f'<summary>{len(missing)} missing</summary>'
            f'<ul>{items}</ul>'
            "</details>"
        )
    elif total:
        detail = '<div class="priority-coverage-complete">✓ Complete</div>'
    else:
        detail = '<div class="priority-coverage-empty">No tracked targets</div>'

    return f"""
      <div class="priority-coverage-tier">
        <div class="priority-coverage-tier-head">
          <span class="badge {'rejected' if priority == 'P1' else 'review'}">{_esc(priority)}</span>
          <strong>{found}/{total}</strong>
          <span class="muted">stable</span>
        </div>
        <div class="priority-coverage-bar" role="progressbar" aria-label="{_esc(priority)} completeness" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{pct:.0f}">
          <span style="width:{pct:.1f}%"></span>
        </div>
        {detail}
      </div>
    """


def render_priority_coverage_html(coverage: dict) -> str:
    cards = []
    for code, country in (coverage.get("countries") or {}).items():
        priorities = country.get("priorities") or {}
        flag = FLAG_BY_COUNTRY.get(code, "🌐")
        cards.append(
            f"""
    <article class="priority-coverage-country" data-country="{_esc(code)}">
      <div class="priority-coverage-country-head">
        <h3>{flag} {_esc(country.get('name') or code)}</h3>
        <span class="muted">{_esc(code)}</span>
      </div>
      {_render_priority('P1', priorities.get('P1') or {})}
      {_render_priority('P2', priorities.get('P2') or {})}
    </article>
            """
        )

    return f"""{SECTION_START}
  <section id="priorityCoverage" class="panel priority-coverage" aria-labelledby="priorityCoverageHeading">
    <h2 id="priorityCoverageHeading">P1 / P2 completeness</h2>
    <p class="muted">
      A channel counts as found only when it has a stable family feed. Open a missing
      count to see exactly which priority channels still need work.
    </p>
    <div class="priority-coverage-grid">
      {''.join(cards)}
    </div>
  </section>
{SECTION_END}"""


def priority_coverage_style() -> str:
    return f"""{STYLE_START}
<style id="priorityCoverageStyles">
.priority-coverage {{ margin: 24px 0; border-left: 4px solid var(--accent); }}
.priority-coverage h2 {{ margin-top: 0; }}
.priority-coverage-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:12px; }}
.priority-coverage-country {{ border:1px solid var(--border); border-radius:10px; padding:14px; background:var(--bg); }}
.priority-coverage-country-head {{ display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px; }}
.priority-coverage-country-head h3 {{ margin:0; font-size:1.08rem; }}
.priority-coverage-tier + .priority-coverage-tier {{ margin-top:14px; padding-top:14px; border-top:1px solid var(--border); }}
.priority-coverage-tier-head {{ display:flex; align-items:center; gap:8px; }}
.priority-coverage-tier-head strong {{ font-size:1.3rem; }}
.priority-coverage-bar {{ height:7px; margin:8px 0; overflow:hidden; border-radius:999px; background:var(--border); }}
.priority-coverage-bar span {{ display:block; height:100%; border-radius:inherit; background:var(--good); }}
.priority-coverage-missing summary {{ width:max-content; cursor:pointer; color:var(--accent); font-weight:700; }}
.priority-coverage-missing ul {{ margin:8px 0 0; padding-left:20px; max-height:220px; overflow:auto; }}
.priority-coverage-missing li {{ margin:6px 0; }}
.priority-coverage-missing li span {{ display:block; color:var(--muted); font-size:.78rem; }}
.priority-coverage-complete {{ color:var(--good); font-weight:700; }}
.priority-coverage-empty {{ color:var(--muted); font-size:.9rem; }}
</style>
{STYLE_END}"""


def _replace_block(text: str, start: str, end: str, replacement: str) -> str:
    if start not in text:
        return text
    start_index = text.index(start)
    end_index = text.index(end, start_index) + len(end)
    return text[:start_index] + replacement + text[end_index:]


def inject_priority_coverage(index_path: Path, coverage: dict) -> None:
    if not index_path.is_file():
        raise RuntimeError(f"Dashboard does not exist: {index_path}")

    text = index_path.read_text(encoding="utf-8")
    style = priority_coverage_style()
    section = render_priority_coverage_html(coverage)

    if STYLE_START in text:
        text = _replace_block(text, STYLE_START, STYLE_END, style)
    else:
        marker = "</head>"
        if marker not in text:
            raise RuntimeError("Dashboard </head> marker not found for priority coverage styles.")
        text = text.replace(marker, style + "\n" + marker, 1)

    if SECTION_START in text:
        text = _replace_block(text, SECTION_START, SECTION_END, section)
    else:
        marker = '  <section id="nextWorkPanel"'
        if marker not in text:
            raise RuntimeError("Dashboard next-work marker not found for priority coverage scorecard.")
        text = text.replace(marker, section + "\n\n" + marker, 1)

    index_path.write_text(text, encoding="utf-8")


def generate_priority_coverage(
    *,
    audit_path: Path = Path("public/audit.csv"),
    index_path: Path = Path("public/index.html"),
    output_path: Path = Path("public/priority-coverage.json"),
    config_path: Path = Path("config.json"),
    priority_policy_path: Path = Path("data/research_priority.json"),
    wanted_channels_path: Path = Path("data/wanted_channels.json"),
    logo_quality_path: Path = Path("public/logo-quality.json"),
) -> dict:
    logo_quality = _load_json(logo_quality_path) if logo_quality_path.is_file() else {}
    coverage = build_priority_coverage(
        load_audit_rows(audit_path),
        config=_load_json(config_path),
        priority_policy=_load_json(priority_policy_path),
        wanted_channels=load_wanted_channels(wanted_channels_path),
        logo_quality=logo_quality,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    inject_priority_coverage(index_path, coverage)
    return coverage
