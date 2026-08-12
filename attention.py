#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from country_language import (
    legacy_country_scope_from_language_token,
    normalize_country_code,
)
from healthcheck import canonical_stream_url
from epg_policy import compile_epg_policy, resolve_epg_policy
from research_priority import normalize_name, normalize_tvg_id


SEVERITY_RANK = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

TV_SAFE_DECISIONS = {
    "Verified",
    "TV verified",
}

CATEGORY_LABELS = {
    "stream_manual_retest": "Stream needs manual retest",
    "stream_failure": "Automated stream failure",
    "manual_stale": "Manual test is old",
    "manual_date_missing": "Manual test date missing",
    "epg_mapped_empty": "EPG mapped but empty",
    "epg_unmapped": "No EPG mapping",
    "epg_missing_id": "No tvg-id for EPG",
    "upstream_missing": "Verified stream disappeared upstream",
    "relay_concentration": "Third-party relay concentration",
    "no_independent_backup": "No independent verified backup",
}


def load_json(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def parse_report_date(value: str) -> date:
    text = (value or "").strip()
    if not text:
        return datetime.now(timezone.utc).date()

    for fmt in (
        "%Y-%m-%d %H:%M:%S UTC",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass

    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return datetime.now(timezone.utc).date()


def parse_tested_on(value: str) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "y",
    }


def item_key(*, stream_url: str = "", tvg_id: str = "", channel: str = "") -> str:
    if stream_url:
        return "url:" + canonical_stream_url(stream_url)
    if tvg_id:
        return "id:" + tvg_id.strip().casefold()
    return "name:" + channel.strip().casefold()


def max_severity(signals: list[dict]) -> str:
    return max(
        (str(signal.get("severity") or "low") for signal in signals),
        key=lambda value: SEVERITY_RANK.get(value, 0),
        default="low",
    )


def manual_status(row: dict) -> str:
    return str(row.get("decision") or "Unknown").strip() or "Unknown"


def row_country(row: dict) -> str:
    """Return publication geography without promoting spoken language to country."""
    for key in (
        "output_country_code",
        "playlist_country_code",
        "country_code",
    ):
        country = normalize_country_code(str(row.get(key) or ""))
        if country:
            return country

    for key in (
        "output_language_code",
        "playlist_language_code",
    ):
        country = legacy_country_scope_from_language_token(row.get(key))
        if country:
            return country

    expected = row.get("expected_language_codes")
    if isinstance(expected, (list, tuple, set)):
        expected_values = list(expected)
    else:
        expected_values = str(expected or "").replace(";", ",").replace("/", ",").split(",")

    for value in expected_values:
        country = legacy_country_scope_from_language_token(value)
        if country:
            return country

    country = normalize_country_code(str(row.get("language_code") or ""))
    return country or "UNKNOWN"


def stream_hostname(url: object) -> str:
    try:
        return (urlparse(str(url or "").strip()).hostname or "").strip().casefold()
    except ValueError:
        return ""


def row_logical_key(row: dict) -> tuple[str, str, str]:
    """Match audit alternatives conservatively within one publication country."""
    country = row_country(row)

    canonical_id = str(row.get("canonical_id") or "").strip().casefold()
    if canonical_id:
        return (country, "canonical", canonical_id)

    tvg_id = normalize_tvg_id(row.get("tvg_id"))
    if tvg_id:
        return (country, "tvg_id", tvg_id)

    return (
        country,
        "channel",
        normalize_name(row.get("channel") or row.get("channel_name") or ""),
    )


def current_tv_safe(row: dict) -> bool:
    return (
        truthy(row.get("in_playlist"))
        and manual_status(row) in TV_SAFE_DECISIONS
        and not truthy(row.get("exclude_from_playlist"))
        and not truthy(row.get("excluded"))
        and bool(str(row.get("stream_url") or "").strip())
    )


def concentration_attention_severity(value: object) -> tuple[str, int]:
    severity = str(value or "").strip().casefold()
    return {
        "critical": ("critical", 95),
        "high": ("high", 85),
        "warning": ("medium", 65),
    }.get(severity, ("medium", 60))


def make_base_item(row: dict | None = None, *, channel: str = "", tvg_id: str = "", stream_url: str = "") -> dict:
    row = row or {}
    return {
        "country": row_country(row),
        "channel": str(row.get("channel") or channel or "Unnamed channel").strip(),
        "tvg_id": str(row.get("tvg_id") or tvg_id or "").strip(),
        "stream_url": str(row.get("stream_url") or stream_url or "").strip(),
        "source": str(row.get("source") or "").strip(),
        "manual_status": manual_status(row),
        "tested_on": str(row.get("tested_on") or "").strip(),
        "auto_status": "Unknown",
        "consecutive_failures": 0,
        "epg_status": "Unknown",
        "epg_policy": "unknown",
        "epg_policy_reason": "",
        "epg_policy_match": "",
        "signals": [],
    }


def add_signal(item: dict, signal: dict) -> None:
    category = str(signal.get("category") or "")
    if category and any(existing.get("category") == category for existing in item["signals"]):
        return
    item["signals"].append(signal)


def build_attention(
    report: dict,
    *,
    health: dict | None = None,
    epg_coverage: dict | None = None,
    epg_health: dict | None = None,
    epg_policy: dict | None = None,
    source_concentration: dict | None = None,
    config: dict | None = None,
    reference_date: date | None = None,
) -> dict:
    health = health or {}
    epg_coverage = epg_coverage or {}
    epg_health = epg_health or {}
    epg_policy = epg_policy or {}
    source_concentration = source_concentration or {}
    config = config or {}

    epg_policy_default, epg_policy_indexes = compile_epg_policy(epg_policy)

    generated_at = str(report.get("generated_at") or "").strip()
    today = reference_date or parse_report_date(generated_at)

    attention_cfg = config.get("attention") or {}
    stale_days = max(int(attention_cfg.get("manual_stale_days") or 30), 1)
    very_stale_days = max(
        int(attention_cfg.get("manual_very_stale_days") or 90),
        stale_days,
    )

    audit_rows = ((report.get("audit") or {}).get("channels") or [])
    stable_rows = [
        row
        for row in audit_rows
        if isinstance(row, dict) and truthy(row.get("in_stable_playlist"))
    ]

    stable_by_url = {
        canonical_stream_url(str(row.get("stream_url") or "")): row
        for row in stable_rows
        if str(row.get("stream_url") or "").strip()
    }
    stable_by_tvg = {
        str(row.get("tvg_id") or "").strip(): row
        for row in stable_rows
        if str(row.get("tvg_id") or "").strip()
    }

    items: dict[str, dict] = {}

    def get_item(row: dict | None = None, *, channel: str = "", tvg_id: str = "", stream_url: str = "") -> dict:
        base = make_base_item(row, channel=channel, tvg_id=tvg_id, stream_url=stream_url)
        key = item_key(
            stream_url=base["stream_url"],
            tvg_id=base["tvg_id"],
            channel=base["channel"],
        )
        if key not in items:
            items[key] = base
        else:
            current = items[key]
            for field in (
                "country",
                "channel",
                "tvg_id",
                "stream_url",
                "source",
                "manual_status",
                "tested_on",
            ):
                if not current.get(field) and base.get(field):
                    current[field] = base[field]
        return items[key]

    # 1) Automated stream failures. Playable redirects/slow-start warnings stay
    # visible in health.json, but this queue is intentionally for failures.
    for stream in health.get("streams", []) or []:
        if not isinstance(stream, dict) or truthy(stream.get("success")):
            continue
        if (
            stream.get("actionable_failure") is False
            or str(stream.get("attention") or "").strip().casefold() == "informational"
        ):
            continue

        url = str(stream.get("stream_url") or "").strip()
        row = stable_by_url.get(canonical_stream_url(url))
        item = get_item(
            row,
            channel=str(stream.get("channel") or ""),
            tvg_id=str(stream.get("tvg_id") or ""),
            stream_url=url,
        )
        item["auto_status"] = str(stream.get("status") or "Failed")
        item["consecutive_failures"] = int(stream.get("consecutive_failures") or 0)

        streak = max(item["consecutive_failures"], 1)
        detail = str(stream.get("detail") or "Automated stream probe failed.").strip()

        if truthy(stream.get("manual_retest_recommended")) or streak >= 3:
            add_signal(item, {
                "category": "stream_manual_retest",
                "severity": "critical",
                "priority": 100,
                "label": CATEGORY_LABELS["stream_manual_retest"],
                "detail": f"Failed {streak} consecutive daily checks. {detail}",
                "action": "Retest this exact URL in VLC and on the Samsung TV before changing its manual status.",
            })
        else:
            severity = "high" if streak >= 2 else "medium"
            priority = 80 if streak >= 2 else 60
            add_signal(item, {
                "category": "stream_failure",
                "severity": severity,
                "priority": priority,
                "label": CATEGORY_LABELS["stream_failure"],
                "detail": f"Automated status: {item['auto_status']} (failure streak ×{streak}). {detail}",
                "action": (
                    "If the next daily check also fails, keep watching the streak; manual VLC + Samsung testing remains authoritative."
                    if streak == 1
                    else "A second daily failure was recorded. Consider a manual VLC + Samsung retest now."
                ),
            })

    # 2) Stale or undated manual verification for streams that are currently
    # published in the stable family playlist.
    for row in stable_rows:
        item = None
        tested = parse_tested_on(str(row.get("tested_on") or ""))
        if tested is None:
            item = get_item(row)
            add_signal(item, {
                "category": "manual_date_missing",
                "severity": "low",
                "priority": 25,
                "label": CATEGORY_LABELS["manual_date_missing"],
                "detail": "This stable stream has manual verification but no usable tested_on date.",
                "action": "Retest in VLC + Samsung when convenient and record the test date.",
            })
            continue

        age_days = (today - tested).days
        if age_days < stale_days:
            continue

        item = get_item(row)
        very_stale = age_days >= very_stale_days
        add_signal(item, {
            "category": "manual_stale",
            "severity": "high" if very_stale else "medium",
            "priority": 75 if very_stale else 50,
            "label": CATEGORY_LABELS["manual_stale"],
            "detail": (
                f"Last manual VLC/Samsung verification was {age_days} days ago "
                f"({row.get('tested_on')})."
            ),
            "action": "Repeat the manual VLC + Samsung playback test and update tested_on.",
        })

    # 3) EPG gaps for current stable streams. The policy layer keeps
    # genuinely actionable guide gaps in this queue while allowing local,
    # web, event, and other schedule-light channels to opt out explicitly.
    matched_ids = {
        str(entry.get("tvg_id") or "").strip()
        for entry in (epg_coverage.get("matched") or [])
        if isinstance(entry, dict) and str(entry.get("tvg_id") or "").strip()
    }
    unmatched_ids = {
        str(value).strip()
        for value in (epg_coverage.get("unmatched_tvg_ids") or [])
        if str(value).strip()
    }
    mapped_empty = {
        str(entry.get("tvg_id") or "").strip(): str(entry.get("provider") or "").strip()
        for entry in (epg_health.get("mapped_without_programmes") or [])
        if isinstance(entry, dict) and str(entry.get("tvg_id") or "").strip()
    }

    epg_policy_counts = Counter()
    epg_suppressed_gap_counts = Counter()

    def apply_epg_policy(item: dict, policy: dict) -> None:
        item["epg_policy"] = str(policy.get("status") or "expected")
        item["epg_policy_reason"] = str(policy.get("reason") or "")
        item["epg_policy_match"] = str(policy.get("matched_by") or "default")

    for row in stable_rows:
        policy = resolve_epg_policy(
            row,
            default=epg_policy_default,
            indexes=epg_policy_indexes,
        )
        policy_status = str(policy.get("status") or epg_policy_default)
        epg_policy_counts[policy_status] += 1

        tvg_id = str(row.get("tvg_id") or "").strip()
        row_key = item_key(
            stream_url=str(row.get("stream_url") or ""),
            tvg_id=tvg_id,
            channel=str(row.get("channel") or ""),
        )
        existing_item = items.get(row_key)
        if existing_item is not None:
            apply_epg_policy(existing_item, policy)

        category = ""
        severity = "low"
        priority = 0
        label = ""
        detail = ""
        action = ""
        gap_status = ""

        if not tvg_id:
            category = "epg_missing_id"
            severity = "low"
            priority = 30
            label = CATEGORY_LABELS[category]
            gap_status = "No tvg-id"
            detail = (
                "The stable stream has no tvg-id, so it cannot be matched to "
                "the generated XMLTV guide."
            )
            action = "Find the correct channel tvg-id and add it to the source/extra entry."
        elif tvg_id in mapped_empty:
            provider = mapped_empty[tvg_id] or "selected EPG provider"
            category = "epg_mapped_empty"
            severity = "medium"
            priority = 45
            label = CATEGORY_LABELS[category]
            gap_status = "Mapped, no programmes"
            detail = (
                f"{tvg_id} maps to {provider}, but no current/future programme "
                "entries were produced."
            )
            action = "Check the provider mapping/data or add a working EPG fallback for this channel."
        elif tvg_id in unmatched_ids:
            category = "epg_unmapped"
            severity = "low"
            priority = 35
            label = CATEGORY_LABELS[category]
            gap_status = "Unmapped"
            detail = f"No EPG source currently maps playlist id {tvg_id}."
            action = "Find an exact deterministic EPG mapping or provider for this channel."
        elif tvg_id in matched_ids:
            if existing_item is not None:
                existing_item["epg_status"] = "Programme data"
            continue
        else:
            continue

        if policy_status != "expected":
            epg_suppressed_gap_counts[policy_status] += 1
            if existing_item is not None:
                if policy_status == "not_expected":
                    existing_item["epg_status"] = "Not expected"
                else:
                    existing_item["epg_status"] = f"Optional: {gap_status}"
            continue

        item = get_item(row)
        apply_epg_policy(item, policy)
        item["epg_status"] = gap_status
        add_signal(item, {
            "category": category,
            "severity": severity,
            "priority": priority,
            "label": label,
            "detail": detail,
            "action": action,
        })

    # 4) Previously TV-safe verified URLs that no longer exist in any current
    # source/test candidate. This is advisory history, not automatic deletion.
    for row in audit_rows:
        if not isinstance(row, dict):
            continue
        if truthy(row.get("in_playlist")):
            continue
        if manual_status(row) not in TV_SAFE_DECISIONS:
            continue
        url = str(row.get("stream_url") or "").strip()
        if not url:
            continue

        item = get_item(row)
        add_signal(item, {
            "category": "upstream_missing",
            "severity": "high",
            "priority": 85,
            "label": CATEGORY_LABELS["upstream_missing"],
            "detail": "This URL was previously manually TV-safe, but it is absent from all current source and extras inputs.",
            "action": "Look for a replacement/current URL. If the station/feed is intentionally retired, keep or clean the historical audit deliberately.",
        })

    # 5) Source-concentration and independent-backup reliability.
    #
    # source-concentration.json describes the exact stable winners. Audit rows
    # describe every current manually reviewed alternative. Combining both lets
    # us distinguish a broad relay dependency from the channels that actually
    # lack a manually verified feed on another hostname.
    concentration_channels_by_url = {
        canonical_stream_url(str(record.get("stream_url") or "")): record
        for record in (source_concentration.get("channels") or [])
        if isinstance(record, dict) and str(record.get("stream_url") or "").strip()
    }
    concentration_flags = [
        flag
        for flag in (source_concentration.get("flags") or [])
        if isinstance(flag, dict)
        and str(flag.get("hostname") or "").strip()
        and str(flag.get("country_code") or "").strip()
    ]
    flagged_hosts = {
        (
            normalize_country_code(str(flag.get("country_code") or "")) or "UNKNOWN",
            str(flag.get("hostname") or "").strip().casefold(),
        ): flag
        for flag in concentration_flags
    }

    safe_rows_by_channel: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in audit_rows:
        if isinstance(row, dict) and current_tv_safe(row):
            safe_rows_by_channel[row_logical_key(row)].append(row)

    no_backup_by_host: Counter = Counter()
    relay_stable_by_host: Counter = Counter()
    independent_backup_channels = 0

    for row in stable_rows:
        stable_url = str(row.get("stream_url") or "").strip()
        stable_url_key = canonical_stream_url(stable_url)
        concentration_record = concentration_channels_by_url.get(stable_url_key)
        if not concentration_record:
            continue
        if str(concentration_record.get("source_type") or "") != "Third-party relay":
            continue

        country = row_country(row)
        hostname = stream_hostname(stable_url)
        if not hostname:
            continue

        relay_stable_by_host[(country, hostname)] += 1
        logical_key = row_logical_key(row)
        backup_hostnames = sorted({
            stream_hostname(candidate.get("stream_url"))
            for candidate in safe_rows_by_channel.get(logical_key, [])
            if canonical_stream_url(str(candidate.get("stream_url") or "")) != stable_url_key
            and stream_hostname(candidate.get("stream_url"))
            and stream_hostname(candidate.get("stream_url")) != hostname
        })

        if backup_hostnames:
            independent_backup_channels += 1
            continue

        concentrated = (country, hostname) in flagged_hosts
        no_backup_by_host[(country, hostname)] += 1
        item = get_item(row)
        item["stable_hostname"] = hostname
        item["verified_backup_hostnames"] = []
        item["redundancy_status"] = "Fragile"
        add_signal(item, {
            "category": "no_independent_backup",
            "severity": "high" if concentrated else "medium",
            "priority": 90 if concentrated else 65,
            "label": CATEGORY_LABELS["no_independent_backup"],
            "detail": (
                f"The stable feed is a third-party relay on {hostname} and no current "
                "manually TV-safe alternative exists on another hostname."
            ),
            "action": (
                "Find and manually verify an independent backup feed. Prefer a direct "
                "broadcaster or broadcaster-CDN source when available."
            ),
        })

    for flag in concentration_flags:
        country = normalize_country_code(str(flag.get("country_code") or "")) or "UNKNOWN"
        hostname = str(flag.get("hostname") or "").strip().casefold()
        if not hostname:
            continue

        severity, priority = concentration_attention_severity(flag.get("severity"))
        relay_channels = int(
            flag.get("third_party_relay_channels")
            or relay_stable_by_host.get((country, hostname), 0)
            or 0
        )
        no_backup = int(no_backup_by_host.get((country, hostname), 0))
        country_percent = float(flag.get("third_party_relay_percent") or 0.0)

        host_row = {
            "output_country_code": country,
            "channel": f"Relay dependency: {hostname}",
            "source": hostname,
            "decision": "Infrastructure",
        }
        item = get_item(host_row)
        item["stable_hostname"] = hostname
        item["redundancy_status"] = "Concentrated relay dependency"
        add_signal(item, {
            "category": "relay_concentration",
            "severity": severity,
            "priority": priority,
            "label": CATEGORY_LABELS["relay_concentration"],
            "detail": (
                f"{relay_channels} stable {country} channels ({country_percent:.1f}% of "
                f"the country playlist) depend on third-party relay hostname {hostname}. "
                f"{no_backup} of those channels have no current manually TV-safe feed "
                "on another hostname."
            ),
            "action": (
                "Prioritize independent verified backups for the affected channels, "
                "starting with those that currently have no second hostname."
            ),
        })

    # Fill current statuses from health where possible, including healthy
    # streams that also have an unrelated attention signal such as missing EPG.
    health_by_url = {
        canonical_stream_url(str(stream.get("stream_url") or "")): stream
        for stream in (health.get("streams") or [])
        if isinstance(stream, dict) and str(stream.get("stream_url") or "").strip()
    }
    for item in items.values():
        url = str(item.get("stream_url") or "").strip()
        if url:
            stream = health_by_url.get(canonical_stream_url(url))
            if stream:
                item["auto_status"] = str(stream.get("status") or "Unknown")
                item["consecutive_failures"] = int(stream.get("consecutive_failures") or 0)

        tvg_id = str(item.get("tvg_id") or "").strip()
        if item.get("epg_status") == "Unknown" and tvg_id:
            if tvg_id in mapped_empty:
                item["epg_status"] = "Mapped, no programmes"
            elif tvg_id in unmatched_ids:
                item["epg_status"] = "Unmapped"
            elif tvg_id in matched_ids:
                item["epg_status"] = "Programme data"

        item["signals"].sort(
            key=lambda signal: (
                -int(signal.get("priority") or 0),
                str(signal.get("label") or "").casefold(),
            )
        )
        item["severity"] = max_severity(item["signals"])
        item["priority_score"] = max(
            (int(signal.get("priority") or 0) for signal in item["signals"]),
            default=0,
        ) + min(max(len(item["signals"]) - 1, 0) * 5, 15)
        item["reason_count"] = len(item["signals"])

    output_items = sorted(
        items.values(),
        key=lambda item: (
            -int(item.get("priority_score") or 0),
            -SEVERITY_RANK.get(str(item.get("severity") or "low"), 0),
            str(item.get("channel") or "").casefold(),
        ),
    )

    severity_counts = Counter(item["severity"] for item in output_items)
    category_counts = Counter(
        signal["category"]
        for item in output_items
        for signal in item["signals"]
    )

    overall_status = (
        "critical"
        if severity_counts.get("critical", 0)
        else "attention"
        if output_items
        else "healthy"
    )

    return {
        "schema_version": 3,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "reference_date": today.isoformat(),
        "advisory_only": True,
        "status": overall_status,
        "settings": {
            "manual_stale_days": stale_days,
            "manual_very_stale_days": very_stale_days,
            "epg_policy_default": epg_policy_default,
        },
        "summary": {
            "items": len(output_items),
            "critical": severity_counts.get("critical", 0),
            "high": severity_counts.get("high", 0),
            "medium": severity_counts.get("medium", 0),
            "low": severity_counts.get("low", 0),
            "severity_counts": dict(sorted(severity_counts.items())),
            "category_counts": dict(sorted(category_counts.items())),
            "epg_policy_counts": {
                status: epg_policy_counts.get(status, 0)
                for status in ("expected", "optional", "not_expected")
            },
            "epg_suppressed_gaps": sum(epg_suppressed_gap_counts.values()),
            "epg_suppressed_gap_counts": {
                status: epg_suppressed_gap_counts.get(status, 0)
                for status in ("optional", "not_expected")
            },
            "relay_concentration_hosts": len(concentration_flags),
            "relay_stable_channels": sum(relay_stable_by_host.values()),
            "relay_channels_with_independent_backup": independent_backup_channels,
            "relay_channels_without_independent_backup": sum(no_backup_by_host.values()),
        },
        "category_labels": CATEGORY_LABELS,
        "items": output_items,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build one advisory Needs attention queue from stream, manual-test, EPG, "
            "upstream-source, source-concentration, and redundancy signals."
        )
    )
    parser.add_argument("--report", type=Path, default=Path("public/report.json"))
    parser.add_argument("--health", type=Path, default=Path("public/health.json"))
    parser.add_argument("--epg-coverage", type=Path, default=Path("public/epg-coverage.json"))
    parser.add_argument("--epg-health", type=Path, default=Path("public/epg-health.json"))
    parser.add_argument("--epg-policy", type=Path, default=Path("epg_policy.json"))
    parser.add_argument(
        "--source-concentration",
        type=Path,
        default=Path("public/source-concentration.json"),
    )
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--output", type=Path, default=Path("public/attention.json"))
    args = parser.parse_args()

    if not args.report.is_file():
        raise SystemExit(f"Attention report requires {args.report}.")

    result = build_attention(
        load_json(args.report),
        health=load_json(args.health),
        epg_coverage=load_json(args.epg_coverage),
        epg_health=load_json(args.epg_health),
        epg_policy=load_json(args.epg_policy),
        source_concentration=load_json(args.source_concentration),
        config=load_json(args.config),
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = result["summary"]
    print(
        "Needs attention: "
        f"{summary['items']} items — "
        f"{summary['critical']} critical, "
        f"{summary['high']} high, "
        f"{summary['medium']} medium, "
        f"{summary['low']} low."
    )


if __name__ == "__main__":
    main()
