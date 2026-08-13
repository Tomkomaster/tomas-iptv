#!/usr/bin/env python3
"""Canonical channel identity and display-name helpers for Tomas IPTV.

This module is intentionally build-state free. It owns logical channel identity,
stream-URL identity normalization, safe display-name cleanup and application of
already-resolved canonical metadata. Selector resolution itself remains in
``identity_overrides.py``.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse, urlunparse

from iptv.source_loader import split_extinf

QUALITY_SUFFIX_RE = re.compile(
    r"""
    \s*
    (?:
        \((?:2160p|1440p|1080p|720p|576p|540p|480p|360p|240p|4K|UHD|FHD|HD|SD)\)
        |
        \[(?:2160p|1440p|1080p|720p|576p|540p|480p|360p|240p|4K|UHD|FHD|HD|SD)\]
        |
        \[(?:Geo[- ]?blocked|Not\s*24/7|Offline)\]
    )
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

TVG_VARIANT_SUFFIX_RE = re.compile(r'@(SD|HD|FHD|UHD|4K|\d{3,4}P)$', re.IGNORECASE)

CUSTOM_PREFIX_RE = re.compile(r'^\[[A-Z]{2,3}(?:\s+(?:OK|TV|PC|\?|X))?\]\s*', re.IGNORECASE)

INTERNAL_PROVIDER_TEST_SUFFIX_RE = re.compile(
    r"""
    (?:\s*[-–—]\s*|\s+)
    (?:
        LEGACY(?:\s+ANTIK)?
        | ANTIK
        | PANACCESS
        | KABELKO
        | REBIT
        | STREAMLOCK
        | ZSTV\s+DIRECT
        | JOJ\s+CDN
    )
    \s+TEST
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

def split_display_annotations(name: str) -> tuple[str, list[str]]:
    """Split recognized trailing quality/status annotations from a name."""
    value = " ".join(str(name or "").split()).strip()
    annotations: list[str] = []

    while value:
        match = QUALITY_SUFFIX_RE.search(value)
        if not match or match.end() != len(value):
            break

        annotation = " ".join(match.group(0).split()).strip()
        if annotation:
            annotations.append(annotation)

        value = value[:match.start()].strip()

    annotations.reverse()
    return (value or "Unnamed channel", annotations)

def deduplicate_identical_annotations(annotations: list[str]) -> list[str]:
    """Collapse only adjacent identical recognized annotations."""
    result: list[str] = []

    for annotation in annotations:
        if (
            result
            and annotation.casefold() == result[-1].casefold()
        ):
            continue
        result.append(annotation)

    return result

def collapse_duplicate_quality_suffixes(name: str) -> str:
    """Collapse repeated identical trailing quality/status suffixes safely."""
    base, annotations = split_display_annotations(name)
    annotations = deduplicate_identical_annotations(annotations)
    return " ".join([base, *annotations]).strip()

def published_display_from_canonical(
    canonical_name: str,
    research_display_name: str,
) -> str:
    """Build a published name from canonical identity plus safe annotations.

    Research/provider wording stays out of the base identity. Only the
    already-recognized trailing quality/status annotations are carried over.
    """
    cleaned_display = strip_internal_candidate_annotations(
        strip_custom_prefix(research_display_name)
    )
    _, annotations = split_display_annotations(cleaned_display)
    annotations = deduplicate_identical_annotations(annotations)
    return " ".join([canonical_name, *annotations]).strip()

def strip_display_annotations(name: str) -> str:
    base, _ = split_display_annotations(name)
    return base

def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())

def strip_internal_candidate_annotations(name: str) -> str:
    """Remove provider/research TEST labels from a channel name.

    Labels such as ``ANTIK TEST`` and ``PANACCESS TEST`` describe where a
    candidate URL came from. They belong in comments/audit provenance, not in
    the logical channel identity or the name shown to playlist users.
    """
    value = " ".join(str(name or "").split()).strip()
    previous = None
    while value and value != previous:
        previous = value
        value = INTERNAL_PROVIDER_TEST_SUFFIX_RE.sub("", value).strip()
    return value or "Unnamed channel"

def normalized_tvg_id(tvg_id: str) -> str:
    value = (tvg_id or "").strip()

    # IPTV-org identity exception:
    # ducktv HD is a separate station from regular ducktv,
    # despite its tvg-id being expressed as ducktv.sk@HD.
    identity_overrides = {
        "ducktv.sk@hd": "ducktvhd.sk",
    }

    override = identity_overrides.get(value.casefold())
    if override:
        return override

    value = TVG_VARIANT_SUFFIX_RE.sub("", value)
    return value.casefold()

def canonical_stream_url(url: str) -> str:
    """
    Return a normalized URL used only for stream identity comparisons.

    The original URL must still be preserved for playlist output, reports,
    audits, and playback.

    Safe normalizations:
      - trim surrounding whitespace
      - lowercase scheme
      - lowercase hostname
      - remove default HTTPS port :443
      - remove default HTTP port :80
      - remove URL fragment
      - normalize an empty path to /
      - preserve path case
      - preserve query string exactly
      - preserve non-default ports
    """
    value = (url or "").strip()
    if not value:
        return ""

    parsed = urlparse(value)
    scheme = parsed.scheme.lower()

    # Leave malformed/non-absolute values alone. Validation elsewhere decides
    # whether they are acceptable.
    if not scheme or not parsed.netloc or parsed.hostname is None:
        return value

    hostname = parsed.hostname.lower()

    # urlparse() removes IPv6 brackets from .hostname, so restore them when
    # rebuilding the network location.
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"

    # Preserve user:password@ exactly if a stream URL ever contains it.
    userinfo = ""
    if "@" in parsed.netloc:
        userinfo = parsed.netloc.rsplit("@", 1)[0] + "@"

    try:
        port = parsed.port
    except ValueError:
        # Malformed ports are handled by validation elsewhere.
        return value

    if (scheme == "https" and port == 443) or (
        scheme == "http" and port == 80
    ):
        port = None

    netloc = f"{userinfo}{hostname}"

    if port is not None:
        netloc += f":{port}"

    path = parsed.path or "/"

    return urlunparse((
        scheme,
        netloc,
        path,
        parsed.params,
        parsed.query,
        "",
    ))

def apply_canonical_identity(
    entry: dict,
    override: dict,
) -> None:
    """Apply canonical channel metadata after identity resolution.

    Selector matching lives in identity_overrides.py. This function only
    applies the already-resolved channel identity to parsed feed metadata.
    Feed URL/source provenance and audit state remain separate.
    """
    if not isinstance(override, dict):
        return

    channel_name = ""

    if "channel_name" in override:
        channel_name = str(
            override.get("channel_name") or ""
        ).strip()

        if channel_name:
            entry["display_name"] = channel_name
            entry["channel_name"] = channel_name

    if "tvg_name" in override:
        entry["tvg_name"] = str(
            override.get("tvg_name") or ""
        ).strip()

    if "tvg_id" in override:
        entry["tvg_id"] = str(
            override.get("tvg_id") or ""
        ).strip()

    updated_lines = list(
        entry.get("lines") or []
    )

    for i, line in enumerate(updated_lines):
        if not line.strip().startswith("#EXTINF:"):
            continue

        metadata, old_display_name = split_extinf(line)

        def set_attribute(
            metadata_value: str,
            attribute: str,
            value: str,
        ) -> str:
            pattern = (
                rf'\s+{re.escape(attribute)}="[^"]*"'
            )

            if value == "":
                return re.sub(
                    pattern,
                    "",
                    metadata_value,
                    count=1,
                    flags=re.IGNORECASE,
                )

            safe_value = value.replace(
                '"',
                "'",
            )

            replacement = (
                f' {attribute}="{safe_value}"'
            )

            if re.search(
                pattern,
                metadata_value,
                flags=re.IGNORECASE,
            ):
                return re.sub(
                    pattern,
                    replacement,
                    metadata_value,
                    count=1,
                    flags=re.IGNORECASE,
                )

            return metadata_value + replacement

        if "tvg_id" in override:
            metadata = set_attribute(
                metadata,
                "tvg-id",
                str(
                    override.get("tvg_id")
                    or ""
                ).strip(),
            )

        if "tvg_name" in override:
            metadata = set_attribute(
                metadata,
                "tvg-name",
                str(
                    override.get("tvg_name")
                    or ""
                ).strip(),
            )

        display_name = (
            channel_name
            or old_display_name
        )

        updated_lines[i] = (
            f"{metadata},{display_name}"
        )

        break

    entry["lines"] = updated_lines

def channel_key(entry: dict) -> str:
    """
    Identify a logical channel.

    Priority:
      1. explicit canonical channel ID from the identity layer
      2. tvg-id, with @SD/@HD-style variants collapsed
      3. tvg-name
      4. cleaned display name
    """
    canonical_id = str(entry.get("canonical_id") or "").strip().casefold()
    if canonical_id:
        return f"canonical:{canonical_id}"

    tvg_id = normalized_tvg_id(entry.get("tvg_id", ""))
    if tvg_id:
        return f"id:{tvg_id}"

    tvg_name = normalize_text(
        strip_internal_candidate_annotations(
            entry.get("tvg_name", "")
        )
    )
    if tvg_name:
        return f"name:{tvg_name}"

    display_name = strip_internal_candidate_annotations(
        entry.get("display_name", "")
    )
    return f"name:{normalize_text(strip_display_annotations(display_name))}"

def strip_custom_prefix(name: str) -> str:
    return CUSTOM_PREFIX_RE.sub("", (name or "").strip()).strip()
