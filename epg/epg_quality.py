#!/usr/bin/env python3
"""Measure tvg-id identity quality and practical EPG completeness.

This report works at the stable *logical channel* level. Multiple feeds of the
same channel therefore do not inflate coverage or create false tvg-id
collisions.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from epg.epg_policy import compile_epg_policy, resolve_epg_policy


QUALITY_EXACT = "Exact tvg-id"
QUALITY_ALIAS = "Alias"
QUALITY_GUESSED = "Guessed"
QUALITY_MISSING = "Missing"
QUALITY_UNAVAILABLE = "EPG unavailable"
QUALITY_CATEGORIES = (
    QUALITY_EXACT,
    QUALITY_ALIAS,
    QUALITY_GUESSED,
    QUALITY_MISSING,
    QUALITY_UNAVAILABLE,
)

EXACT_MATCH_TYPES = frozenset({
    "exact",
    "external_exact_id",
    "local_schedule_exact_id",
})
ALIAS_MATCH_TYPES = frozenset({
    "external_explicit_alias",
    "external_explicit_cross_country_alias",
})
GUESSED_MATCH_TYPES = frozenset({
    "quality_variant",
    "external_quality_id",
    "external_unique_name",
})
TV_SAFE_DECISIONS = frozenset({"Verified", "TV verified"})


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y"}


def _country(value) -> str:
    code = str(value or "").strip().upper()
    return code if re.fullmatch(r"[A-Z]{2,3}", code) else "UNKNOWN"


def _name_key(value) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _logical_key(row: dict) -> str:
    country = _country(
        row.get("country_code")
        or row.get("output_country_code")
        or row.get("playlist_country_code")
    )
    canonical_id = str(row.get("canonical_id") or "").strip().casefold()
    if canonical_id:
        return f"{country}:canonical:{canonical_id}"
    explicit = str(row.get("key") or "").strip()
    if explicit:
        return explicit
    name = str(row.get("name") or row.get("channel") or row.get("channel_name") or "").strip()
    return f"{country}:name:{_name_key(name)}"


def mapping_quality_for_match_type(match_type: str) -> str:
    """Collapse implementation-specific match types into user-facing trust tiers."""
    token = str(match_type or "").strip()
    if token in EXACT_MATCH_TYPES:
        return "exact"
    if token in ALIAS_MATCH_TYPES:
        return "alias"
    if token in GUESSED_MATCH_TYPES:
        return "guessed"
    # A future non-empty automatic matcher is conservative by default. It must
    # be explicitly promoted to exact/alias here before the dashboard trusts it.
    return "guessed" if token else "unmapped"


def _match_has_programmes(match: dict | None, mapped_without_programmes: set[str]) -> bool:
    if not match:
        return False
    tvg_key = str(match.get("tvg_id") or "").strip().casefold()
    if tvg_key in mapped_without_programmes:
        return False
    if "fresh_programmes" in match:
        try:
            return int(match.get("fresh_programmes") or 0) > 0
        except (TypeError, ValueError):
            return False
    # Older coverage fixtures did not expose fresh_programmes. epg-health's
    # mapped_without_programmes list is authoritative in that schema.
    return True


def _stable_audit_rows(report: dict) -> list[dict]:
    rows = ((report.get("audit") or {}).get("channels") or [])
    return [
        row for row in rows
        if isinstance(row, dict) and _truthy(row.get("in_stable_playlist"))
    ]


def _representative_audit_rows(
    logical_channels: list[dict],
    stable_audit_rows: list[dict],
) -> dict[str, dict]:
    by_canonical: dict[tuple[str, str], dict] = {}
    by_name: dict[tuple[str, str], dict] = {}
    by_tvg: dict[str, list[dict]] = defaultdict(list)

    for row in stable_audit_rows:
        country = _country(
            row.get("output_country_code")
            or row.get("playlist_country_code")
            or row.get("country_code")
        )
        canonical = str(row.get("canonical_id") or "").strip().casefold()
        if canonical:
            by_canonical.setdefault((country, canonical), row)
        name = _name_key(row.get("channel") or row.get("channel_name") or "")
        if name:
            by_name.setdefault((country, name), row)
        tvg = str(row.get("tvg_id") or "").strip().casefold()
        if tvg:
            by_tvg[tvg].append(row)

    result: dict[str, dict] = {}
    for channel in logical_channels:
        key = _logical_key(channel)
        country = _country(channel.get("country_code"))
        canonical = str(channel.get("canonical_id") or "").strip().casefold()
        name = _name_key(channel.get("name") or "")
        tvg = str(channel.get("tvg_id") or "").strip().casefold()
        row = None
        if canonical:
            row = by_canonical.get((country, canonical))
        if row is None and name:
            row = by_name.get((country, name))
        if row is None and tvg and len(by_tvg.get(tvg, [])) == 1:
            row = by_tvg[tvg][0]
        if row is not None:
            result[key] = row
    return result


def _policy_for_channel(
    channel: dict,
    representative: dict | None,
    *,
    default: str,
    indexes: dict,
) -> dict:
    row = dict(representative or {})
    row.setdefault("channel", str(channel.get("name") or ""))
    row.setdefault("tvg_id", str(channel.get("tvg_id") or ""))
    country = _country(channel.get("country_code"))
    if country != "UNKNOWN":
        row.setdefault("country_code", country)
        row.setdefault("output_country_code", country)
    return resolve_epg_policy(row, default=default, indexes=indexes)


def _quality_category(tvg_id: str, match: dict | None, programmes: bool) -> tuple[str, str]:
    if not str(tvg_id or "").strip():
        return QUALITY_MISSING, "missing"
    if match is None or not programmes:
        mapping = mapping_quality_for_match_type(str((match or {}).get("match_type") or ""))
        return QUALITY_UNAVAILABLE, mapping
    mapping = mapping_quality_for_match_type(str(match.get("match_type") or ""))
    if mapping == "exact":
        return QUALITY_EXACT, mapping
    if mapping == "alias":
        return QUALITY_ALIAS, mapping
    return QUALITY_GUESSED, mapping


def _collision_report(logical_channels: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    display_id: dict[str, str] = {}
    for channel in logical_channels:
        tvg_id = str(channel.get("tvg_id") or "").strip()
        if not tvg_id:
            continue
        token = tvg_id.casefold()
        display_id.setdefault(token, tvg_id)
        grouped[token].append(channel)

    collisions: list[dict] = []
    for token, rows in grouped.items():
        distinct: dict[str, dict] = {}
        for row in rows:
            distinct.setdefault(_logical_key(row), row)
        if len(distinct) < 2:
            continue
        channels = [
            {
                "key": key,
                "channel": str(row.get("name") or "Unnamed channel"),
                "country_code": _country(row.get("country_code")),
                "canonical_id": str(row.get("canonical_id") or ""),
            }
            for key, row in sorted(
                distinct.items(),
                key=lambda item: (_country(item[1].get("country_code")), _name_key(item[1].get("name"))),
            )
        ]
        collisions.append({
            "tvg_id": display_id[token],
            "logical_channel_count": len(channels),
            "channels": channels,
        })
    collisions.sort(key=lambda item: str(item["tvg_id"]).casefold())
    return collisions


def _verified_epg_gaps(
    stable_audit_rows: list[dict],
    mapped_ids: set[str],
    mapped_without_programmes: set[str],
) -> tuple[list[dict], list[dict]]:
    without_mapping: dict[str, dict] = {}
    mapped_empty: dict[str, dict] = {}

    for row in stable_audit_rows:
        decision = str(row.get("decision") or "").strip()
        if decision not in TV_SAFE_DECISIONS:
            continue
        country = _country(
            row.get("output_country_code")
            or row.get("playlist_country_code")
            or row.get("country_code")
        )
        channel = str(row.get("channel") or row.get("channel_name") or "Unnamed channel").strip()
        tvg_id = str(row.get("tvg_id") or "").strip()
        token = tvg_id.casefold()
        identity = _logical_key({
            "country_code": country,
            "canonical_id": row.get("canonical_id"),
            "name": channel,
        })
        base = {
            "key": identity,
            "country_code": country,
            "channel": channel,
            "tvg_id": tvg_id,
            "decision": decision,
            "stream_url": str(row.get("stream_url") or "").strip(),
        }
        if not tvg_id:
            without_mapping.setdefault(identity, {**base, "issue": "missing_tvg_id"})
        elif token not in mapped_ids:
            without_mapping.setdefault(identity, {**base, "issue": "no_epg_mapping"})
        elif token in mapped_without_programmes:
            mapped_empty.setdefault(identity, {**base, "issue": "mapped_without_programmes"})

    sorter = lambda item: (item["country_code"], _name_key(item["channel"]))
    return (
        sorted(without_mapping.values(), key=sorter),
        sorted(mapped_empty.values(), key=sorter),
    )


def _summary_for_rows(rows: list[dict]) -> dict:
    counts = Counter(str(row.get("quality_category") or "") for row in rows)
    expected = [row for row in rows if row.get("epg_policy") == "expected"]
    expected_available = [
        row for row in expected
        if row.get("quality_category") in {QUALITY_EXACT, QUALITY_ALIAS, QUALITY_GUESSED}
    ]
    return {
        "stable_logical_channels": len(rows),
        "exact_tvg_id": counts[QUALITY_EXACT],
        "alias": counts[QUALITY_ALIAS],
        "guessed": counts[QUALITY_GUESSED],
        "missing": counts[QUALITY_MISSING],
        "epg_unavailable": counts[QUALITY_UNAVAILABLE],
        "epg_expected_channels": len(expected),
        "epg_expected_with_programmes": len(expected_available),
        "epg_completeness_percent": round(
            len(expected_available) / len(expected) * 100.0 if expected else 0.0,
            1,
        ),
        "trusted_mapping_channels": counts[QUALITY_EXACT] + counts[QUALITY_ALIAS],
    }


def build_epg_quality(
    report: dict,
    coverage: dict,
    *,
    health: dict | None = None,
    policy_payload: dict | None = None,
) -> dict:
    """Build a reusable EPG identity-quality report from generated build data."""
    health = health or {}
    policy_payload = policy_payload or {}
    default_policy, policy_indexes = compile_epg_policy(policy_payload)

    logical_channels = [
        dict(row)
        for row in (report.get("channels") or [])
        if isinstance(row, dict)
    ]
    stable_audit_rows = _stable_audit_rows(report)
    representatives = _representative_audit_rows(logical_channels, stable_audit_rows)

    matched_by_id: dict[str, dict] = {}
    for raw in coverage.get("matched") or []:
        if not isinstance(raw, dict):
            continue
        tvg_id = str(raw.get("tvg_id") or "").strip()
        if tvg_id:
            matched_by_id.setdefault(tvg_id.casefold(), raw)

    mapped_without_programmes = {
        str(item.get("tvg_id") or "").strip().casefold()
        for item in (health.get("mapped_without_programmes") or [])
        if isinstance(item, dict) and str(item.get("tvg_id") or "").strip()
    }
    mapped_ids = set(matched_by_id)

    rows: list[dict] = []
    for channel in logical_channels:
        key = _logical_key(channel)
        name = str(channel.get("name") or "Unnamed channel").strip()
        country = _country(channel.get("country_code"))
        tvg_id = str(channel.get("tvg_id") or "").strip()
        match = matched_by_id.get(tvg_id.casefold()) if tvg_id else None
        programmes = _match_has_programmes(match, mapped_without_programmes)
        category, mapping_quality = _quality_category(tvg_id, match, programmes)
        policy = _policy_for_channel(
            channel,
            representatives.get(key),
            default=default_policy,
            indexes=policy_indexes,
        )
        rows.append({
            "key": key,
            "channel": name,
            "country_code": country,
            "canonical_id": str(channel.get("canonical_id") or ""),
            "tvg_id": tvg_id,
            "quality_category": category,
            "mapping_quality": mapping_quality,
            "match_type": str((match or {}).get("match_type") or ""),
            "provider": str((match or {}).get("provider") or ""),
            "provider_xmltv_id": str((match or {}).get("provider_xmltv_id") or ""),
            "programme_available": programmes,
            "fresh_programmes": int((match or {}).get("fresh_programmes") or 0),
            "epg_policy": str(policy.get("status") or default_policy),
            "epg_policy_reason": str(policy.get("reason") or ""),
            "epg_policy_match": str(policy.get("matched_by") or "default"),
        })

    rows.sort(key=lambda item: (item["country_code"], _name_key(item["channel"])))
    countries: dict[str, dict] = {}
    for country in sorted({row["country_code"] for row in rows}):
        countries[country] = _summary_for_rows([
            row for row in rows if row["country_code"] == country
        ])

    verified_without_mapping, verified_mapped_empty = _verified_epg_gaps(
        stable_audit_rows,
        mapped_ids,
        mapped_without_programmes,
    )
    collisions = _collision_report(logical_channels)

    summary = _summary_for_rows(rows)
    summary.update({
        "tvg_id_collision_count": len(collisions),
        "verified_without_epg_mapping_count": len(verified_without_mapping),
        "verified_mapped_without_programmes_count": len(verified_mapped_empty),
    })

    return {
        "schema_version": 1,
        "metric": {
            "name": "EPG completeness",
            "definition": (
                "Stable logical channels whose EPG policy is expected and that have "
                "current/future programme data, divided by all stable logical channels "
                "whose EPG policy is expected. Missing tvg-id values are included in "
                "the denominator."
            ),
        },
        "summary": summary,
        "countries": countries,
        "channels": rows,
        "tvg_id_collisions": collisions,
        "verified_without_epg_mapping": verified_without_mapping,
        "verified_mapped_without_programmes": verified_mapped_empty,
    }


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_epg_quality_outputs(
    quality: dict,
    *,
    output_path: Path,
    collisions_csv_path: Path | None = None,
    verified_missing_csv_path: Path | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if collisions_csv_path is not None:
        collision_rows = []
        for collision in quality.get("tvg_id_collisions") or []:
            channels = collision.get("channels") or []
            collision_rows.append({
                "tvg_id": collision.get("tvg_id", ""),
                "logical_channel_count": collision.get("logical_channel_count", 0),
                "channels": " | ".join(str(item.get("channel") or "") for item in channels),
                "countries": " | ".join(str(item.get("country_code") or "") for item in channels),
                "logical_keys": " | ".join(str(item.get("key") or "") for item in channels),
            })
        _write_csv(
            collisions_csv_path,
            ["tvg_id", "logical_channel_count", "channels", "countries", "logical_keys"],
            collision_rows,
        )

    if verified_missing_csv_path is not None:
        _write_csv(
            verified_missing_csv_path,
            ["issue", "country_code", "channel", "tvg_id", "decision", "stream_url"],
            list(quality.get("verified_without_epg_mapping") or []),
        )


def load_json(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object in {path}.")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Classify tvg-id quality, EPG completeness and identity gaps."
    )
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--coverage", required=True, type=Path)
    parser.add_argument("--health", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--collisions-csv", type=Path)
    parser.add_argument("--verified-missing-csv", type=Path)
    args = parser.parse_args()

    quality = build_epg_quality(
        load_json(args.report),
        load_json(args.coverage),
        health=load_json(args.health),
        policy_payload=load_json(args.policy),
    )
    write_epg_quality_outputs(
        quality,
        output_path=args.output,
        collisions_csv_path=args.collisions_csv,
        verified_missing_csv_path=args.verified_missing_csv,
    )

    summary = quality["summary"]
    print(
        "EPG quality: "
        f"{summary['epg_expected_with_programmes']}/"
        f"{summary['epg_expected_channels']} expected logical channels complete "
        f"({summary['epg_completeness_percent']:.1f}%)."
    )
    print(
        "tvg-id trust: "
        f"{summary['exact_tvg_id']} exact, {summary['alias']} alias, "
        f"{summary['guessed']} guessed, {summary['missing']} missing, "
        f"{summary['epg_unavailable']} EPG unavailable."
    )
    print(
        f"Identity checks: {summary['tvg_id_collision_count']} tvg-id collisions, "
        f"{summary['verified_without_epg_mapping_count']} verified channels without mapping."
    )


if __name__ == "__main__":
    main()
