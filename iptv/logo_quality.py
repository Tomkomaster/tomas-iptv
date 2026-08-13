#!/usr/bin/env python3
"""Canonical channel-logo mappings and stable logical-channel coverage reports.

No image discovery or scraping happens here. Human-reviewed overrides are stored
in ``data/logo_overrides.json``; existing upstream ``tvg-logo`` values remain a
compatibility fallback until a canonical mapping is reviewed.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from country_language import normalize_country_code
from iptv.channel_identity import logical_channel_key


SCHEMA_VERSION = 1
QUALITY_CANONICAL = "Canonical"
QUALITY_SOURCE = "Source fallback"
QUALITY_MISSING = "Missing"
QUALITY_CATEGORIES = (QUALITY_CANONICAL, QUALITY_SOURCE, QUALITY_MISSING)


def _normalize_name(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _country(entry: dict) -> str:
    return (
        normalize_country_code(
            str(entry.get("country_code") or entry.get("language_code") or "")
        )
        or "UNKNOWN"
    )


def _channel_name(entry: dict) -> str:
    return str(
        entry.get("channel_name")
        or entry.get("tvg_name")
        or entry.get("display_name")
        or "Unnamed channel"
    ).strip()


def _normalize_match(match_type: str, match: dict) -> dict[str, str]:
    if match_type == "canonical_id":
        return {"canonical_id": str(match.get("canonical_id") or "").strip().casefold()}
    if match_type == "country_tvg_id":
        return {
            "country_code": str(match.get("country_code") or "").strip().upper(),
            "tvg_id": str(match.get("tvg_id") or "").strip().casefold(),
        }
    if match_type == "country_channel":
        return {
            "country_code": str(match.get("country_code") or "").strip().upper(),
            "channel": _normalize_name(match.get("channel")),
        }
    raise AssertionError(match_type)


class LogoRegistry:
    """Resolve one reviewed logo override for a logical channel."""

    _MATCH_SHAPES = {
        frozenset({"canonical_id"}): (300, "canonical_id"),
        frozenset({"country_code", "tvg_id"}): (200, "country_tvg_id"),
        frozenset({"country_code", "channel"}): (100, "country_channel"),
    }

    def __init__(self, payload: dict | None = None):
        payload = payload or {"schema_version": SCHEMA_VERSION, "entries": []}
        if not isinstance(payload, dict):
            raise RuntimeError("logo_overrides.json must contain a JSON object.")
        if payload.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported logo_overrides schema_version: {payload.get('schema_version')!r}"
            )
        raw_entries = payload.get("entries") or []
        if not isinstance(raw_entries, list):
            raise RuntimeError("logo_overrides entries must be a list.")

        self.entries: list[dict] = []
        seen: set[tuple] = set()
        for index, raw in enumerate(raw_entries, start=1):
            if not isinstance(raw, dict):
                raise RuntimeError(f"Logo override #{index} must be an object.")
            unknown = set(raw) - {"match", "logo", "source", "note"}
            if unknown:
                raise RuntimeError(
                    f"Logo override #{index} has unsupported fields: "
                    + ", ".join(sorted(unknown))
                )
            match = raw.get("match")
            if not isinstance(match, dict):
                raise RuntimeError(f"Logo override #{index} requires a match object.")
            shape_info = self._MATCH_SHAPES.get(frozenset(match))
            if not shape_info:
                raise RuntimeError(
                    f"Logo override #{index} has unsupported match fields. Allowed: "
                    "canonical_id; country_code+tvg_id; country_code+channel."
                )
            priority, match_type = shape_info
            normalized = _normalize_match(match_type, match)
            if not all(normalized.values()):
                raise RuntimeError(f"Logo override #{index} has an empty selector value.")

            logo = str(raw.get("logo") or "").strip()
            parsed = urlparse(logo)
            if parsed.scheme.casefold() != "https" or not parsed.netloc:
                raise RuntimeError(
                    f"Logo override #{index} must use an absolute HTTPS logo URL."
                )
            source = str(raw.get("source") or "").strip()
            if not source:
                raise RuntimeError(
                    f"Logo override #{index} requires source provenance; do not add unreviewed scraped logos."
                )

            selector_key = (match_type, tuple(sorted(normalized.items())))
            if selector_key in seen:
                raise RuntimeError(f"Duplicate logo override selector at entry #{index}.")
            seen.add(selector_key)
            self.entries.append({
                "match": normalized,
                "match_type": match_type,
                "priority": priority,
                "logo": logo,
                "source": source,
                "note": str(raw.get("note") or "").strip(),
                "index": index,
            })

    def resolve(self, entry: dict) -> dict | None:
        evidence = {
            "canonical_id": str(entry.get("canonical_id") or "").strip().casefold(),
            "country_code": _country(entry),
            "tvg_id": str(entry.get("tvg_id") or "").strip().casefold(),
            "channel": _normalize_name(_channel_name(entry)),
        }
        matches = [
            item for item in self.entries
            if all(evidence.get(key, "") == value for key, value in item["match"].items())
        ]
        if not matches:
            return None
        highest = max(item["priority"] for item in matches)
        winners = [item for item in matches if item["priority"] == highest]
        logos = {item["logo"] for item in winners}
        if len(logos) != 1:
            raise RuntimeError(
                f"Ambiguous logo overrides for {_channel_name(entry)!r}: equally strong mappings disagree."
            )
        return dict(winners[0])


def load_logo_registry(path: Path) -> LogoRegistry:
    if not path.is_file():
        raise RuntimeError(f"Configured logo override file not found: {path}")
    return LogoRegistry(json.loads(path.read_text(encoding="utf-8")))


def apply_channel_logos(entries: list[dict], registry: LogoRegistry) -> list[dict]:
    """Give every feed of one logical channel one consistent logo decision."""
    copied: list[dict] = []
    groups: dict[str, list[dict]] = defaultdict(list)
    for raw in entries:
        entry = dict(raw)
        entry["lines"] = list(raw.get("lines") or [])
        copied.append(entry)
        groups[logical_channel_key(entry)].append(entry)

    for key, group in groups.items():
        overrides = [registry.resolve(entry) for entry in group]
        overrides = [item for item in overrides if item is not None]
        if overrides:
            urls = {item["logo"] for item in overrides}
            if len(urls) != 1:
                raise RuntimeError(
                    f"Logical channel {key!r} resolves to conflicting canonical logo URLs."
                )
            chosen = max(overrides, key=lambda item: int(item["priority"]))
            for entry in group:
                entry["logo"] = chosen["logo"]
                entry["logo_quality"] = QUALITY_CANONICAL
                entry["logo_match_type"] = chosen["match_type"]
                entry["logo_provenance"] = chosen["source"]
                entry["logo_note"] = chosen["note"]
            continue

        source_candidates = sorted(
            (
                entry for entry in group
                if str(entry.get("logo") or "").strip()
            ),
            key=lambda entry: int(entry.get("_source_order") or 0),
        )
        if source_candidates:
            chosen_entry = source_candidates[0]
            chosen_logo = str(chosen_entry.get("logo") or "").strip()
            provenance = str(chosen_entry.get("source") or "upstream source").strip()
            for entry in group:
                entry["logo"] = chosen_logo
                entry["logo_quality"] = QUALITY_SOURCE
                entry["logo_match_type"] = "source_tvg_logo"
                entry["logo_provenance"] = provenance
                entry["logo_note"] = ""
        else:
            for entry in group:
                entry["logo"] = ""
                entry["logo_quality"] = QUALITY_MISSING
                entry["logo_match_type"] = ""
                entry["logo_provenance"] = ""
                entry["logo_note"] = ""
    return copied


def _summary(rows: list[dict]) -> dict:
    canonical = sum(1 for row in rows if row.get("quality_category") == QUALITY_CANONICAL)
    source = sum(1 for row in rows if row.get("quality_category") == QUALITY_SOURCE)
    missing = sum(1 for row in rows if row.get("quality_category") == QUALITY_MISSING)
    total = len(rows)
    available = canonical + source
    return {
        "stable_logical_channels": total,
        "with_logo": available,
        "canonical_logo": canonical,
        "source_fallback": source,
        "missing_logo": missing,
        "logo_availability_percent": round(100.0 * available / total if total else 0.0, 1),
        "canonical_logo_coverage_percent": round(100.0 * canonical / total if total else 0.0, 1),
    }


def build_logo_quality(
    published_entries: list[dict],
    *,
    generated_at: str = "",
    registry_path: str = "",
) -> dict:
    """Measure logo quality once per stable logical channel, not per feed URL."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for entry in published_entries:
        groups[logical_channel_key(entry)].append(entry)

    rows: list[dict] = []
    for key, group in groups.items():
        representative = group[0]
        qualities = {str(entry.get("logo_quality") or QUALITY_MISSING) for entry in group}
        if QUALITY_CANONICAL in qualities:
            quality = QUALITY_CANONICAL
        elif QUALITY_SOURCE in qualities:
            quality = QUALITY_SOURCE
        else:
            quality = QUALITY_MISSING
        logo = next((str(entry.get("logo") or "").strip() for entry in group if str(entry.get("logo") or "").strip()), "")
        rows.append({
            "key": key,
            "country_code": _country(representative),
            "channel": _channel_name(representative),
            "canonical_id": str(representative.get("canonical_id") or ""),
            "tvg_id": str(representative.get("tvg_id") or ""),
            "logo": logo,
            "quality_category": quality,
            "match_type": str(representative.get("logo_match_type") or ""),
            "provenance": str(representative.get("logo_provenance") or ""),
            "note": str(representative.get("logo_note") or ""),
            "feed_count": len(group),
        })
    rows.sort(key=lambda row: (row["country_code"], _normalize_name(row["channel"])))

    countries: dict[str, dict] = {}
    for country in sorted({row["country_code"] for row in rows}):
        countries[country] = _summary([row for row in rows if row["country_code"] == country])

    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "registry_path": registry_path,
        "metric": {
            "name": "Channel logo coverage",
            "definition": (
                "Stable logical channels with a logo URL divided by all stable logical channels. "
                "Canonical coverage counts only reviewed logo_overrides mappings."
            ),
        },
        "summary": _summary(rows),
        "countries": countries,
        "channels": rows,
        "missing_channels": [row for row in rows if row["quality_category"] == QUALITY_MISSING],
    }


def write_logo_quality_outputs(
    data: dict,
    *,
    output_path: Path,
    missing_csv_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with missing_csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["country_code", "channel", "tvg_id", "canonical_id", "key"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in data.get("missing_channels") or []:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
