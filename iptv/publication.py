#!/usr/bin/env python3
"""Published channel names, group titles and EXTINF rewriting.

Selection decides which streams survive; this module turns those already-selected
entries into final presentation metadata without owning filesystem/build state.
"""
from __future__ import annotations

import re

from country_language import normalize_country_code
from iptv.channel_identity import (
    logical_channel_key,
    normalize_text,
    published_display_from_canonical,
    strip_custom_prefix,
    strip_display_annotations,
    strip_internal_candidate_annotations,
)
from iptv.language_routing import country_name_for_code
from iptv.source_loader import split_extinf

def normalize_content_group(
    group_title: str,
    country_name: str = "",
    language_code: str = "",
    default_group: str = "General",
) -> str:
    """
    Convert an upstream M3U group-title into a useful content category.

    Useful source categories are preserved:
      Music
      News
      Sports
      Movies
      Culture;General
      etc.

    Empty/placeholder categories fall back to General.

    The function also understands both our old status groups:
      HU | Verified
      HU | Needs review

    and our new country/category groups:
      Hungary | News

    This keeps rebuilding idempotent instead of producing:
      Hungary | Hungary | News
    """
    fallback = " ".join(
        str(default_group or "General").split()
    ).strip() or "General"

    value = " ".join(
        str(group_title or "").split()
    ).strip()

    if not value:
        return fallback

    # Strip an already-generated country/language prefix.
    for prefix in (
        country_name,
        language_code,
    ):
        prefix = str(prefix or "").strip()

        if not prefix:
            continue

        marker = f"{prefix} | "

        if value.casefold().startswith(
            marker.casefold()
        ):
            value = value[
                len(marker):
            ].strip()
            break

    if not value:
        return fallback

    # Old Tomas IPTV group-title values used verification status as the
    # category. Never carry those forward as content categories.
    old_status_groups = {
        "verified",
        "tv verified",
        "pc only",
        "needs review",
        "rejected",
    }

    if normalize_text(value) in {
        normalize_text(status)
        for status in old_status_groups
    }:
        return fallback

    ignored_groups = {
        "undefined",
        "unknown",
        "uncategorized",
        "unclassified",
        "none",
        "n a",
    }

    country_key = normalize_text(
        country_name
    )

    language_key = normalize_text(
        language_code
    )

    categories: list[str] = []
    seen: set[str] = set()

    # IPTV-org can use multiple categories separated by semicolons.
    # Preserve all meaningful ones.
    for raw_part in value.split(";"):
        part = " ".join(
            raw_part.split()
        ).strip()

        if not part:
            continue

        key = normalize_text(part)

        if not key:
            continue

        if key in ignored_groups:
            continue

        # Some external playlists use the country itself as group-title.
        # "Hungary | Hungary" is not useful, so treat that as General.
        if key in {
            country_key,
            language_key,
        }:
            continue

        if key in seen:
            continue

        seen.add(key)
        categories.append(part)

    if not categories:
        return fallback

    return ";".join(categories)

def rewrite_extinf_line(line: str, new_name: str, group_title: str) -> str:
    metadata, _old_name = split_extinf(line)
    safe_group = (group_title or "").replace('"', "'")
    if re.search(r'\s+group-title="[^"]*"', metadata, flags=re.IGNORECASE):
        metadata = re.sub(
            r'\s+group-title="[^"]*"',
            f' group-title="{safe_group}"',
            metadata,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        metadata += f' group-title="{safe_group}"'

    # Some source playlists put research provenance in tvg-name, e.g.
    # "JOJ Šport 2 ANTIK TEST". Clean it as well because a number of
    # IPTV clients prefer tvg-name over the visible text after the comma.
    tvg_name_match = re.search(
        r'\s+tvg-name="([^"]*)"',
        metadata,
        flags=re.IGNORECASE,
    )
    if tvg_name_match:
        clean_tvg_name = strip_internal_candidate_annotations(
            tvg_name_match.group(1)
        ).replace('"', "'")
        metadata = re.sub(
            r'\s+tvg-name="[^"]*"',
            f' tvg-name="{clean_tvg_name}"',
            metadata,
            count=1,
            flags=re.IGNORECASE,
        )

    return f"{metadata},{new_name}"

def rewrite_entry_lines(lines: list[str], new_name: str, group_title: str) -> list[str]:
    updated = list(lines)
    for i, line in enumerate(updated):
        if line.strip().startswith("#EXTINF:"):
            updated[i] = rewrite_extinf_line(line, new_name, group_title)
            break
    return updated

def playlist_status_suffix(decision: str) -> str:
    return {
        "Verified": "OK",
        "TV verified": "TV",
        "PC only": "PC",
        "Rejected": "X",
    }.get(decision, "?")

def prepare_published_entries(
    candidates: list[dict],
    cfg: dict,
) -> list[dict]:
    """
    Convert candidate entries into final playlist entries with:
      - [HU OK] / [SK TV] / [HU ?] prefixes
      - feed numbering
      - country/category group-title
    """
    visible_groups: dict[
        str,
        list[dict],
    ] = {}

    for entry in candidates:
        visible_groups.setdefault(
            logical_channel_key(entry),
            [],
        ).append(
            entry
        )

    published_entries: list[dict] = []

    for (
        channel_key_value,
        group,
    ) in visible_groups.items():
        group.sort(
            key=lambda e: int(
                e.get(
                    "_source_order"
                )
                or 0
            )
        )

        visible_count = len(
            group
        )

        # Pick one clean, canonical channel name for all feeds.
        # A URL-specific manual audit name is authoritative: manual playback
        # often resolves shortened or research-only upstream display names.
        canonical_name = ""

        for candidate in group:
            audit_name = str(
                (candidate.get("_audit") or {}).get("channel")
                or ""
            ).strip()
            # Feed numbering is presentation metadata and is added below.
            # Do not let an old audit label such as "Channel Feed 2" become
            # the logical base channel name.
            audit_name = re.sub(
                r"\s+Feed\s+\d+\s*$",
                "",
                audit_name,
                flags=re.IGNORECASE,
            ).strip()

            candidate_name = (
                audit_name
                or str(
                    candidate.get("channel_name")
                    or candidate.get("tvg_name")
                    or candidate.get("display_name")
                    or ""
                ).strip()
            )

            candidate_name = strip_custom_prefix(
                candidate_name
            )

            candidate_name = strip_internal_candidate_annotations(
                candidate_name
            )

            candidate_name = strip_display_annotations(
                candidate_name
            )

            if candidate_name:
                canonical_name = candidate_name
                break

        if not canonical_name:
            canonical_name = "Unnamed channel"
			
        for (
            visible_index,
            entry,
        ) in enumerate(
            group,
            start=1,
        ):
            decision = entry.get(
                "_decision",
                "Needs review",
            )

            country_code = (
                normalize_country_code(
                    str(
                        entry.get("country_code")
                        or entry.get("language_code")
                        or cfg.get("default_country_code")
                        
                        or "HU"
                    )
                )
                or "HU"
            )

            suffix = (
                playlist_status_suffix(
                    decision
                )
            )

            if visible_count > 1:
                # Multiple URLs for the same channel:
                # Channel Name
                # Channel Name Feed 2
                # Channel Name Feed 3
                original_display = canonical_name

                if visible_index > 1:
                    original_display += (
                        f" Feed {visible_index}"
                    )
            else:
                # The published base name always comes from canonical channel
                # identity. Preserve only recognized quality/status suffixes
                # from the research display name, collapsing exact repeats.
                original_display = published_display_from_canonical(
                    canonical_name,
                    str(entry.get("display_name") or ""),
                )

            published_name = (
                f"[{country_code} {suffix}] "
                f"{original_display}"
            )

            country_name = str(
                entry.get(
                    "country_name"
                )
                or country_name_for_code(
                    cfg,
                    country_code,
                )
            ).strip()

            content_group = (
                normalize_content_group(
                    entry.get(
                        "content_group"
                    )
                    or entry.get(
                        "source_group_title"
                    )
                    or entry.get(
                        "group_title"
                    )
                    or "",
                    country_name=(
                        country_name
                    ),
                    language_code=country_code,
                    default_group=(
                        "General"
                    ),
                )
            )

            group_title = (
                f"{country_name} | "
                f"{content_group}"
            )

            published = dict(
                entry
            )

            published[
                "published_name"
            ] = published_name

            published[
                "test_status"
            ] = decision

            published[
                "group_title"
            ] = group_title

            published["country_code"] = country_code
            published["language_code"] = country_code  # legacy alias
            published[
                "country_name"
            ] = country_name

            published[
                "content_group"
            ] = content_group

            published[
                "source_group_title"
            ] = str(
                entry.get(
                    "source_group_title"
                )
                or ""
            ).strip()

            published[
                "visible_feed_index"
            ] = visible_index

            published[
                "visible_feed_count"
            ] = visible_count

            published["lines"] = (
                rewrite_entry_lines(
                    entry["lines"],
                    published_name,
                    group_title,
                )
            )

            published_entries.append(
                published
            )

    published_entries.sort(
        key=lambda e: (
            normalize_text(
                e.get(
                    "country_name",
                    "",
                )
            ),
            normalize_text(
                e.get(
                    "channel_name",
                    "",
                )
            ),
            normalize_text(
                e.get(
                    "published_name",
                    "",
                )
            ),
        )
    )

    return published_entries
