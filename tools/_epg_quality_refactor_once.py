#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_exact(path: str, old: str, new: str, expected: int = 1) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"{path}: expected {expected} occurrence(s), found {count}\nMARKER:\n{old}"
        )
    target.write_text(text.replace(old, new), encoding="utf-8")


EPG_QUALITY = r'''#!/usr/bin/env python3
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
'''

TESTS = r'''import json
import tempfile
import unittest
from pathlib import Path

from epg.epg_policy import compile_epg_policy, resolve_epg_policy
from epg.epg_quality import (
    QUALITY_ALIAS,
    QUALITY_EXACT,
    QUALITY_GUESSED,
    QUALITY_MISSING,
    QUALITY_UNAVAILABLE,
    build_epg_quality,
    write_epg_quality_outputs,
)


ROOT = Path(__file__).resolve().parents[1]


class EpgQualityTests(unittest.TestCase):
    def sample_report(self):
        channels = [
            {"key": "HU:name:exact", "name": "Exact", "country_code": "HU", "tvg_id": "Exact.hu"},
            {"key": "HU:name:alias", "name": "Alias", "country_code": "HU", "tvg_id": "Alias.hu"},
            {"key": "HU:name:guess", "name": "Guess", "country_code": "HU", "tvg_id": "Guess.hu"},
            {"key": "HU:name:missing", "name": "Missing", "country_code": "HU", "tvg_id": ""},
            {"key": "HU:name:empty", "name": "Empty", "country_code": "HU", "tvg_id": "Empty.hu"},
            {"key": "HU:name:optional", "name": "Optional", "country_code": "HU", "tvg_id": ""},
        ]
        audit = []
        for channel in channels:
            audit.append({
                "channel": channel["name"],
                "country_code": "HU",
                "output_country_code": "HU",
                "tvg_id": channel["tvg_id"],
                "stream_url": f"https://example.test/{channel['name'].lower()}.m3u8",
                "decision": "Verified",
                "in_stable_playlist": True,
            })
        return {"channels": channels, "audit": {"channels": audit}}

    def test_five_quality_categories_and_completeness(self):
        coverage = {
            "matched": [
                {"tvg_id": "Exact.hu", "match_type": "external_exact_id", "fresh_programmes": 5},
                {"tvg_id": "Alias.hu", "match_type": "external_explicit_alias", "fresh_programmes": 5},
                {"tvg_id": "Guess.hu", "match_type": "external_unique_name", "fresh_programmes": 5},
                {"tvg_id": "Empty.hu", "match_type": "exact", "fresh_programmes": 0},
            ]
        }
        policy = {
            "default": "expected",
            "entries": [{"channel": "Optional", "status": "optional", "reason": "test"}],
        }
        quality = build_epg_quality(
            self.sample_report(), coverage,
            health={"mapped_without_programmes": [{"tvg_id": "Empty.hu", "provider": "test"}]},
            policy_payload=policy,
        )
        by_name = {row["channel"]: row for row in quality["channels"]}
        self.assertEqual(by_name["Exact"]["quality_category"], QUALITY_EXACT)
        self.assertEqual(by_name["Alias"]["quality_category"], QUALITY_ALIAS)
        self.assertEqual(by_name["Guess"]["quality_category"], QUALITY_GUESSED)
        self.assertEqual(by_name["Missing"]["quality_category"], QUALITY_MISSING)
        self.assertEqual(by_name["Empty"]["quality_category"], QUALITY_UNAVAILABLE)
        self.assertEqual(by_name["Optional"]["quality_category"], QUALITY_MISSING)

        summary = quality["summary"]
        self.assertEqual(summary["exact_tvg_id"], 1)
        self.assertEqual(summary["alias"], 1)
        self.assertEqual(summary["guessed"], 1)
        self.assertEqual(summary["missing"], 2)
        self.assertEqual(summary["epg_unavailable"], 1)
        self.assertEqual(summary["epg_expected_channels"], 5)
        self.assertEqual(summary["epg_expected_with_programmes"], 3)
        self.assertEqual(summary["epg_completeness_percent"], 60.0)

    def test_unexpected_tvg_id_collision_uses_logical_channels(self):
        report = {
            "channels": [
                {"key": "HU:name:one", "name": "One", "country_code": "HU", "tvg_id": "Shared.hu"},
                {"key": "HU:name:two", "name": "Two", "country_code": "HU", "tvg_id": "Shared.hu"},
                {"key": "HU:name:other", "name": "Other", "country_code": "HU", "tvg_id": "Other.hu"},
            ],
            "audit": {"channels": []},
        }
        quality = build_epg_quality(report, {"matched": []}, policy_payload={"default": "expected"})
        self.assertEqual(quality["summary"]["tvg_id_collision_count"], 1)
        collision = quality["tvg_id_collisions"][0]
        self.assertEqual(collision["tvg_id"], "Shared.hu")
        self.assertEqual(collision["logical_channel_count"], 2)
        self.assertEqual({row["channel"] for row in collision["channels"]}, {"One", "Two"})

    def test_verified_without_mapping_and_mapped_empty_are_separate(self):
        report = {
            "channels": [
                {"key": "HU:name:mapped", "name": "Mapped", "country_code": "HU", "tvg_id": "Mapped.hu"},
                {"key": "HU:name:unmapped", "name": "Unmapped", "country_code": "HU", "tvg_id": "Unmapped.hu"},
                {"key": "HU:name:no-id", "name": "No ID", "country_code": "HU", "tvg_id": ""},
                {"key": "HU:name:empty", "name": "Empty", "country_code": "HU", "tvg_id": "Empty.hu"},
            ],
            "audit": {"channels": [
                {"channel": "Mapped", "country_code": "HU", "tvg_id": "Mapped.hu", "decision": "Verified", "in_stable_playlist": True},
                {"channel": "Unmapped", "country_code": "HU", "tvg_id": "Unmapped.hu", "decision": "TV verified", "in_stable_playlist": True},
                {"channel": "No ID", "country_code": "HU", "tvg_id": "", "decision": "Verified", "in_stable_playlist": True},
                {"channel": "Empty", "country_code": "HU", "tvg_id": "Empty.hu", "decision": "Verified", "in_stable_playlist": True},
                {"channel": "Review", "country_code": "HU", "tvg_id": "Review.hu", "decision": "Needs review", "in_stable_playlist": True},
            ]},
        }
        coverage = {"matched": [
            {"tvg_id": "Mapped.hu", "match_type": "exact", "fresh_programmes": 2},
            {"tvg_id": "Empty.hu", "match_type": "exact", "fresh_programmes": 0},
        ]}
        health = {"mapped_without_programmes": [{"tvg_id": "Empty.hu", "provider": "test"}]}
        quality = build_epg_quality(report, coverage, health=health, policy_payload={"default": "expected"})
        gaps = quality["verified_without_epg_mapping"]
        self.assertEqual({row["channel"] for row in gaps}, {"Unmapped", "No ID"})
        self.assertEqual(
            {row["issue"] for row in gaps},
            {"no_epg_mapping", "missing_tvg_id"},
        )
        self.assertEqual(
            [row["channel"] for row in quality["verified_mapped_without_programmes"]],
            ["Empty"],
        )

    def test_modern_country_field_selects_country_policy_default(self):
        default, indexes = compile_epg_policy({
            "default": "expected",
            "country_defaults": {"CZ": "optional"},
        })
        resolved = resolve_epg_policy(
            {"channel": "Example", "output_country_code": "CZ"},
            default=default,
            indexes=indexes,
        )
        self.assertEqual(resolved["status"], "optional")
        self.assertEqual(resolved["matched_by"], "country_default")

    def test_csv_reports_are_written(self):
        report = {
            "channels": [
                {"key": "HU:name:one", "name": "One", "country_code": "HU", "tvg_id": "Shared.hu"},
                {"key": "HU:name:two", "name": "Two", "country_code": "HU", "tvg_id": "Shared.hu"},
            ],
            "audit": {"channels": [
                {"channel": "One", "country_code": "HU", "tvg_id": "Shared.hu", "decision": "Verified", "in_stable_playlist": True},
            ]},
        }
        quality = build_epg_quality(report, {"matched": []}, policy_payload={"default": "expected"})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_epg_quality_outputs(
                quality,
                output_path=root / "quality.json",
                collisions_csv_path=root / "collisions.csv",
                verified_missing_csv_path=root / "verified.csv",
            )
            self.assertEqual(json.loads((root / "quality.json").read_text(encoding="utf-8"))["schema_version"], 1)
            self.assertIn("Shared.hu", (root / "collisions.csv").read_text(encoding="utf-8-sig"))
            self.assertIn("One", (root / "verified.csv").read_text(encoding="utf-8-sig"))

    def test_dashboard_exposes_quality_categories_and_reports(self):
        template = (ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "dashboard.js").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "build-and-publish.yml").read_text(encoding="utf-8")
        for label in (
            "Exact tvg-id", "Alias", "Guessed", "Missing", "EPG unavailable",
        ):
            self.assertIn(label, template + script)
        self.assertIn("epg-quality.json", script)
        self.assertIn("tvg-id collisions", template.casefold())
        self.assertIn("Verified channels without EPG mapping", template)
        self.assertIn("python3 -m epg.epg_quality", workflow)


if __name__ == "__main__":
    unittest.main()
'''

DOC = r'''# EPG identity quality

The generated `public/epg-quality.json` measures programme-guide quality at the
**stable logical-channel** level. Alternative feeds of the same station do not
inflate the denominator.

## Dashboard categories

Each stable logical channel appears in exactly one category:

- **Exact tvg-id** — an exact playlist/provider ID match with current/future programmes;
- **Alias** — an explicit hand-maintained alias (including intentional cross-country aliases) with programmes;
- **Guessed** — a deterministic quality-variant or unique-name inference with programmes;
- **Missing** — the stable logical channel has no `tvg-id`;
- **EPG unavailable** — it has a `tvg-id`, but no final mapping or the mapped provider currently has no programmes.

The underlying row also keeps `match_type`, provider, provider XMLTV ID and the
coarser `mapping_quality` (`exact`, `alias`, `guessed`, `unmapped`, `missing`).
This lets future quality logic get stricter without changing the user-facing
five-state dashboard.

## EPG completeness metric

`epg_completeness_percent` deliberately uses **all stable logical channels whose
EPG policy is `expected`** as its denominator. A missing `tvg-id` therefore
counts as incomplete instead of disappearing from the metric. Channels marked
`optional` or `not_expected` in `data/epg_policy.json` do not lower this score.

This is intended to become the next major quality metric after high-priority
stream coverage is largely solved.

## Identity reports

The quality report also exposes:

- `tvg_id_collisions`: two or more distinct logical channels sharing the same
  exact `tvg-id`; multiple feeds of one logical channel do not count;
- `verified_without_epg_mapping`: stable `Verified` / `TV verified` channels
  with no `tvg-id` or with a `tvg-id` that has no final EPG mapping;
- `verified_mapped_without_programmes`: verified channels whose mapping exists
  but currently produces no programme data.

For quick review, the build also publishes:

- `public/tvg-id-collisions.csv`
- `public/verified-without-epg.csv`

All of these files are generated telemetry/reporting output and are not written
back into the manual `audit.json`.
'''

(ROOT / "epg" / "epg_quality.py").write_text(EPG_QUALITY, encoding="utf-8")
(ROOT / "tests" / "test_epg_quality.py").write_text(TESTS, encoding="utf-8")
(ROOT / "docs" / "epg-quality.md").write_text(DOC, encoding="utf-8")

# Modern geography must be authoritative when resolving country defaults.
replace_exact(
    "epg/epg_policy.py",
    '''    country_code = str(\n        row.get("output_language_code")\n        or row.get("language_code")\n        or row.get("playlist_language_code")\n        or ""\n    ).strip().upper()\n''',
    '''    country_code = str(\n        row.get("output_country_code")\n        or row.get("playlist_country_code")\n        or row.get("country_code")\n        or row.get("output_language_code")\n        or row.get("language_code")\n        or row.get("playlist_language_code")\n        or ""\n    ).strip().upper()\n''',
)

# Publish generated quality/report links beside the existing guide links.
replace_exact(
    "iptv/dashboard.py",
    '''        epg_link_html = (\n            '<a href="guide.xml">'\n            'EPG programme guide (guide.xml)'\n            '</a>'\n            ' · '\n            '<a href="epg-coverage.json">'\n            'EPG coverage report'\n            '</a>'\n        )\n''',
    '''        epg_link_html = (\n            '<a href="guide.xml">'\n            'EPG programme guide (guide.xml)'\n            '</a>'\n            ' · '\n            '<a href="epg-coverage.json">'\n            'EPG coverage report'\n            '</a>'\n            ' · '\n            '<a href="epg-quality.json">'\n            'EPG identity quality (JSON)'\n            '</a>'\n            ' · '\n            '<a href="tvg-id-collisions.csv">'\n            'tvg-id collisions (CSV)'\n            '</a>'\n            ' · '\n            '<a href="verified-without-epg.csv">'\n            'Verified without EPG (CSV)'\n            '</a>'\n        )\n''',
)

# Replace the small country-only EPG block with the full identity-quality panel.
old_epg_html = '''  <h2>EPG coverage by country</h2>\n  <p class="muted">\n    Programme-guide coverage is shown separately for HU, SK and CZ so growth in\n    one country does not hide gaps in another. Percentages use stable channels\n    that currently have a tvg-id. Missing tvg-id values remain visible in Needs attention.\n  </p>\n  <div id="epgCountrySummary" class="audit-summary">\n    <div class="card"><div class="value">…</div><div class="label">Loading EPG coverage</div></div>\n  </div>\n\n'''
new_epg_html = '''  <h2>EPG identity quality & completeness</h2>\n  <p class="muted">\n    EPG quality is measured per stable logical channel, not per stream URL. Exact IDs\n    and explicit aliases are higher-confidence identities; deterministic variant/name\n    inference is shown as Guessed. Missing IDs and mapped-but-empty/unmapped guide\n    entries stay visible instead of disappearing from the denominator. The main EPG\n    completeness percentage counts expected logical channels with current/future\n    programme data, including missing tvg-id values as incomplete.\n  </p>\n  <div id="epgQualitySummary" class="audit-summary">\n    <div class="card"><div class="value">…</div><div class="label">Loading EPG identity quality</div></div>\n  </div>\n\n  <h3>EPG completeness by country</h3>\n  <div id="epgCountrySummary" class="audit-summary">\n    <div class="card"><div class="value">…</div><div class="label">Loading country EPG quality</div></div>\n  </div>\n\n  <div class="controls">\n    <input id="epgQualitySearch" type="search" placeholder="Search EPG identity quality...">\n    <select id="epgQualityFilter">\n      <option value="">All EPG identity states</option>\n      <option value="Exact tvg-id">Exact tvg-id</option>\n      <option value="Alias">Alias</option>\n      <option value="Guessed">Guessed</option>\n      <option value="Missing">Missing</option>\n      <option value="EPG unavailable">EPG unavailable</option>\n    </select>\n  </div>\n  <p id="epgQualityVisibleCount" class="muted">Loading epg-quality.json…</p>\n  <div class="table-wrap">\n    <table id="epgQualityTable">\n      <thead><tr><th>Country</th><th>Channel</th><th>tvg-id</th><th>Quality</th><th>Match</th><th>Provider</th><th>EPG policy</th><th>Programmes</th></tr></thead>\n      <tbody><tr><td colspan="8" class="muted">Loading EPG identity quality…</td></tr></tbody>\n    </table>\n  </div>\n\n  <h3>Unexpected tvg-id collisions</h3>\n  <p class="muted">\n    These are distinct logical channels sharing the same exact tvg-id. Multiple feeds\n    of one logical channel are intentionally collapsed and do not create a warning.\n  </p>\n  <div class="table-wrap">\n    <table id="epgCollisionTable">\n      <thead><tr><th>tvg-id</th><th>Logical channels</th><th>Countries</th><th>Channel identities</th></tr></thead>\n      <tbody><tr><td colspan="4" class="muted">Loading tvg-id collisions…</td></tr></tbody>\n    </table>\n  </div>\n\n  <h3>Verified channels without EPG mapping</h3>\n  <p class="muted">\n    Stable channels already verified for TV playback but lacking an EPG identity path.\n    Missing tvg-id and present-but-unmapped tvg-id cases are separated in the report.\n  </p>\n  <div class="table-wrap">\n    <table id="epgVerifiedMissingTable">\n      <thead><tr><th>Country</th><th>Channel</th><th>tvg-id</th><th>Issue</th><th>Manual status</th><th>URL</th></tr></thead>\n      <tbody><tr><td colspan="6" class="muted">Loading verified EPG gaps…</td></tr></tbody>\n    </table>\n  </div>\n\n'''
replace_exact("templates/dashboard.html", old_epg_html, new_epg_html)

# Country filtering should refresh all dynamic EPG-quality surfaces.
replace_exact(
    "static/dashboard.js",
    "  renderEpgCountryCoverage(epgData);\n",
    "  renderEpgQuality();\n  applyEpgQualityFilters();\n",
)

old_epg_js = '''const epgCountrySummary = document.getElementById('epgCountrySummary');\nlet epgData = null;\n\nfunction renderEpgCountryCoverage(data) {\n  if (!epgCountrySummary) return;\n  const countries = data?.countries || {};\n  const codes = SUPPORTED_COUNTRIES\n    .filter(code => countries[code])\n    .filter(countryMatches);\n  if (!codes.length) {\n    epgCountrySummary.innerHTML = '<div class="card"><div class="value">—</div><div class="label">Country EPG data unavailable</div></div>';\n    return;\n  }\n  epgCountrySummary.innerHTML = codes.map(code => {\n    const info = countries[code] || {};\n    const total = Number(info.playlist_tvg_ids || 0);\n    const mapped = Number(info.mapped_tvg_ids || 0);\n    const populated = Number(info.channels_with_programmes || 0);\n    const actual = Number(info.actual_programme_coverage_percent || 0).toFixed(1);\n    const mappedPct = Number(info.mapping_coverage_percent || 0).toFixed(1);\n    return `\n      <div class="card" data-country="${esc(code)}">\n        <div class="value">${actual}%</div>\n        <div class="label">${code} programmes (${populated}/${total})</div>\n        <div class="detail">Mapped: ${mapped}/${total} (${mappedPct}%)</div>\n      </div>`;\n  }).join('');\n}\n\nfetch('epg-health.json', { cache: 'no-store' })\n  .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })\n  .then(data => { epgData = data; renderEpgCountryCoverage(data); })\n  .catch(error => {\n    if (epgCountrySummary) epgCountrySummary.innerHTML = `<div class="card"><div class="value">—</div><div class="label">EPG coverage unavailable: ${esc(error.message)}</div></div>`;\n  });\n\n'''
new_epg_js = r'''const epgQualitySummary = document.getElementById('epgQualitySummary');
const epgCountrySummary = document.getElementById('epgCountrySummary');
const epgQualitySearch = document.getElementById('epgQualitySearch');
const epgQualityFilter = document.getElementById('epgQualityFilter');
const epgQualityVisibleCount = document.getElementById('epgQualityVisibleCount');
const epgQualityTableBody = document.querySelector('#epgQualityTable tbody');
const epgCollisionTableBody = document.querySelector('#epgCollisionTable tbody');
const epgVerifiedMissingTableBody = document.querySelector('#epgVerifiedMissingTable tbody');
let epgQualityData = null;
let epgQualityRows = [];

function epgQualityBadgeClass(category) {
  if (category === 'Exact tvg-id') return 'verified';
  if (category === 'Alias') return 'tv';
  if (category === 'Guessed' || category === 'EPG unavailable') return 'review';
  if (category === 'Missing') return 'rejected';
  return 'base';
}

function selectedEpgChannels() {
  const channels = Array.isArray(epgQualityData?.channels) ? epgQualityData.channels : [];
  return channels.filter(row => countryMatches(row.country_code));
}

function epgSummaryForRows(rows) {
  const count = category => rows.filter(row => row.quality_category === category).length;
  const expected = rows.filter(row => row.epg_policy === 'expected');
  const complete = expected.filter(row => ['Exact tvg-id', 'Alias', 'Guessed'].includes(row.quality_category));
  return {
    total: rows.length,
    exact: count('Exact tvg-id'),
    alias: count('Alias'),
    guessed: count('Guessed'),
    missing: count('Missing'),
    unavailable: count('EPG unavailable'),
    expected: expected.length,
    complete: complete.length,
    completeness: expected.length ? (100 * complete.length / expected.length) : 0,
  };
}

function renderEpgQuality() {
  if (!epgQualityData) return;
  const rows = selectedEpgChannels();
  const summary = epgSummaryForRows(rows);
  if (epgQualitySummary) {
    epgQualitySummary.innerHTML = `
      <div class="card"><div class="value">${summary.completeness.toFixed(1)}%</div><div class="label">EPG completeness (${summary.complete}/${summary.expected} expected)</div></div>
      <div class="card"><div class="value">${summary.exact}</div><div class="label">Exact tvg-id</div></div>
      <div class="card"><div class="value">${summary.alias}</div><div class="label">Alias</div></div>
      <div class="card"><div class="value">${summary.guessed}</div><div class="label">Guessed</div></div>
      <div class="card"><div class="value">${summary.missing}</div><div class="label">Missing</div></div>
      <div class="card"><div class="value">${summary.unavailable}</div><div class="label">EPG unavailable</div></div>`;
  }

  if (epgCountrySummary) {
    const countries = epgQualityData.countries || {};
    const codes = SUPPORTED_COUNTRIES.filter(code => countries[code]).filter(countryMatches);
    epgCountrySummary.innerHTML = codes.length ? codes.map(code => {
      const info = countries[code] || {};
      return `<div class="card" data-country="${esc(code)}">
        <div class="value">${Number(info.epg_completeness_percent || 0).toFixed(1)}%</div>
        <div class="label">${esc(code)} EPG completeness (${Number(info.epg_expected_with_programmes || 0)}/${Number(info.epg_expected_channels || 0)})</div>
        <div class="detail">Exact ${Number(info.exact_tvg_id || 0)} · Alias ${Number(info.alias || 0)} · Guessed ${Number(info.guessed || 0)} · Missing ${Number(info.missing || 0)} · Unavailable ${Number(info.epg_unavailable || 0)}</div>
      </div>`;
    }).join('') : '<div class="card"><div class="value">—</div><div class="label">Country EPG quality unavailable</div></div>';
  }

  if (epgCollisionTableBody) {
    const collisions = (epgQualityData.tvg_id_collisions || []).filter(item => {
      const channels = Array.isArray(item.channels) ? item.channels : [];
      return selectedCountry === 'ALL' || channels.some(channel => countryMatches(channel.country_code));
    });
    epgCollisionTableBody.innerHTML = collisions.length ? collisions.map(item => {
      const channels = Array.isArray(item.channels) ? item.channels : [];
      return `<tr>
        <td>${esc(item.tvg_id || '—')}</td>
        <td><span class="badge rejected">${Number(item.logical_channel_count || channels.length)} channels</span></td>
        <td>${esc([...new Set(channels.map(row => row.country_code).filter(Boolean))].join(', ') || '—')}</td>
        <td>${channels.map(row => `<div><strong>${esc(row.channel || 'Unnamed')}</strong><div class="detail">${esc(row.key || '')}</div></div>`).join('')}</td>
      </tr>`;
    }).join('') : '<tr><td colspan="4"><span class="badge verified">Clear</span> No unexpected tvg-id collisions.</td></tr>';
  }

  if (epgVerifiedMissingTableBody) {
    const gaps = (epgQualityData.verified_without_epg_mapping || []).filter(row => countryMatches(row.country_code));
    epgVerifiedMissingTableBody.innerHTML = gaps.length ? gaps.map(row => {
      const issue = row.issue === 'missing_tvg_id' ? 'Missing tvg-id' : 'No EPG mapping';
      const link = row.stream_url ? `<a href="${esc(row.stream_url)}" target="_blank" rel="noopener">stream</a>` : '—';
      return `<tr data-country="${esc(row.country_code || 'UNKNOWN')}">
        <td>${esc(row.country_code || 'UNKNOWN')}</td><td class="channel">${esc(row.channel || 'Unnamed')}</td>
        <td>${esc(row.tvg_id || '—')}</td><td><span class="badge rejected">${esc(issue)}</span></td>
        <td><span class="badge ${manualBadgeClass(row.decision)}">${esc(row.decision || 'Unknown')}</span></td><td>${link}</td>
      </tr>`;
    }).join('') : '<tr><td colspan="6"><span class="badge verified">Clear</span> Every verified stable channel has an EPG mapping identity.</td></tr>';
  }
}

function applyEpgQualityFilters() {
  if (!epgQualitySearch || !epgQualityFilter) return;
  const query = epgQualitySearch.value.trim().toLowerCase();
  const category = epgQualityFilter.value;
  let shown = 0;
  for (const row of epgQualityRows) {
    const matchesText = !query || row.innerText.toLowerCase().includes(query);
    const matchesCategory = !category || row.dataset.epgQuality === category;
    const show = countryMatches(row.dataset.country) && matchesText && matchesCategory;
    row.style.display = show ? '' : 'none';
    if (show) shown++;
  }
  if (epgQualityVisibleCount) {
    epgQualityVisibleCount.textContent = `Showing ${shown} of ${epgQualityRows.length} stable logical channels`;
  }
}

function renderEpgQualityTable() {
  if (!epgQualityTableBody || !epgQualityData) return;
  const channels = Array.isArray(epgQualityData.channels) ? epgQualityData.channels : [];
  epgQualityTableBody.innerHTML = channels.length ? channels.map(row => `
    <tr data-country="${esc(row.country_code || 'UNKNOWN')}" data-epg-quality="${esc(row.quality_category || '')}">
      <td>${esc(row.country_code || 'UNKNOWN')}</td><td class="channel">${esc(row.channel || 'Unnamed')}</td>
      <td>${esc(row.tvg_id || '—')}</td><td><span class="badge ${epgQualityBadgeClass(row.quality_category)}">${esc(row.quality_category || 'Unknown')}</span></td>
      <td>${esc(row.match_type || '—')}<div class="detail">${esc(row.provider_xmltv_id || '')}</div></td>
      <td>${esc(row.provider || '—')}</td><td>${esc(row.epg_policy || 'expected')}<div class="detail">${esc(row.epg_policy_reason || '')}</div></td>
      <td>${row.programme_available ? '<span class="badge verified">Available</span>' : '<span class="badge review">Unavailable</span>'}</td>
    </tr>`).join('') : '<tr><td colspan="8">No stable logical channels were reported.</td></tr>';
  epgQualityRows = Array.from(document.querySelectorAll('#epgQualityTable tbody tr[data-epg-quality]'));
  applyEpgQualityFilters();
}

fetch('epg-quality.json', { cache: 'no-store' })
  .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
  .then(data => {
    epgQualityData = data;
    renderEpgQuality();
    renderEpgQualityTable();
  })
  .catch(error => {
    if (epgQualitySummary) epgQualitySummary.innerHTML = `<div class="card"><div class="value">—</div><div class="label">EPG quality unavailable: ${esc(error.message)}</div></div>`;
    if (epgCountrySummary) epgCountrySummary.innerHTML = '<div class="card"><div class="value">—</div><div class="label">Country EPG quality unavailable</div></div>';
    if (epgQualityTableBody) epgQualityTableBody.innerHTML = `<tr><td colspan="8">epg-quality.json could not be loaded: ${esc(error.message)}</td></tr>`;
  });
if (epgQualitySearch) epgQualitySearch.addEventListener('input', applyEpgQualityFilters);
if (epgQualityFilter) epgQualityFilter.addEventListener('change', applyEpgQualityFilters);

'''
replace_exact("static/dashboard.js", old_epg_js, new_epg_js)

# Generate the new report after final EPG health is known and before attention.
workflow_marker = '''          python3 -m epg.epg_health \\\n            --coverage public/epg-coverage.json \\\n            --guide public/guide.xml \\\n            --grab-log .epg-grab.log \\\n            --output public/epg-health.json\n\n      - name: Build needs attention queue\n'''
workflow_replacement = '''          python3 -m epg.epg_health \\\n            --coverage public/epg-coverage.json \\\n            --guide public/guide.xml \\\n            --grab-log .epg-grab.log \\\n            --output public/epg-health.json\n\n      - name: Analyze EPG identity quality\n        shell: bash\n        run: |\n          set -euo pipefail\n\n          EPG_ENABLED="$(\n            python3 -c '\n          import json\n          from pathlib import Path\n          cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))\n          print("true" if (cfg.get("epg") or {}).get("enabled") else "false")\n          '\n          )"\n\n          if [ "$EPG_ENABLED" != "true" ]; then\n            echo "EPG disabled; identity-quality analysis skipped."\n            exit 0\n          fi\n\n          python3 -m epg.epg_quality \\\n            --report public/report.json \\\n            --coverage public/epg-coverage.json \\\n            --health public/epg-health.json \\\n            --policy data/epg_policy.json \\\n            --output public/epg-quality.json \\\n            --collisions-csv public/tvg-id-collisions.csv \\\n            --verified-missing-csv public/verified-without-epg.csv\n\n      - name: Build needs attention queue\n'''
replace_exact(".github/workflows/build-and-publish.yml", workflow_marker, workflow_replacement)

print("EPG quality implementation written.")
