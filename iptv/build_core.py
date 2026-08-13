#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import sys
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path
from iptv.stable_selection import stable_block_reason
from iptv.stable_selection import select_stable_playlist_candidates as _select_stable_playlist_candidates
from iptv.feed_selection import (
    select_playlist_candidates,
    make_test_playlist_candidates,
)
from iptv.audit import (
    calculate_audit_decision,
    infer_protocol,
    canonical_audit_name,
    normalize_audit_decision_token,
    audit_status_is_recognized,
    audit_excluded,
    exact_url_audit_matches_entry,
    validate_audit_items,
    audit_match_key,
    prepare_audit_rows,
    audit_rows_by_stream_url,
)
from iptv.language_routing import (
    LANGUAGE_NAME_TO_CODE,
    normalize_language_code,
    normalize_language_codes,
    normalize_language_match,
    legacy_language_is_negative,
    derive_language_match,
    resolve_language_info,
    format_language_codes,
    language_mismatch_reason,
    configured_playlist_country_codes,
    configured_playlist_language_codes,
    configured_spoken_language_codes,
    audit_playlist_country_code,
    audit_playlist_scope_code,
    verified_output_country_code,
    verified_output_language_code,
    language_acceptance_state,
)
from iptv.source_loader import (
    ATTR_RE,
    SOURCE_FLAG_RE,
    VALID_SOURCE_KINDS,
    http_get_text,
    download_m3u,
    split_extinf,
    parse_entries,
    normalize_source_kind,
    source_spec,
)
from iptv.playlist_writer import playlist_header
from iptv.playlist_writer import write_m3u_playlist as _write_m3u_playlist
from iptv.playback_status import (
    normalize_test_status,
    is_tested_status,
)
from iptv.reports import (
    summarize_country_stats,
    summarize_language_stats,
    safe_csv_value,
    write_csv,
)
from iptv.channel_identity import logical_channel_key
from iptv.channel_identity import (
    QUALITY_SUFFIX_RE,
    TVG_VARIANT_SUFFIX_RE,
    CUSTOM_PREFIX_RE,
    INTERNAL_PROVIDER_TEST_SUFFIX_RE,
    split_display_annotations,
    deduplicate_identical_annotations,
    collapse_duplicate_quality_suffixes,
    published_display_from_canonical,
    strip_display_annotations,
    normalize_text,
    strip_internal_candidate_annotations,
    normalized_tvg_id,
    canonical_stream_url,
    apply_canonical_identity,
    channel_key,
    strip_custom_prefix,
)
from dashboard import copy_dashboard_assets, render_dashboard
from feed_quality import build_feed_quality_context, score_feed_quality
from identity_overrides import IdentityRegistry, load_identity_registry
from source_concentration import build_source_concentration
from country_language import (
    configured_country_codes,
    configured_language_codes,
    country_code_from_tvg_id,
    legacy_country_scope_from_language_token,
    normalize_country_code,
    normalize_language_code as normalize_spoken_language_code,
    normalize_language_codes as normalize_spoken_language_codes,
    source_country_code,
    source_country_mode,
    source_language_codes,
    verified_country_route,
)

ROOT = Path(__file__).resolve().parent






	
def read_local(path: str) -> str:
    p = ROOT / path
    if not p.is_file():
        raise RuntimeError(f"Required local source {path} not found")
    return p.read_text(encoding="utf-8-sig")






















	



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



def country_name_for_code(
    cfg: dict,
    country_code: str,
) -> str:
    """Return the human-readable name for one publication country."""
    code = normalize_country_code(country_code) or str(country_code or "").strip().upper()
    country_names = cfg.get("country_names") or {}
    if isinstance(country_names, dict):
        country = str(country_names.get(code) or "").strip()
        if country:
            return country
    return code or "Other"


def country_name_for_language(
    cfg: dict,
    language_code: str,
) -> str:
    """Legacy compatibility alias: historical language_code stored country scope."""
    return country_name_for_code(cfg, language_code)

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








def load_previous_report(url: str | None) -> dict | None:
    if not url:
        return None

    try:
        text = http_get_text(url, timeout=15)
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("channels"), list):
            return data
    except Exception as exc:
        print(f"Previous report unavailable: {exc}")

    return None







def load_audit(path: str | None) -> list[dict]:
    if not path:
        return []

    p = ROOT / path
    if not p.exists():
        print(f"Audit file not found: {path}")
        return []

    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("channels", [])

    if not isinstance(data, list):
        raise RuntimeError("audit.json must contain a list or an object with a 'channels' list.")

    return [dict(item) for item in data if isinstance(item, dict)]




















	
























	








def route_candidates_to_verified_countries(
    candidates: list[dict],
    cfg: dict,
) -> list[dict]:
    """Apply country routing and attach verified observed spoken-language metadata."""
    supported = set(configured_playlist_country_codes(cfg))
    routed: list[dict] = []
    for entry in candidates:
        candidate = dict(entry)
        source_code = (
            normalize_country_code(
                str(
                    candidate.get("country_code")
                    or candidate.get("language_code")
                    or cfg.get("default_country_code")
                    or cfg.get("default_language_code")
                    or "HU"
                )
            )
            or "HU"
        )
        audit = candidate.get("_audit") or {}
        decision = str(candidate.get("_decision") or audit.get("decision") or "").strip()
        observed_languages = normalize_spoken_language_codes(
            audit.get("observed_language_codes")
        )
        if decision in {"Verified", "TV verified"} and observed_languages:
            candidate["language_codes"] = observed_languages
        else:
            candidate["language_codes"] = normalize_spoken_language_codes(
                candidate.get("language_codes")
            )

        output_code = normalize_country_code(
            str(audit.get("output_country_code") or audit.get("output_language_code") or "")
        ) or verified_output_country_code(
            audit,
            source_code,
            cfg,
        )
        if output_code not in supported:
            output_code = source_code
        candidate["source_country_code"] = source_code
        candidate["country_code"] = output_code
        # Legacy entry alias retained so older report/dashboard code keeps working.
        candidate["language_code"] = output_code
        candidate["country_name"] = country_name_for_code(cfg, output_code)
        routed.append(candidate)
    return routed


def route_candidates_to_verified_languages(
    candidates: list[dict],
    cfg: dict,
) -> list[dict]:
    """Legacy compatibility alias."""
    return route_candidates_to_verified_countries(candidates, cfg)







def select_stable_playlist_candidates(
    final_entries: list[dict],
    audit_rows: list[dict],
    cfg: dict,
):
    """Compatibility wrapper that keeps live build globals injectable."""
    return _select_stable_playlist_candidates(
        final_entries,
        audit_rows,
        cfg,
        make_test_candidates=make_test_playlist_candidates,
        route_candidates=route_candidates_to_verified_countries,
        build_quality_context=build_feed_quality_context,
        score_quality=score_feed_quality,
    )

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
                        or cfg.get("default_language_code")
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


def build_language_catalog_entries(
    country_entries: list[dict],
    language_only_entries: list[dict],
) -> list[dict]:
    """Build a URL-unique catalog for spoken-language playlists.

    Existing country entries are inserted first and therefore keep authority
    for an exact URL already published by the country build. A language-only
    duplicate may still add additional spoken-language metadata, but it cannot
    steal or rewrite the established country identity.
    """
    result: list[dict] = []
    by_url: dict[str, dict] = {}

    for entry in [*country_entries, *language_only_entries]:
        url = str(entry.get("url") or "").strip()
        url_key = canonical_stream_url(url)
        if not url_key:
            continue

        languages = normalize_spoken_language_codes(
            entry.get("language_codes")
        )

        current = by_url.get(url_key)
        if current is not None:
            current["language_codes"] = normalize_spoken_language_codes(
                [
                    *(current.get("language_codes") or []),
                    *languages,
                ]
            )
            continue

        candidate = dict(entry)
        candidate["language_codes"] = languages
        by_url[url_key] = candidate
        result.append(candidate)

    return result


def entries_for_spoken_language(
    entries: list[dict],
    language_code: str,
) -> list[dict]:
    """Return entries explicitly carrying one normalized spoken language."""
    code = normalize_spoken_language_code(language_code)
    if not code:
        raise ValueError(f"Unsupported spoken language code: {language_code!r}")

    return [
        entry
        for entry in entries
        if code in normalize_spoken_language_codes(
            entry.get("language_codes")
        )
    ]


	


def write_m3u_playlist(
    path: Path,
    cfg: dict,
    entries: list[dict],
    generated: str,
    playlist_label: str,
    name_style: str = "status",
) -> None:
    """Compatibility wrapper around the extracted playlist writer."""
    return _write_m3u_playlist(
        path,
        cfg,
        entries,
        generated,
        playlist_label,
        name_style=name_style,
        strip_custom_prefix=strip_custom_prefix,
        normalize_country_code=normalize_country_code,
        rewrite_entry_lines=rewrite_entry_lines,
    )

def make_dashboard(
    cfg: dict,
    generated: str,
    final_entries: list[dict],
    unique_channels: list[dict],
    source_stats: list[dict],
    language_stats: list[dict],
    duplicate_rows: list[dict],
    changes: dict,
    audit_rows: list[dict],
    audit_ambiguity_warnings: list[str],
    country_stats: list[dict] | None = None,
) -> str:
    """Render the dashboard through the standalone presentation layer."""
    if country_stats is None:
        country_stats = summarize_country_stats(final_entries, source_stats)
    return render_dashboard(
        cfg=cfg,
        generated=generated,
        final_entries=final_entries,
        unique_channels=unique_channels,
        source_stats=source_stats,
        country_stats=country_stats,
        language_stats=language_stats,
        duplicate_rows=duplicate_rows,
        changes=changes,
        audit_rows=audit_rows,
        audit_ambiguity_warnings=audit_ambiguity_warnings,
        is_tested_status=is_tested_status,
        format_language_codes=format_language_codes,
    )




def main(strict: bool = False) -> None:
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    audit_items = load_audit(cfg.get("audit_path", "audit.json"))
    supported_language_codes = configured_spoken_language_codes(cfg)
    supported_country_codes = configured_playlist_country_codes(cfg)

    raw_identity_path = str(
        cfg.get("identity_overrides_path")
        or ""
    ).strip()

    if raw_identity_path:
        identity_path = ROOT / raw_identity_path
        identity_registry = load_identity_registry(identity_path)
    else:
        identity_path = None
        identity_registry = IdentityRegistry({
            "schema_version": 1,
            "identities": {},
            "selectors": [],
        })

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
            text = download_m3u(location)
        elif spec.get("path"):
            location = str(spec["path"])
            print(f"Reading {name}: {location}")
            text = read_local(location)
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

    audit_warnings, audit_ambiguity_warnings = validate_audit_items(
        audit_items,
        final_entries,
        strict=strict,
    )

    for warning in audit_warnings:
        print(
            f"WARNING: {warning}",
            file=sys.stderr,
        )

    audit_rows = prepare_audit_rows(
        audit_items,
        final_entries,
        supported_language_codes=(
            supported_language_codes
        ),
        cfg=cfg,
    )

    language_catalog_entries = build_language_catalog_entries(
        final_entries,
        language_only_entries,
    )
    language_audit_rows = prepare_audit_rows(
        audit_items,
        language_catalog_entries,
        supported_language_codes=(
            supported_language_codes
        ),
        cfg=cfg,
    )

    test_candidates = (
        route_candidates_to_verified_countries(
            make_test_playlist_candidates(
                final_entries,
                audit_rows,
            ),
            cfg,
        )
    )

    (
        stable_candidates,
        excluded_rows,
    ) = (
        select_stable_playlist_candidates(
            final_entries,
            audit_rows,
            cfg,
        )
    )

    (
        language_stable_candidates,
        _language_excluded_rows,
    ) = select_stable_playlist_candidates(
        language_catalog_entries,
        language_audit_rows,
        cfg,
    )

    test_entries = (
        prepare_published_entries(
            test_candidates,
            cfg,
        )
    )

    # Keep the old variable name for the rest of the reporting/dashboard
    # code. From now on, published_entries means the stable family playlist.
    published_entries = (
        prepare_published_entries(
            stable_candidates,
            cfg,
        )
    )

    language_published_entries = prepare_published_entries(
        language_stable_candidates,
        cfg,
    )

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

    previous_report = load_previous_report(cfg.get("previous_report_url"))
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

    out_path = ROOT / cfg.get(
        "output",
        "public/tv.m3u",
    )

    public_dir = (
        out_path.parent
    )

    public_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    generated = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    source_concentration = build_source_concentration(
        published_entries,
        cfg,
        generated_at=generated,
    )
    (public_dir / "source-concentration.json").write_text(
        json.dumps(source_concentration, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Main stable family playlist.
    write_m3u_playlist(
        out_path,
        cfg,
        published_entries,
        generated,
        "Stable family playlist",
        name_style="country",
    )

    # Full testing/research playlist.
    test_out_path = (
        ROOT
        / str(
            cfg.get(
                "test_output"
            )
            or "public/test.m3u"
        )
    )

    write_m3u_playlist(
        test_out_path,
        cfg,
        test_entries,
        generated,
        "Testing and research playlist",
    )

    # Stable per-country playlists.
    country_outputs = (
        cfg.get(
            "country_outputs"
        )
        or {
            "HU": "public/hu.m3u",
            "SK": "public/sk.m3u",
        }
    )

    if not isinstance(
        country_outputs,
        dict,
    ):
        raise RuntimeError(
            "country_outputs must be "
            "a JSON object."
        )

    country_playlist_counts: dict[
        str,
        int,
    ] = {}

    for (
        raw_country_code,
        relative_path,
    ) in country_outputs.items():
        country_code = (
            normalize_country_code(str(raw_country_code))
            or str(raw_country_code).strip().upper()
        )

        country_entries = [
            entry
            for entry
            in published_entries
            if str(
                entry.get(
                    "country_code"
                )
                or entry.get("language_code")
                or ""
            ).upper()
            == country_code
        ]

        country_path = (
            ROOT
            / str(
                relative_path
            )
        )

        country_name = (
            country_name_for_code(
                cfg,
                country_code,
            )
        )

        write_m3u_playlist(
            country_path,
            cfg,
            country_entries,
            generated,
            (
                f"Stable {country_name} "
                "playlist"
            ),
            name_style="plain",
        )

        country_playlist_counts[
            country_code
        ] = len(
            country_entries
        )

    # Stable per-spoken-language playlists. These are independent of enabled
    # country outputs: a verified RS/hun entry can therefore live in hun.m3u
    # even when there is no public rs.m3u yet. Country prefixes remain visible
    # inside language playlists so geography is never lost.
    language_outputs = cfg.get("language_outputs") or {}
    if not isinstance(language_outputs, dict):
        raise RuntimeError("language_outputs must be a JSON object.")

    language_names = cfg.get("language_names") or {}
    if not isinstance(language_names, dict):
        raise RuntimeError("language_names must be a JSON object.")

    language_playlist_counts: dict[str, int] = {}

    for raw_language_code, relative_path in language_outputs.items():
        language_code = normalize_spoken_language_code(
            str(raw_language_code)
        )
        if not language_code:
            raise RuntimeError(
                f"Invalid language_outputs key: {raw_language_code!r}"
            )

        raw_path = str(relative_path or "").strip()
        if not raw_path:
            raise RuntimeError(
                f"language_outputs[{raw_language_code!r}] requires a path."
            )

        language_entries = entries_for_spoken_language(
            language_published_entries,
            language_code,
        )

        language_name = str(
            language_names.get(language_code)
            or language_code
        ).strip()

        write_m3u_playlist(
            ROOT / raw_path,
            cfg,
            language_entries,
            generated,
            f"Stable {language_name} spoken-language playlist",
            name_style="country",
        )

        language_playlist_counts[language_code] = len(language_entries)

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

    copy_dashboard_assets(public_dir)

    (public_dir / "index.html").write_text(
        make_dashboard(
            cfg=cfg,
            generated=generated,
            final_entries=published_entries,
            unique_channels=unique_channels,
            source_stats=source_stats,
            country_stats=country_stats,
            language_stats=language_stats,
            duplicate_rows=duplicate_rows,
            changes=changes,
            audit_rows=audit_rows,
            audit_ambiguity_warnings=(
                audit_ambiguity_warnings
            ),
        ),
        encoding="utf-8",
    )

    (public_dir / ".nojekyll").write_text("", encoding="utf-8")

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


if __name__ == "__main__":
    try:
        args = sys.argv[1:]

        unknown_args = [
            arg
            for arg in args
            if arg != "--strict"
        ]

        if unknown_args:
            raise RuntimeError(
                "Unknown command-line option(s): "
                + ", ".join(unknown_args)
            )

        strict = "--strict" in args

        if strict:
            print(
                "Strict audit validation enabled."
            )

        main(strict=strict)

    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
