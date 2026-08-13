#!/usr/bin/env python3
"""Source ingestion, canonical identity application and global URL deduplication."""
from __future__ import annotations

import sys

from country_language import (
    country_code_from_tvg_id,
    normalize_country_code,
    normalize_language_codes as normalize_spoken_language_codes,
    source_country_code,
    source_country_mode,
    source_language_codes,
)
from iptv.channel_identity import (
    apply_canonical_identity,
    canonical_stream_url,
    channel_key,
    logical_channel_key,
    strip_display_annotations,
    strip_internal_candidate_annotations,
)
from iptv.language_routing import country_name_for_code
from iptv.publication import normalize_content_group
from iptv.source_loader import (
    SOURCE_FLAG_RE,
    normalize_source_kind,
    parse_entries,
    source_spec,
)

def extract_source_flags(name: str) -> list[str]:
    flags: list[str] = []
    for match in SOURCE_FLAG_RE.finditer(name or ""):
        value = match.group(1).casefold()
        if "geo" in value:
            label = "Geo-blocked"
        elif "24/7" in value:
            label = "Not 24/7"
        else:
            label = "Offline"
        if label not in flags:
            flags.append(label)
    return flags


def collect_source_entries(
    cfg: dict,
    identity_registry,
    supported_country_codes,
    *,
    remote_loader,
    local_loader,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Load configured sources and apply the project's global stream deduplication.

    Returns country-publication entries, language-only entries, ignored duplicate
    rows and per-source contribution statistics. Loaders are injected so build.py
    keeps its historical ROOT override and network monkeypatch behavior.
    """
    source_items: list[dict] = []

    # Entries under "sources" are base sources by default.
    # Anything that is not a base source should declare its kind explicitly,
    # for example kind="alternatives".
    for i, item in enumerate(
        cfg.get("sources", []),
        start=1,
    ):
        source_items.append(
            source_spec(
                item,
                f"Source {i}",
                "base",
            )
        )

    for i, item in enumerate(
        cfg.get("extras", []),
        start=1,
    ):
        source_items.append(
            source_spec(
                item,
                f"Extra {i}",
                "extras",
            )
        )

    if not source_items:
        raise RuntimeError("config.json contains no sources or extras.")

    final_entries: list[dict] = []
    # Country-neutral language sources may contain verified channels from
    # countries that do not have a country playlist yet. Keep those entries
    # isolated so they can feed by-language outputs without changing the
    # existing tv.m3u/test.m3u/per-country publication universe.
    language_only_entries: list[dict] = []
    duplicate_rows: list[dict] = []
    source_stats: list[dict] = []

    seen_urls: dict[str, dict] = {}
    seen_channels: dict[str, dict] = {}

    for source_index, spec in enumerate(
        source_items
    ):
        name = str(
            spec.get("name")
            or f"Source {source_index + 1}"
        )

        kind = normalize_source_kind(
            spec.get("kind"),
            default="source",
        )

        country_mode = source_country_mode(spec)
        country_code = source_country_code(spec, cfg)
        language_codes = source_language_codes(spec, cfg, country_code)
        # Historical config/build code called this country bucket language_code.
        language_code = country_code

        if spec.get("url"):
            location = str(spec["url"])
            print(f"Downloading {name}: {location}")
            text = remote_loader(location)
        elif spec.get("path"):
            location = str(spec["path"])
            print(f"Reading {name}: {location}")
            text = local_loader(location)
        else:
            raise RuntimeError(f"Source '{name}' has neither 'url' nor 'path'.")

        entries = parse_entries(text)
        if spec.get("url") and not entries:
            raise RuntimeError(f"No playable entries found in remote source: {location}")

        source_keys: set[str] = set()
        kept = 0
        new_channels = 0

        base_channels = 0
        added_channels = 0
        alternatives = 0

        duplicate_urls = 0
        country_derivation_failures = 0
        out_of_scope_country_entries = 0

        for entry in entries:
            url = (entry.get("url") or "").strip()
            if not url:
                continue

            url_key = canonical_stream_url(url)

            entry["source"] = name
            entry["source_kind"] = kind
            entry_country = normalize_country_code(
                str(entry.get("country_code") or "")
            )
            if not entry_country and country_mode == "tvg_id":
                entry_country = country_code_from_tvg_id(
                    str(entry.get("tvg_id") or "")
                )
            if not entry_country:
                entry_country = country_code
            entry_languages = (
                normalize_spoken_language_codes(entry.get("language_codes"))
                or list(language_codes)
            )
            entry["country_code"] = entry_country
            entry["language_codes"] = entry_languages
            entry["language_code"] = entry_country  # legacy country alias

            identity_name = strip_display_annotations(
                strip_internal_candidate_annotations(
                    entry.get("tvg_name")
                    or entry.get("display_name")
                    or ""
                )
            )
            identity_match = identity_registry.resolve(
                entry,
                source=name,
                normalized_name=identity_name,
            )

            entry["identity_match_type"] = ""
            entry["identity_selector_index"] = None
            entry["identity_note"] = ""

            if identity_match:
                canonical_identity = identity_match["identity"]
                apply_canonical_identity(
                    entry,
                    canonical_identity,
                )
                entry["canonical_id"] = identity_match["canonical_id"]
                entry["identity_match_type"] = identity_match["match_type"]
                entry["identity_selector_index"] = identity_match["selector_index"]
                entry["identity_note"] = identity_match["note"]

                raw_identity_country = str(
                    canonical_identity.get("country_code")
                    or canonical_identity.get("language_code")
                    or ""
                ).strip()
                if raw_identity_country:
                    identity_country = normalize_country_code(raw_identity_country)
                    if not identity_country:
                        raise RuntimeError(
                            "Invalid canonical identity country_code "
                            f"{raw_identity_country!r} for {url}"
                        )
                    entry["country_code"] = identity_country
                    entry["language_code"] = identity_country

                raw_identity_languages = canonical_identity.get("language_codes")
                if raw_identity_languages:
                    identity_languages = normalize_spoken_language_codes(raw_identity_languages)
                    if not identity_languages:
                        raise RuntimeError(
                            "Invalid canonical identity language_codes "
                            f"{raw_identity_languages!r} for {url}"
                        )
                    entry["language_codes"] = identity_languages

            final_entry_country = normalize_country_code(
                str(entry.get("country_code") or entry.get("language_code") or "")
            )
            if not final_entry_country:
                country_derivation_failures += 1
                print(
                    "WARNING: skipping source entry whose country could not be "
                    f"derived from tvg-id {entry.get('tvg_id')!r}: {url}",
                    file=sys.stderr,
                )
                continue

            entry["country_code"] = final_entry_country
            entry["language_code"] = final_entry_country

            language_only_country_entry = (
                country_mode == "tvg_id"
                and final_entry_country not in supported_country_codes
            )
            if language_only_country_entry:
                out_of_scope_country_entries += 1

            key = channel_key(entry)
            source_keys.add(key)

            clean_name = (
                strip_display_annotations(
                    strip_internal_candidate_annotations(
                        entry.get(
                            "display_name",
                            ""
                        )
                    )
                )
            )

            entry["channel_key"] = key
            entry["channel_name"] = clean_name

            logical_key = (
                logical_channel_key(
                    entry
                )
            )

            country_name = str(
                spec.get("country_name")
                or country_name_for_code(
                    cfg,
                    entry["country_code"],
                )
            ).strip()

            entry[
                "country_name"
            ] = country_name

            # Preserve exactly what the source supplied before we create
            # our own final playlist grouping.
            source_group_title = str(
                entry.get("group_title")
                or ""
            ).strip()

            entry[
                "source_group_title"
            ] = source_group_title

            entry[
                "content_group"
            ] = normalize_content_group(
                source_group_title,
                country_name=country_name,
                language_code=entry["country_code"],
                default_group=str(
                    spec.get(
                        "default_group_title"
                    )
                    or "General"
                ),
            )

            entry[
                "source_flags"
            ] = extract_source_flags(
                entry.get(
                    "display_name",
                    "",
                )
            )

            if language_only_country_entry:
                # Preserve this candidate only for language-centric outputs.
                # Do not put it into seen_urls/seen_channels: doing so would
                # change which existing HU/SK/CZ source wins duplicate URL
                # precedence later in the normal country build.
                entry["classification"] = "Language-only channel"
                entry["country_output_enabled"] = False
                language_only_entries.append(dict(entry))
                continue

            entry["country_output_enabled"] = True

            if url_key in seen_urls:
                duplicate_urls += 1
                first = seen_urls[url_key]

                duplicate_rows.append({
                    "channel_name": clean_name,
                    "tvg_id": entry.get("tvg_id", ""),
                    "source": name,
                    "stream_url": url,
                    "already_kept_from": first["source"],
                    "already_kept_as": first["channel_name"],
                })
                continue

            if logical_key not in seen_channels:
                new_channels += 1

                if kind == "base":
                    classification = (
                        "Base channel"
                    )
                    base_channels += 1

                else:
                    classification = (
                        "Added channel"
                    )
                    added_channels += 1

                seen_channels[logical_key] = {
                    "key": logical_key,
                    "raw_key": key,
                    "name": clean_name,
                    "canonical_id": entry.get("canonical_id", ""),
                    "first_source": name,
                    "first_source_kind": kind,
                    "language_code": (
                        entry["language_code"]
                    ),
                }

            else:
                classification = (
                    "Alternative stream"
                )

                alternatives += 1

            entry["classification"] = classification
            final_entries.append(entry)
            seen_urls[url_key] = entry
            kept += 1

        source_stats.append({
            "name": name,
            "kind": kind,
            "country_mode": country_mode,
            "country_code": country_code,
            "language_codes": list(language_codes),
            "language_code": country_code,  # legacy country alias
            "location": location,

            "raw_entries": len(entries),
            "unique_channels_in_source": (
                len(source_keys)
            ),
            "kept_stream_urls": kept,

            "new_channels_contributed": (
                new_channels
            ),
            "base_channels_contributed": (
                base_channels
            ),
            "added_channels_contributed": (
                added_channels
            ),
            "alternative_streams": (
                alternatives
            ),

            "duplicate_urls_ignored": (
                duplicate_urls
            ),
            "country_derivation_failures": (
                country_derivation_failures
            ),
            "out_of_scope_country_entries": (
                out_of_scope_country_entries
            ),
        })


    return final_entries, language_only_entries, duplicate_rows, source_stats
