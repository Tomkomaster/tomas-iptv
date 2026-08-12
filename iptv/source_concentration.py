#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter, defaultdict
from urllib.parse import urlparse

from feed_quality import classify_feed_source


SOURCE_TYPES = (
    "Official broadcaster",
    "Broadcaster CDN",
    "Third-party relay",
    "Unclassified",
)

DEFAULT_THRESHOLDS = {
    "warning_min_channels": 5,
    "warning_percent": 15.0,
    "high_min_channels": 10,
    "high_percent": 20.0,
    "critical_min_channels": 20,
    "critical_percent": 30.0,
}


def _settings(cfg: dict | None) -> dict[str, float | int]:
    configured = (cfg or {}).get("source_concentration") or {}
    if not isinstance(configured, dict):
        configured = {}
    result: dict[str, float | int] = dict(DEFAULT_THRESHOLDS)
    for key, default in DEFAULT_THRESHOLDS.items():
        raw = configured.get(key, default)
        try:
            if isinstance(default, int):
                result[key] = max(int(raw), 1)
            else:
                result[key] = max(float(raw), 0.0)
        except (TypeError, ValueError):
            result[key] = default
    return result


def _percent(count: int, total: int) -> float:
    return round((100.0 * count / total) if total else 0.0, 1)


def _relay_risk(relay_count: int, country_total: int, settings: dict) -> str:
    percent = _percent(relay_count, country_total)
    levels = (
        ("critical", "critical_min_channels", "critical_percent"),
        ("high", "high_min_channels", "high_percent"),
        ("warning", "warning_min_channels", "warning_percent"),
    )
    for severity, count_key, percent_key in levels:
        if relay_count >= int(settings[count_key]) and percent >= float(settings[percent_key]):
            return severity
    return ""


def _source_type_rows(counter: Counter, total: int) -> list[dict]:
    return [
        {
            "source_type": source_type,
            "channels": int(counter.get(source_type, 0)),
            "percent": _percent(int(counter.get(source_type, 0)), total),
        }
        for source_type in SOURCE_TYPES
    ]


def build_source_concentration(
    entries: list[dict],
    cfg: dict | None = None,
    *,
    generated_at: str = "",
) -> dict:
    """Summarize how the stable playlist is concentrated by hostname and provenance."""
    settings = _settings(cfg)
    records: list[dict] = []
    type_totals: Counter = Counter()
    country_totals: Counter = Counter()
    country_type_totals: dict[str, Counter] = defaultdict(Counter)
    country_hosts: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))

    for entry in entries:
        classification = classify_feed_source(entry, cfg)
        country = str(
            entry.get("country_code") or entry.get("language_code") or "UNKNOWN"
        ).strip().upper() or "UNKNOWN"
        hostname = str(classification.get("hostname") or "").strip().casefold()
        if not hostname:
            url = str(entry.get("url") or "").strip()
            hostname = (urlparse(url).hostname or "").strip().casefold() or "(no hostname)"
        source_type = str(classification.get("source_type") or "Unclassified")
        if source_type not in SOURCE_TYPES:
            source_type = "Unclassified"

        record = {
            "country_code": country,
            "channel": str(entry.get("channel_name") or entry.get("published_name") or "Unnamed channel"),
            "tvg_id": str(entry.get("tvg_id") or ""),
            "hostname": hostname,
            "source_type": source_type,
            "source": str(entry.get("source") or ""),
            "stream_url": str(entry.get("url") or ""),
            "feed_quality_score": int(entry.get("_feed_quality_score") or 0),
        }
        records.append(record)
        type_totals[source_type] += 1
        country_totals[country] += 1
        country_type_totals[country][source_type] += 1
        country_hosts[country][hostname].append(record)

    countries: dict[str, dict] = {}
    flags: list[dict] = []

    for country in sorted(country_totals):
        total = int(country_totals[country])
        host_rows: list[dict] = []
        for hostname, host_records in country_hosts[country].items():
            type_counts = Counter(item["source_type"] for item in host_records)
            relay_count = int(type_counts.get("Third-party relay", 0))
            severity = _relay_risk(relay_count, total, settings)
            if len([value for value in type_counts.values() if value]) == 1:
                source_type = next(iter(type_counts))
            else:
                source_type = "Mixed"

            host_row = {
                "hostname": hostname,
                "channels": len(host_records),
                "country_percent": _percent(len(host_records), total),
                "source_type": source_type,
                "source_types": {
                    key: int(type_counts.get(key, 0))
                    for key in SOURCE_TYPES
                    if type_counts.get(key, 0)
                },
                "third_party_relay_channels": relay_count,
                "third_party_relay_percent": _percent(relay_count, total),
                "risk": severity or "none",
                "channel_names": sorted({item["channel"] for item in host_records}),
            }
            host_rows.append(host_row)

            if severity:
                flags.append({
                    "severity": severity,
                    "country_code": country,
                    "hostname": hostname,
                    "channels": len(host_records),
                    "country_percent": host_row["country_percent"],
                    "third_party_relay_channels": relay_count,
                    "third_party_relay_percent": host_row["third_party_relay_percent"],
                    "message": (
                        f"{country}: {relay_count}/{total} stable channels "
                        f"({host_row['third_party_relay_percent']:.1f}%) depend on "
                        f"third-party relay hostname {hostname}."
                    ),
                })

        risk_order = {"critical": 0, "high": 1, "warning": 2, "none": 3}
        host_rows.sort(
            key=lambda row: (
                risk_order.get(str(row.get("risk")), 9),
                -int(row.get("channels") or 0),
                str(row.get("hostname") or ""),
            )
        )
        countries[country] = {
            "stable_channels": total,
            "source_types": _source_type_rows(country_type_totals[country], total),
            "hostnames": host_rows,
            "flagged_relays": [
                row for row in host_rows if str(row.get("risk")) != "none"
            ],
        }

    severity_order = {"critical": 0, "high": 1, "warning": 2}
    flags.sort(
        key=lambda item: (
            severity_order.get(str(item.get("severity")), 9),
            -int(item.get("third_party_relay_channels") or 0),
            str(item.get("country_code") or ""),
            str(item.get("hostname") or ""),
        )
    )

    total = len(records)
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "settings": settings,
        "summary": {
            "stable_channels": total,
            "hostnames": len({item["hostname"] for item in records}),
            "source_types": _source_type_rows(type_totals, total),
            "classified_channels": total - int(type_totals.get("Unclassified", 0)),
            "unclassified_channels": int(type_totals.get("Unclassified", 0)),
            "concentration_flags": len(flags),
        },
        "countries": countries,
        "flags": flags,
        "channels": records,
    }
