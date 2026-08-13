#!/usr/bin/env python3
"""Build summary and CSV export helpers for Tomas IPTV.

These functions are intentionally free of build orchestration state. They turn
already-prepared entries/source metadata into country/language summaries and
write deterministic CSV exports.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from iptv.channel_identity import (
    canonical_stream_url,
    logical_channel_key,
    normalize_text,
)
from iptv.playback_status import is_tested_status
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

def build_report_context(
    published_entries: list[dict],
    test_entries: list[dict],
    audit_rows: list[dict],
    source_stats: list[dict],
    previous_report: dict | None,
) -> tuple[list[dict], list[dict], list[dict], dict]:
    """Prepare mutable audit membership, channel inventory summaries and change diff."""
    stable_urls = {
        canonical_stream_url(
            str(
                entry.get("url")
                or ""
            )
        )
        for entry in published_entries
        if entry.get("url")
    }

    test_urls = {
        canonical_stream_url(
            str(
                entry.get("url")
                or ""
            )
        )
        for entry in test_entries
        if entry.get("url")
    }

    for row in audit_rows:
        row_url = str(
            row.get(
                "stream_url"
            )
            or ""
        ).strip()

        if not row_url:
            row[
                "in_playlist"
            ] = False

            row[
                "in_stable_playlist"
            ] = False

            continue

        row_url_key = (
            canonical_stream_url(
                row_url
            )
        )

        # prepare_audit_rows deliberately marks historical-only rows false.
        # Preserve that authority even when a different current identity uses
        # the same URL.
        if row.get("in_playlist") is False:
            row["in_stable_playlist"] = False
            continue

        # "in_playlist" now means the stream is a current candidate
        # and is therefore present in test.m3u.
        row[
            "in_playlist"
        ] = (
            row_url_key
            in test_urls
        )

        row[
            "in_stable_playlist"
        ] = (
            row_url_key
            in stable_urls
        )

    by_channel: dict[str, dict] = {}
    for entry in published_entries:
        key = logical_channel_key(entry)
        record = by_channel.setdefault(key, {
            "key": key,
            "raw_key": entry.get("channel_key", ""),
            "country_code": entry.get("country_code", entry.get("language_code", "")),
            "language_codes": list(entry.get("language_codes") or []),
            "language_code": entry.get("country_code", entry.get("language_code", "")),
            "name": entry["channel_name"],
            "canonical_id": entry.get("canonical_id", ""),
            "tvg_id": entry.get("tvg_id", ""),
            "logo": entry.get("logo", ""),
            "logo_quality": entry.get("logo_quality", ""),
            "logo_match_type": entry.get("logo_match_type", ""),
            "logo_provenance": entry.get("logo_provenance", ""),
            "feed_quality_score": int(
                entry.get("_feed_quality_score") or 0
            ),
            "feed_quality_summary": str(
                entry.get("_feed_quality_summary") or ""
            ),
            "sources": [],
            "stream_count": 0,
        })
        if entry["source"] not in record["sources"]:
            record["sources"].append(entry["source"])
        record["stream_count"] += 1

    unique_channels = sorted(
        by_channel.values(),
        key=lambda x: normalize_text(x["name"])
    )

    country_stats = summarize_country_stats(published_entries, source_stats)
    language_stats = summarize_language_stats(published_entries, source_stats)

    changes = {
        "previous_generated_at": None,
        "added_channels": [],
        "removed_channels": [],
    }

    if previous_report:
        previous_channels = [
            ch
            for ch in previous_report.get("channels", [])
            if ch.get("key")
        ]

        previous_by_key = {
            str(ch.get("key")): str(ch.get("name") or ch.get("key"))
            for ch in previous_channels
        }

        current_by_key = {
            ch["key"]: ch["name"]
            for ch in unique_channels
        }

        # The first build after this migration compares against a report whose
        # keys were not language-scoped. Compare raw legacy keys once so the
        # dashboard does not report every channel as removed and re-added.
        previous_has_scoped_keys = any(
            re.fullmatch(
                r"[A-Z]{2,3}:(?:canonical|id|name):.+",
                key,
            )
            for key in previous_by_key
        )

        if previous_by_key and not previous_has_scoped_keys:
            current_by_key = {
                str(ch.get("raw_key") or ch["key"]): ch["name"]
                for ch in unique_channels
            }

        added_keys = sorted(
            set(current_by_key) - set(previous_by_key),
            key=lambda k: normalize_text(current_by_key[k]),
        )
        removed_keys = sorted(
            set(previous_by_key) - set(current_by_key),
            key=lambda k: normalize_text(previous_by_key[k]),
        )

        changes = {
            "previous_generated_at": previous_report.get("generated_at"),
            "added_channels": [current_by_key[k] for k in added_keys],
            "removed_channels": [previous_by_key[k] for k in removed_keys],
        }


    return unique_channels, country_stats, language_stats, changes

def write_build_csv_exports(
    public_dir: Path,
    published_entries: list[dict],
    duplicate_rows: list[dict],
    excluded_rows: list[dict],
    audit_rows: list[dict],
) -> None:
    """Write the generated channel, duplicate, exclusion and audit CSV exports."""
    inventory_rows = [
        {
            "playlist_name": e.get("published_name", e["channel_name"]),
            "channel_name": e["channel_name"],
            "feed_label": (
                f"Feed {int(e.get('visible_feed_index') or 1)}/{int(e.get('visible_feed_count') or 1)}"
                if int(e.get("visible_feed_count") or 1) > 1 else "Single"
            ),
            "feed_index": int(e.get("visible_feed_index") or 1),
            "feed_count": int(e.get("visible_feed_count") or 1),
            "tvg_id": e.get(
                "tvg_id",
                "",
            ),
            "canonical_id": e.get("canonical_id", ""),
            "identity_match_type": e.get("identity_match_type", ""),

            "country_code": e.get("country_code", e.get("language_code", "")),
            "language_codes": ", ".join(e.get("language_codes") or []),
            "country_name": e.get(
                "country_name",
                "",
            ),

            "content_group": e.get(
                "content_group",
                "",
            ),

            "source_group_title": e.get(
                "source_group_title",
                "",
            ),

            "group_title": e.get(
                "group_title",
                "",
            ),

            "test_status": e.get(
                "test_status",
                "Needs review",
            ),
            "feed_quality_score": int(
                e.get("_feed_quality_score") or 0
            ),
            "feed_quality_summary": str(
                e.get("_feed_quality_summary") or ""
            ),
            "source_flags": ", ".join(e.get("source_flags") or []),
            "source": e["source"],
            "classification": e["classification"],
            "stream_url": e["url"],
            "logo": e.get("logo", ""),
            "logo_quality": e.get("logo_quality", ""),
            "logo_match_type": e.get("logo_match_type", ""),
            "logo_provenance": e.get("logo_provenance", ""),
        }
        for e in published_entries
    ]
    write_csv(
        public_dir / "channels.csv",
        [
            "playlist_name",
            "channel_name",
            "feed_label",
            "feed_index",
            "feed_count",
            "tvg_id",
            "canonical_id",
            "identity_match_type",

            "country_code",
            "language_codes",
            "country_name",
            "content_group",
            "source_group_title",
            "group_title",

            "test_status",
            "feed_quality_score",
            "feed_quality_summary",
            "source_flags",
            "source",
            "classification",
            "stream_url",
            "logo",
            "logo_quality",
            "logo_match_type",
            "logo_provenance",
        ],
        inventory_rows,
    )

    write_csv(
        public_dir / "duplicates.csv",
        ["channel_name", "tvg_id", "source", "stream_url", "already_kept_from", "already_kept_as"],
        duplicate_rows,
    )

    write_csv(
        public_dir / "excluded.csv",
        ["channel_name", "tvg_id", "source", "stream_url", "reason"],
        excluded_rows,
    )

    audit_csv_rows = []

    for row in audit_rows:
        csv_row = dict(row)

        csv_row[
            "expected_language_codes"
        ] = ", ".join(
            row.get(
                "expected_language_codes"
            ) or []
        )

        csv_row[
            "observed_language_codes"
        ] = ", ".join(
            row.get(
                "observed_language_codes"
            ) or []
        )

        audit_csv_rows.append(csv_row)

    write_csv(
        public_dir / "audit.csv",
        [
            "channel",
            "feed_label",
            "feed_index",
            "feed_count",
            "tvg_id",
            "source",
            "discovery",
            "stream_url",
            "protocol",

            "playlist_country_code",
            "output_country_code",
            "playlist_language_code",
            "output_language_code",
            "expected_language_codes",
            "observed_language_codes",
            "language_match",
            "language_acceptance",

            # Legacy fields retained during migration.
            "language",
            "language_code",

            "provenance",
            "source_flags",
            "vlc",
            "vlc_note",
            "samsung",
            "samsung_note",
            "decision",
            "exclude_from_playlist",
            "in_playlist",
            "in_stable_playlist",
            "tested_on",
            "reason",
            "notes",
        ],
        audit_csv_rows,
    )

def write_machine_report(
    public_dir: Path,
    *,
    cfg: dict,
    generated: str,
    published_entries: list[dict],
    test_entries: list[dict],
    excluded_rows: list[dict],
    duplicate_rows: list[dict],
    source_stats: list[dict],
    country_stats: list[dict],
    language_stats: list[dict],
    source_concentration: dict,
    changes: dict,
    audit_warnings: list[str],
    audit_ambiguity_warnings: list[str],
    audit_rows: list[dict],
    unique_channels: list[dict],
    raw_identity_path: str,
    identity_registry,
    country_playlist_counts: dict[str, int],
    language_playlist_counts: dict[str, int],
) -> dict:
    """Build and write public/report.json, returning the payload for callers/tests."""
    report = {
        "schema_version": 23,
        "generated_at": generated,
        "playlists": {
            "stable": {
                "path": str(
                    cfg.get(
                        "output"
                    )
                    or "public/tv.m3u"
                ),
                "stream_urls": len(
                    published_entries
                ),
            },
            "test": {
                "path": str(
                    cfg.get(
                        "test_output"
                    )
                    or "public/test.m3u"
                ),
                "stream_urls": len(
                    test_entries
                ),
            },
            "country_stream_urls": (
                country_playlist_counts
            ),
            "language_stream_urls": (
                language_playlist_counts
            ),
        },		
        "summary": {
            "unique_channels": len(unique_channels),
            "unique_stream_urls": len(published_entries),
            "excluded_from_stable_playlist": len(excluded_rows),
            "added_channels_beyond_base": sum(
                1 for e in published_entries if e["classification"] == "Added channel"
            ),
            "alternative_streams": sum(
                1 for e in published_entries if e["classification"] == "Alternative stream"
            ),
            "duplicate_urls_ignored": len(duplicate_rows),
        },
        "sources": source_stats,
        "countries": country_stats,
        "languages": language_stats,
        "source_concentration": source_concentration.get("summary", {}),
        "geography_language_model": {
            "country_field": "country_code",
            "language_field": "language_codes",
            "language_standard": "ISO-639-3",
            "legacy_country_alias_fields": [
                "language_code",
                "playlist_language_code",
                "output_language_code"
            ],
        },
        "identity": {
            "path": raw_identity_path,
            "canonical_identities": len(identity_registry.identities),
            "selectors": len(identity_registry.selectors),
        },

        "epg": {
            "enabled": bool(
                (cfg.get("epg") or {}).get(
                    "enabled"
                )
            ),
            "public_url": str(
                (cfg.get("epg") or {}).get(
                    "public_url"
                )
                or ""
            ).strip(),
            "sites": list(
                (cfg.get("epg") or {}).get(
                    "sites"
                )
                or []
            ),
        },

        "changes": changes,
        "audit": {
            "warnings": audit_warnings,
            "ambiguous_legacy_audits": audit_ambiguity_warnings,
            "summary": {
                "ambiguous_legacy_audits": len(
                    audit_ambiguity_warnings
                ),
                "language_match_yes": sum(
                    1
                    for e in audit_rows
                    if e.get("language_match") == "yes"
                ),
                "language_multilingual": sum(
                    1
                    for e in audit_rows
                    if e.get("language_match") == "multilingual"
                ),
                "language_mismatch": sum(
                    1
                    for e in audit_rows
                    if e.get("language_match") == "no"
                ),
                "language_unknown": sum(
                    1
                    for e in audit_rows
                    if e.get("language_match") == "unknown"
                ),				
                "current_playlist_rows": sum(1 for e in audit_rows if e["in_playlist"]),
                "tested_on_both": sum(
                    1 for e in audit_rows
                    if e["in_playlist"]
                    and is_tested_status(e["vlc"])
                    and is_tested_status(e["samsung"])
                ),
                "verified": sum(1 for e in audit_rows if e["decision"] == "Verified"),
                "tv_verified": sum(1 for e in audit_rows if e["decision"] == "TV verified"),
                "pc_only": sum(1 for e in audit_rows if e["decision"] == "PC only"),
                "needs_review": sum(1 for e in audit_rows if e["decision"] == "Needs review"),
                "rejected": sum(1 for e in audit_rows if e["decision"] == "Rejected"),
            },
            "channels": audit_rows,
        },
        "channels": unique_channels,
    }

    (public_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


    return report

def print_build_summary(
    *,
    unique_channels: list[dict],
    published_entries: list[dict],
    test_entries: list[dict],
    excluded_rows: list[dict],
    duplicate_rows: list[dict],
    country_playlist_counts: dict[str, int],
    audit_rows: list[dict],
    source_stats: list[dict],
    country_stats: list[dict],
    language_stats: list[dict],
) -> None:
    """Print the human-readable build summary used by local runs and Actions logs."""
    print()
    print("Build complete.")
    print(
        f"Stable unique channels: {len(unique_channels)}"
    )

    print(
        "Stable stream URLs:     "
        f"{len(published_entries)}"
    )

    print(
        "Testing stream URLs:    "
        f"{len(test_entries)}"
    )

    print(
        "Excluded from stable:   "
        f"{len(excluded_rows)}"
    )

    print(
        "Duplicate URLs ignored: "
        f"{len(duplicate_rows)}"
    )

    for (
        country_code,
        stream_count,
    ) in sorted(
        country_playlist_counts.items()
    ):
        print(
            f"Stable {country_code}:"
            f"{' ' * max(1, 15 - len(country_code))}"
            f"{stream_count} streams"
        )
    print(
        "Manual audit:          "
        f"{sum(1 for e in audit_rows if e['decision'] == 'Verified')} verified, "
        f"{sum(1 for e in audit_rows if e['decision'] == 'TV verified')} TV-only, "
        f"{sum(1 for e in audit_rows if e['decision'] == 'PC only')} PC-only, "
        f"{sum(1 for e in audit_rows if e['decision'] == 'Needs review')} needs review, "
        f"{sum(1 for e in audit_rows if e['decision'] == 'Rejected')} rejected"
    )
    for stats in source_stats:
        print(
            f"- [{stats['country_code']}] "
            f"{stats['name']} "
            f"({stats['kind']}): "
            f"{stats['raw_entries']} raw, "
            f"{stats['base_channels_contributed']} base, "
            f"{stats['added_channels_contributed']} added, "
            f"{stats['alternative_streams']} alternatives, "
            f"{stats['duplicate_urls_ignored']} duplicate URLs ignored"
        )

    if country_stats:
        print()
        print("Country summary:")
        for stats in country_stats:
            print(
                f"- {stats['country_code']}: "
                f"{stats['unique_channels']} channels, "
                f"{stats['stream_urls']} streams, "
                f"{stats['base_channels']} base, "
                f"{stats['added_channels']} added, "
                f"{stats['alternative_streams']} alternatives"
            )

    if language_stats:
        print()
        print("Spoken language summary:")

        for stats in language_stats:
            print(
                f"- {stats['language_code']}: "
                f"{stats['unique_channels']} channels, "
                f"{stats['stream_urls']} streams, "
                f"{stats['base_channels']} base, "
                f"{stats['added_channels']} added, "
                f"{stats['alternative_streams']} alternatives"
            )
