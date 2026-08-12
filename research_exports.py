#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from country_language import (
    legacy_country_scope_from_language_token,
    normalize_country_code,
)
from research_priority import (
    PRIORITY_ORDER,
    compile_research_priority_policy,
    priority_rank,
    resolve_research_priority,
)
from wanted_channels import load_wanted_channels


TESTED_STATUSES = {
    "works",
    "works_with_warning",
    "loads",
    "mrl_error",
    "format_error",
    "generic_error",
    "wrong_language",
}
GOOD_STATUSES = {
    "works",
    "works_with_warning",
}
STATUS_ORDER = {
    "WORKING": 0,
    "PARTIAL": 1,
    "CANDIDATES TO TEST": 2,
    "NO WORKING FEED": 3,
    "NOT RESEARCHED": 4,
}
STATUS_ICON = {
    "WORKING": "✅",
    "PARTIAL": "🟠",
    "CANDIDATES TO TEST": "🟡",
    "NO WORKING FEED": "❌",
    "NOT RESEARCHED": "⚪",
}
STATUS_GUIDANCE = {
    "WORKING": (
        "At least one stable TV-safe feed is available. No need to hunt for "
        "another source unless you want a replacement or quality upgrade."
    ),
    "PARTIAL": (
        "A known feed works on at least one test device, but there is no stable "
        "family feed yet. Finish compatibility testing or find a better feed."
    ),
    "CANDIDATES TO TEST": (
        "No stable feed is available yet, but current candidate URLs still need "
        "testing or review. Test these before hunting for more sources."
    ),
    "NO WORKING FEED": (
        "No usable feed is currently known. The recorded candidates are rejected, "
        "unsuitable, or historical; keep hunting for a new source."
    ),
    "NOT RESEARCHED": (
        "The channel is wanted, but no source URL has been recorded yet."
    ),
}


def truthy(value: object) -> bool:
    return str(value or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def normalized_status(value: object) -> str:
    return (
        str(value or "")
        .strip()
        .casefold()
        .replace("-", "_")
        .replace(" ", "_")
    )


def normalize_tvg_id(value: object) -> str:
    text = str(value or "").strip()
    return re.sub(r"@(SD|HD|FHD|UHD|4K|\d{3,4}P)$", "", text, flags=re.I).casefold()


def normalize_name(value: object) -> str:
    text = str(value or "").strip().casefold()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def legacy_expected_country(value: object) -> str:
    """Recover only old HU/SK/CZ-style country tokens from expected languages."""
    for raw in re.split(r"[,;/+]", str(value or "")):
        country = legacy_country_scope_from_language_token(raw)
        if country:
            return country
    return ""


def row_country(row: dict[str, str]) -> str:
    """Return research geography without conflating spoken language with country."""
    for field in (
        "playlist_country_code",
        "playlist_language_code",
    ):
        country = normalize_country_code(str(row.get(field) or ""))
        if country:
            return country

    # Historical audit.csv rows stored country-style HU/SK/CZ tokens in
    # expected_language_codes. Modern hun/slk/ces values are spoken-language
    # metadata and must never be promoted to HUN/SLK/CES country buckets.
    country = legacy_expected_country(row.get("expected_language_codes"))
    if country:
        return country

    country = normalize_country_code(str(row.get("language_code") or ""))
    return country or "UNKNOWN"


def channel_key(row: dict[str, str]) -> str:
    country = row_country(row)
    tvg_id = normalize_tvg_id(row.get("tvg_id"))
    if tvg_id:
        return f"{country}:id:{tvg_id}"
    return f"{country}:name:{normalize_name(row.get('channel'))}"


def is_current(row: dict[str, str]) -> bool:
    return truthy(row.get("in_playlist"))


def is_stable(row: dict[str, str]) -> bool:
    return truthy(row.get("in_stable_playlist"))


def status_is_tested(value: object) -> bool:
    return normalized_status(value) in TESTED_STATUSES


def row_has_any_success(row: dict[str, str]) -> bool:
    vlc = normalized_status(row.get("vlc"))
    samsung = normalized_status(row.get("samsung"))
    return vlc in GOOD_STATUSES or samsung == "works"


def row_needs_followup(row: dict[str, str]) -> bool:
    if not is_current(row):
        return False

    decision = str(row.get("decision") or "").strip()
    if decision == "Needs review":
        return True

    return not (
        status_is_tested(row.get("vlc"))
        and status_is_tested(row.get("samsung"))
    )


def derive_channel_status(rows: list[dict[str, str]]) -> str:
    current = [row for row in rows if is_current(row)]

    if any(is_stable(row) for row in current):
        return "WORKING"

    if any(row_has_any_success(row) for row in current):
        return "PARTIAL"

    if any(row_needs_followup(row) for row in current):
        return "CANDIDATES TO TEST"

    if rows:
        return "NO WORKING FEED"

    return "NOT RESEARCHED"


def work_type_for_status(status: str) -> str:
    return {
        "PARTIAL": "Finish compatibility",
        "CANDIDATES TO TEST": "Test candidates",
        "NOT RESEARCHED": "Find first candidate",
        "NO WORKING FEED": "Hunt new source",
    }.get(status, "Review")


def latest_test_date(rows: list[dict[str, str]]) -> str:
    values = sorted(
        {
            str(row.get("tested_on") or "").strip()
            for row in rows
            if str(row.get("tested_on") or "").strip()
        },
        reverse=True,
    )
    return values[0] if values else ""


def display_channel(rows: list[dict[str, str]]) -> str:
    for row in rows:
        value = str(row.get("channel") or "").strip()
        if value:
            return value
    return "Unnamed channel"


def display_tvg_id(rows: list[dict[str, str]]) -> str:
    for row in rows:
        value = str(row.get("tvg_id") or "").strip()
        if value:
            return value
    return ""


def feed_sort_key(row: dict[str, str]) -> tuple:
    try:
        feed_index = int(str(row.get("feed_index") or "1"))
    except ValueError:
        feed_index = 1

    return (
        0 if is_current(row) else 1,
        0 if is_stable(row) else 1,
        feed_index,
        str(row.get("source") or "").casefold(),
        str(row.get("stream_url") or "").casefold(),
    )


def load_audit_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise RuntimeError(
            f"Required research input does not exist: {path}. Run build.py first."
        )

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def group_channels(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(channel_key(row), []).append(row)

    for channel_rows in grouped.values():
        channel_rows.sort(key=feed_sort_key)

    return grouped


def match_wanted_channels(
    grouped: dict[str, list[dict[str, str]]],
    wanted_channels: list[dict[str, str]] | None,
) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    """Match wanted targets to audit groups without fuzzy or ambiguous guessing."""
    by_id: dict[tuple[str, str], list[str]] = {}
    by_name: dict[tuple[str, str], list[str]] = {}

    for key, rows in grouped.items():
        if not rows:
            continue
        country = row_country(rows[0])
        tvg_id = normalize_tvg_id(display_tvg_id(rows))
        name = normalize_name(display_channel(rows))
        if tvg_id:
            by_id.setdefault((country, tvg_id), []).append(key)
        if name:
            by_name.setdefault((country, name), []).append(key)

    matched: dict[str, dict[str, str]] = {}
    unmatched: list[dict[str, str]] = []

    for wanted in wanted_channels or []:
        country = str(wanted.get("country_code") or "").strip().upper()
        wanted_id = normalize_tvg_id(wanted.get("tvg_id"))
        wanted_name = normalize_name(wanted.get("channel"))
        candidates: list[str] = []

        if wanted_id:
            candidates = by_id.get((country, wanted_id), [])
            if len(candidates) > 1:
                raise ValueError(
                    f"Wanted channel {country} {wanted.get('channel')!r} matches multiple "
                    f"audit groups by tvg_id {wanted.get('tvg_id')!r}."
                )

        if not candidates and wanted_name:
            candidates = by_name.get((country, wanted_name), [])
            if len(candidates) > 1:
                raise ValueError(
                    f"Wanted channel {country} {wanted.get('channel')!r} matches multiple "
                    "audit groups by name; add an exact tvg_id to wanted_channels.json."
                )

        if not candidates:
            unmatched.append(wanted)
            continue

        key = candidates[0]
        if key in matched:
            raise ValueError(
                f"Multiple wanted channel entries resolve to the same audit group {key}."
            )
        matched[key] = wanted

    return matched, unmatched


def target_priority(
    row: dict[str, object],
    compiled_priority: dict,
    wanted: dict[str, str] | None,
) -> dict[str, str]:
    resolved = resolve_research_priority(row, compiled_priority)
    explicit = str((wanted or {}).get("priority") or "").strip().upper()
    if not explicit:
        return resolved

    reason = str((wanted or {}).get("reason") or "").strip()
    return {
        "priority": explicit,
        "label": compiled_priority["labels"][explicit],
        "reason": reason or f"Explicit wanted-channel priority {explicit}.",
        "matched_by": "wanted_channels",
    }


def make_research_rows(
    grouped: dict[str, list[dict[str, str]]],
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []

    for rows in grouped.values():
        status = derive_channel_status(rows)
        country = row_country(rows[0]) if rows else "UNKNOWN"
        channel = display_channel(rows)

        for row in rows:
            output.append(
                {
                    "country": country,
                    "channel": channel,
                    "channel_status": status,
                    "feed_label": row.get("feed_label", ""),
                    "tvg_id": row.get("tvg_id", ""),
                    "source": row.get("source", ""),
                    "discovery": row.get("discovery", ""),
                    "stream_url": row.get("stream_url", ""),
                    "protocol": row.get("protocol", ""),
                    "vlc": row.get("vlc", ""),
                    "vlc_note": row.get("vlc_note", ""),
                    "samsung": row.get("samsung", ""),
                    "samsung_note": row.get("samsung_note", ""),
                    "feed_status": row.get("decision", ""),
                    "language_match": row.get("language_match", ""),
                    "tested_on": row.get("tested_on", ""),
                    "current_candidate": is_current(row),
                    "stable_feed": is_stable(row),
                    "exclude_from_playlist": truthy(row.get("exclude_from_playlist")),
                    "provenance": row.get("provenance", ""),
                    "reason": row.get("reason", ""),
                    "notes": row.get("notes", ""),
                }
            )

    output.sort(
        key=lambda row: (
            str(row["country"]),
            normalize_name(row["channel"]),
            STATUS_ORDER.get(str(row["channel_status"]), 99),
            0 if row["current_candidate"] else 1,
            str(row["source"]).casefold(),
            str(row["stream_url"]).casefold(),
        )
    )
    return output


def make_missing_rows(
    grouped: dict[str, list[dict[str, str]]],
    *,
    priority_policy: dict | None = None,
    wanted_channels: list[dict[str, str]] | None = None,
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    compiled_priority = compile_research_priority_policy(priority_policy)
    matched_wanted, unmatched_wanted = match_wanted_channels(grouped, wanted_channels)

    for group_key, rows in grouped.items():
        status = derive_channel_status(rows)
        if status == "WORKING":
            continue

        country = row_country(rows[0]) if rows else "UNKNOWN"
        channel = display_channel(rows)
        tvg_id = display_tvg_id(rows)
        wanted = matched_wanted.get(group_key)

        current = [row for row in rows if is_current(row)]
        tested = [
            row
            for row in rows
            if status_is_tested(row.get("vlc"))
            or status_is_tested(row.get("samsung"))
        ]
        fully_tested = [
            row
            for row in rows
            if status_is_tested(row.get("vlc"))
            and status_is_tested(row.get("samsung"))
        ]
        followup = [row for row in current if row_needs_followup(row)]
        rejected = [
            row
            for row in rows
            if str(row.get("decision") or "").strip() == "Rejected"
            or truthy(row.get("exclude_from_playlist"))
        ]
        sources = sorted(
            {
                str(row.get("source") or "").strip()
                for row in rows
                if str(row.get("source") or "").strip()
            },
            key=str.casefold,
        )

        if status == "PARTIAL":
            next_action = (
                "Finish device compatibility testing; if Samsung still fails, "
                "hunt for a TV-compatible alternative."
            )
        elif status == "CANDIDATES TO TEST":
            next_action = "Test/review the current candidate feeds before hunting for more."
        else:
            next_action = "Hunt for a new source/feed."

        missing_row = {
            "country": country,
            "channel": channel,
            "wanted": bool(wanted),
            "status": status,
            "tvg_id": tvg_id,
            "known_feeds": len(rows),
            "current_candidates": len(current),
            "tested_feeds": len(tested),
            "fully_tested_feeds": len(fully_tested),
            "followup_candidates": len(followup),
            "rejected_feeds": len(rejected),
            "unique_sources": len(sources),
            "sources": " | ".join(sources),
            "last_tested": latest_test_date(rows),
            "next_action": next_action,
            "work_type": work_type_for_status(status),
        }
        priority = target_priority(missing_row, compiled_priority, wanted)
        missing_row.update(
            {
                "priority": priority["priority"],
                "priority_label": priority["label"],
                "priority_reason": priority["reason"],
                "priority_match": priority["matched_by"],
            }
        )
        output.append(missing_row)

    for wanted in unmatched_wanted:
        missing_row = {
            "country": wanted["country_code"],
            "channel": wanted["channel"],
            "wanted": True,
            "status": "NOT RESEARCHED",
            "tvg_id": wanted.get("tvg_id", ""),
            "known_feeds": 0,
            "current_candidates": 0,
            "tested_feeds": 0,
            "fully_tested_feeds": 0,
            "followup_candidates": 0,
            "rejected_feeds": 0,
            "unique_sources": 0,
            "sources": "",
            "last_tested": "",
            "next_action": "Find the first candidate source/feed.",
            "work_type": work_type_for_status("NOT RESEARCHED"),
        }
        priority = target_priority(missing_row, compiled_priority, wanted)
        missing_row.update(
            {
                "priority": priority["priority"],
                "priority_label": priority["label"],
                "priority_reason": priority["reason"],
                "priority_match": priority["matched_by"],
            }
        )
        output.append(missing_row)

    output.sort(
        key=lambda row: (
            priority_rank(row.get("priority")),
            0 if row.get("wanted") else 1,
            STATUS_ORDER.get(str(row["status"]), 99),
            str(row["country"]),
            normalize_name(row["channel"]),
        )
    )
    return output


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def md_text(value: object) -> str:
    return str(value or "").replace("\n", " ").strip()


def markdown_feed_label(row: dict[str, str], index: int) -> str:
    decision = str(row.get("decision") or "Needs review").strip().upper()
    source = str(row.get("source") or row.get("discovery") or "Unknown source").strip()
    return f"Source {index} — {decision} — {source}"


def make_research_markdown(
    grouped: dict[str, list[dict[str, str]]],
    generated_at: str,
) -> str:
    channels = []
    for rows in grouped.values():
        channels.append(
            (
                row_country(rows[0]) if rows else "UNKNOWN",
                display_channel(rows),
                derive_channel_status(rows),
                rows,
            )
        )

    channels.sort(key=lambda item: (item[0], normalize_name(item[1])))

    lines = [
        "# Tomas IPTV research ledger",
        "",
        f"Generated automatically: {generated_at}",
        "",
        "This file is generated from `public/audit.csv`. It is a research/history view, not a separate manual database.",
        "",
    ]

    current_country = None
    for country, channel, status, rows in channels:
        if country != current_country:
            if current_country is not None:
                lines.append("")
            lines.extend([f"# {country}", ""])
            current_country = country

        icon = STATUS_ICON.get(status, "•")
        lines.extend(
            [
                f"## {icon} {channel}",
                f"Status: **{status}**",
                "",
                STATUS_GUIDANCE.get(status, ""),
                "",
            ]
        )

        for index, row in enumerate(rows, start=1):
            lines.append(f"### {markdown_feed_label(row, index)}")
            url = md_text(row.get("stream_url"))
            lines.append(f"- URL: {url if url else '—'}")
            lines.append(f"- Feed: {md_text(row.get('feed_label')) or '—'}")
            lines.append(f"- VLC: {md_text(row.get('vlc')) or '—'}")
            lines.append(f"- Samsung: {md_text(row.get('samsung')) or '—'}")
            lines.append(f"- Current test candidate: {'Yes' if is_current(row) else 'No'}")
            lines.append(f"- Stable family feed: {'Yes' if is_stable(row) else 'No'}")
            tested_on = md_text(row.get("tested_on"))
            if tested_on:
                lines.append(f"- Tested: {tested_on}")
            reason = md_text(row.get("reason"))
            notes = md_text(row.get("notes"))
            if reason:
                lines.append(f"- Reason: {reason}")
            if notes:
                lines.append(f"- Notes: {notes}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def inject_dashboard_links(index_path: Path) -> None:
    if not index_path.is_file():
        raise RuntimeError(f"Dashboard does not exist: {index_path}. Run build.py first.")

    text = index_path.read_text(encoding="utf-8")
    if 'href="research.csv"' in text:
        return

    marker = '    <a href="audit.csv">Manual verification (CSV)</a>'
    replacement = "\n".join(
        [
            marker,
            '    <a href="research.csv">Research ledger (CSV)</a>',
            '    <a href="research.md">Research ledger (Markdown)</a>',
            '    <a href="missing.csv">Prioritized research work queue (CSV)</a>',
        ]
    )

    if marker not in text:
        raise RuntimeError(
            "Could not find the audit.csv dashboard link; refusing to patch an unknown dashboard layout."
        )

    index_path.write_text(text.replace(marker, replacement, 1), encoding="utf-8")


def load_priority_policy(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def generate_exports(
    public_dir: Path,
    generated_at: str | None = None,
    *,
    priority_policy: dict | None = None,
    wanted_channels: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    public_dir = Path(public_dir)
    audit_rows = load_audit_rows(public_dir / "audit.csv")
    grouped = group_channels(audit_rows)
    research_rows = make_research_rows(grouped)
    missing_rows = make_missing_rows(
        grouped,
        priority_policy=priority_policy,
        wanted_channels=wanted_channels,
    )

    generated_at = generated_at or datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    write_csv(
        public_dir / "research.csv",
        [
            "country",
            "channel",
            "channel_status",
            "feed_label",
            "tvg_id",
            "source",
            "discovery",
            "stream_url",
            "protocol",
            "vlc",
            "vlc_note",
            "samsung",
            "samsung_note",
            "feed_status",
            "language_match",
            "tested_on",
            "current_candidate",
            "stable_feed",
            "exclude_from_playlist",
            "provenance",
            "reason",
            "notes",
        ],
        research_rows,
    )

    write_csv(
        public_dir / "missing.csv",
        [
            "country",
            "channel",
            "wanted",
            "priority",
            "work_type",
            "status",
            "priority_label",
            "priority_reason",
            "priority_match",
            "tvg_id",
            "known_feeds",
            "current_candidates",
            "tested_feeds",
            "fully_tested_feeds",
            "followup_candidates",
            "rejected_feeds",
            "unique_sources",
            "sources",
            "last_tested",
            "next_action",
        ],
        missing_rows,
    )

    (public_dir / "research.md").write_text(
        make_research_markdown(grouped, generated_at),
        encoding="utf-8",
    )

    inject_dashboard_links(public_dir / "index.html")

    priority_counts = Counter(str(row.get("priority") or "") for row in missing_rows)
    wanted_missing = [row for row in missing_rows if row.get("wanted")]
    return {
        "channels": len(grouped),
        "research_rows": len(research_rows),
        "missing_channels": len(missing_rows),
        "wanted_channels": len(wanted_channels or []),
        "wanted_missing": len(wanted_missing),
        "wanted_not_researched": sum(
            1 for row in wanted_missing if row.get("status") == "NOT RESEARCHED"
        ),
        "priority_counts": {
            priority: priority_counts.get(priority, 0)
            for priority in PRIORITY_ORDER
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Tomas IPTV research exports from public/audit.csv."
    )
    parser.add_argument(
        "--public-dir",
        default="public",
        help="Generated public directory (default: public)",
    )
    parser.add_argument(
        "--priority-policy",
        type=Path,
        default=Path("research_priority.json"),
        help="Research priority policy JSON (default: research_priority.json)",
    )
    parser.add_argument(
        "--wanted-channels",
        type=Path,
        default=Path("wanted_channels.json"),
        help="Wanted channel catalog JSON (default: wanted_channels.json)",
    )
    args = parser.parse_args()

    stats = generate_exports(
        Path(args.public_dir),
        priority_policy=load_priority_policy(args.priority_policy),
        wanted_channels=load_wanted_channels(args.wanted_channels),
    )
    print(
        "Research exports complete: "
        f"{stats['channels']} encountered channels, "
        f"{stats['research_rows']} feed/history rows, "
        f"{stats['missing_channels']} channels needing attention."
    )
    print(
        "Wanted coverage: "
        f"{stats['wanted_channels']} targets, "
        f"{stats['wanted_missing']} not yet stable, "
        f"{stats['wanted_not_researched']} not researched."
    )
    priorities = stats["priority_counts"]
    print(
        "Research priorities: "
        + ", ".join(f"{priority} {priorities[priority]}" for priority in PRIORITY_ORDER)
    )


if __name__ == "__main__":
    main()
