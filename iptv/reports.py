#!/usr/bin/env python3
"""Build summary and CSV export helpers for Tomas IPTV.

These functions are intentionally free of build orchestration state. They turn
already-prepared entries/source metadata into country/language summaries and
write deterministic CSV exports.
"""
from __future__ import annotations

import csv
from pathlib import Path

from country_language import (
    normalize_country_code,
    normalize_language_codes as normalize_spoken_language_codes,
)

def summarize_country_stats(
    entries: list[dict],
    source_stats: list[dict],
) -> list[dict]:
    """Summarize final publication by country, independently of language."""
    country_codes: set[str] = set()
    for entry in entries:
        code = normalize_country_code(
            str(entry.get("country_code") or entry.get("language_code") or "")
        )
        if code:
            country_codes.add(code)
    for source in source_stats:
        code = normalize_country_code(
            str(source.get("country_code") or source.get("language_code") or "")
        )
        if code:
            country_codes.add(code)

    result: list[dict] = []
    for code in sorted(country_codes):
        country_entries = [
            entry for entry in entries
            if normalize_country_code(
                str(entry.get("country_code") or entry.get("language_code") or "")
            ) == code
        ]
        country_sources = [
            source for source in source_stats
            if normalize_country_code(
                str(source.get("country_code") or source.get("language_code") or "")
            ) == code
        ]
        unique_channel_keys = {
            entry.get("channel_key") for entry in country_entries if entry.get("channel_key")
        }
        base_channel_keys = {
            entry.get("channel_key") for entry in country_entries
            if entry.get("channel_key") and entry.get("classification") == "Base channel"
        }
        added_channel_keys = {
            entry.get("channel_key") for entry in country_entries
            if entry.get("channel_key") and entry.get("classification") == "Added channel"
        }
        result.append({
            "country_code": code,
            "source_count": len(country_sources),
            "base_source_count": sum(1 for source in country_sources if source.get("kind") == "base"),
            "unique_channels": len(unique_channel_keys),
            "stream_urls": len(country_entries),
            "base_channels": len(base_channel_keys),
            "added_channels": len(added_channel_keys),
            "alternative_streams": sum(
                1 for entry in country_entries
                if entry.get("classification") == "Alternative stream"
            ),
        })
    return result

def summarize_language_stats(
    entries: list[dict],
    source_stats: list[dict],
) -> list[dict]:
    """Summarize actual spoken-language metadata using ISO-639-3 codes."""
    language_codes: set[str] = set()
    for entry in entries:
        language_codes.update(normalize_spoken_language_codes(entry.get("language_codes")))
    for source in source_stats:
        language_codes.update(normalize_spoken_language_codes(source.get("language_codes")))

    result: list[dict] = []
    for code in sorted(language_codes):
        language_entries = [
            entry for entry in entries
            if code in normalize_spoken_language_codes(entry.get("language_codes"))
        ]
        language_sources = [
            source for source in source_stats
            if code in normalize_spoken_language_codes(source.get("language_codes"))
        ]
        unique_channel_keys = {
            entry.get("channel_key") for entry in language_entries if entry.get("channel_key")
        }
        base_channel_keys = {
            entry.get("channel_key") for entry in language_entries
            if entry.get("channel_key") and entry.get("classification") == "Base channel"
        }
        added_channel_keys = {
            entry.get("channel_key") for entry in language_entries
            if entry.get("channel_key") and entry.get("classification") == "Added channel"
        }
        result.append({
            "language_code": code,
            "source_count": len(language_sources),
            "base_source_count": sum(1 for source in language_sources if source.get("kind") == "base"),
            "unique_channels": len(unique_channel_keys),
            "stream_urls": len(language_entries),
            "base_channels": len(base_channel_keys),
            "added_channels": len(added_channel_keys),
            "alternative_streams": sum(
                1 for entry in language_entries
                if entry.get("classification") == "Alternative stream"
            ),
        })
    return result

def safe_csv_value(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ").strip()

def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: safe_csv_value(str(row.get(k, ""))) for k in fieldnames})
