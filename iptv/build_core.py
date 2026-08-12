#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
import json
import re
import sys
import unicodedata
from urllib.parse import urlparse, urlunparse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
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

ATTR_RE = re.compile(r'([A-Za-z0-9_-]+)="([^"]*)"')
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
SOURCE_FLAG_RE = re.compile(r'\[(Geo[- ]?blocked|Not\s*24/7|Offline)\]', re.IGNORECASE)
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


def http_get_text(url: str, timeout: int = 45) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Tomas-IPTV-Playlist-Builder/2.0",
            "Accept": "*/*",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read()
    return data.decode("utf-8-sig", errors="replace")


def download_m3u(url: str) -> str:
    text = http_get_text(url)
    if "#EXTM3U" not in text[:1000]:
        raise RuntimeError(f"Source did not look like an M3U playlist: {url}")
    return text

def playlist_header(cfg: dict) -> str:
    """
    Build the #EXTM3U header.

    When EPG is enabled, advertise the public XMLTV guide URL using both
    commonly understood M3U header attribute names.
    """
    header = "#EXTM3U"

    epg = cfg.get("epg") or {}

    if not isinstance(epg, dict):
        return header

    if not bool(epg.get("enabled")):
        return header

    public_url = str(
        epg.get("public_url") or ""
    ).strip()

    if not public_url:
        return header

    safe_url = public_url.replace(
        '"',
        "%22",
    )

    return (
        f'{header} '
        f'url-tvg="{safe_url}" '
        f'x-tvg-url="{safe_url}"'
    )
	
def read_local(path: str) -> str:
    p = ROOT / path
    if not p.is_file():
        raise RuntimeError(f"Required local source {path} not found")
    return p.read_text(encoding="utf-8-sig")


def split_extinf(line: str) -> tuple[str, str]:
    """Split an #EXTINF line at the first comma outside double quotes."""
    in_quotes = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == "," and not in_quotes:
            return line[:i], line[i + 1 :].strip()
    return line, ""


def parse_entries(text: str) -> list[dict]:
    """Parse M3U entries while preserving their original lines."""
    entries: list[dict] = []
    current: dict | None = None

    for raw in text.splitlines():
        raw = raw.rstrip("\r")
        line = raw.strip()

        if not line or line.startswith("#EXTM3U"):
            continue

        if line.startswith("#EXTINF:"):
            if current and current.get("url"):
                entries.append(current)

            metadata_part, display_name = split_extinf(line)
            attrs = {k.lower(): v for k, v in ATTR_RE.findall(metadata_part)}
            current = {
                "lines": [raw],
                "url": None,
                "display_name": display_name or attrs.get("tvg-name", "") or "Unnamed channel",
                "tvg_id": attrs.get("tvg-id", ""),
                "tvg_name": attrs.get("tvg-name", ""),
                "logo": attrs.get("tvg-logo", ""),
                "group_title": attrs.get("group-title", ""),
                "canonical_id": attrs.get("canonical-id", ""),
                "country_code": attrs.get("country-code", ""),
                "language_codes": attrs.get("language-codes", ""),
            }
            continue

        if current is None:
            continue

        current["lines"].append(raw)

        if not line.startswith("#"):
            current["url"] = line
            entries.append(current)
            current = None

    if current and current.get("url"):
        entries.append(current)

    return entries


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


def strip_custom_prefix(name: str) -> str:
    return CUSTOM_PREFIX_RE.sub("", (name or "").strip()).strip()

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

VALID_SOURCE_KINDS = {
    "base",
    "alternatives",
    "extras",
    "source",
}


def normalize_source_kind(
    value: str,
    default: str = "source",
) -> str:
    """
    Normalize and validate a source kind.

    Supported canonical kinds:
      base
      alternatives
      extras
      source

    Singular aliases are accepted for convenience:
      alternative -> alternatives
      extra       -> extras
    """
    raw = str(
        value or default
    ).strip().casefold()

    raw = (
        raw
        .replace("-", "_")
        .replace(" ", "_")
    )

    aliases = {
        "base": "base",

        "alternative": "alternatives",
        "alternatives": "alternatives",

        "extra": "extras",
        "extras": "extras",

        "source": "source",
    }

    normalized = aliases.get(raw)

    if not normalized:
        allowed = ", ".join(
            sorted(VALID_SOURCE_KINDS)
        )

        raise RuntimeError(
            f"Unsupported source kind {value!r}. "
            f"Allowed kinds: {allowed}."
        )

    return normalized

def source_spec(
    item,
    default_name: str,
    kind: str,
) -> dict:
    """
    Accept both old plain-string config entries and source objects.

    Source kind is normalized here so the rest of the builder can safely
    rely on one of:
      base
      alternatives
      extras
      source
    """
    default_kind = normalize_source_kind(
        kind
    )

    if isinstance(item, str):
        key = (
            "url"
            if item.startswith(
                ("http://", "https://")
            )
            else "path"
        )

        return {
            "name": default_name,
            "kind": default_kind,
            key: item,
        }

    if isinstance(item, dict):
        result = dict(item)

        result.setdefault(
            "name",
            default_name,
        )

        result["kind"] = (
            normalize_source_kind(
                result.get("kind"),
                default=default_kind,
            )
        )

        return result

    raise TypeError(
        f"Unsupported source definition: "
        f"{item!r}"
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


def safe_csv_value(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ").strip()


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: safe_csv_value(str(row.get(k, ""))) for k in fieldnames})



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


def normalize_test_status(value: str) -> str:
    raw = (value or "").strip()
    value = raw.casefold().replace(" ", "_")

    canonical = {
        "works", "works_with_warning", "loads", "mrl_error",
        "format_error", "generic_error", "wrong_language",
        "not_tested", "needs_review"
    }
    if value in canonical:
        return value

    aliases = {
        "ok": "works",
        "working": "works",
        "pass": "works",
        "passed": "works",
        "yes": "works",
        "just_loads": "loads",
        "pending": "not_tested",
        "untested": "not_tested",
        "not-tested": "not_tested",
        "": "not_tested",
    }
    if value in aliases:
        return aliases[value]

    lower = raw.casefold()
    if "unable to open the mrl" in lower:
        return "mrl_error"
    if "player_error_not_supported_file" in lower:
        return "format_error"
    if "player_error_generic" in lower:
        return "generic_error"
    if "certificate" in lower and ("work" in lower or "play" in lower or "ok" in lower):
        return "works_with_warning"
    if "just loads" in lower:
        return "loads"
    if lower.startswith("ok"):
        return "works"

    return "needs_review"

def is_tested_status(value: str) -> bool:
    """
    Return True when a device has an actual recorded test result.

    Any normalized status except 'not_tested' means the stream was tested,
    even if playback failed, kept loading, had a warning, used the wrong
    language, or still needs review.
    """
    return normalize_test_status(value) != "not_tested"

LANGUAGE_NAME_TO_CODE = {
    "hungarian": "HU",
    "magyar": "HU",
    "hun": "HU",

    "slovak": "SK",
    "slovakian": "SK",
    "slk": "SK",
    "slo": "SK",

    "czech": "CZ",
    "ces": "CZ",
    "cze": "CZ",

    "serbian": "SR",
    "serb": "SR",

    "english": "EN",
    "german": "DE",
    "russian": "RU",
    "romanian": "RO",
    "croatian": "HR",
    "slovenian": "SL",
    "ukrainian": "UK",
    "polish": "PL",
}


def normalize_language_code(value: str) -> str:
    """
    Normalize one project language code.

    Tomas IPTV currently uses the familiar uppercase HU/SK/CZ-style codes.
    Legacy language names such as 'Hungarian' and 'Czech' are accepted for
    backwards compatibility.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""

    name_key = " ".join(
        raw.casefold()
        .replace("_", " ")
        .replace("-", " ")
        .split()
    )

    if name_key in LANGUAGE_NAME_TO_CODE:
        return LANGUAGE_NAME_TO_CODE[name_key]

    upper = raw.upper()

    if re.fullmatch(r"[A-Z]{2,3}", upper):
        return upper

    return ""


def logical_channel_key(entry: dict) -> str:
    """Identify one logical channel inside one publication country."""
    country_code = (
        normalize_country_code(
            str(entry.get("country_code") or entry.get("language_code") or "")
        )
        or "UNKNOWN"
    )
    raw_key = str(entry.get("channel_key") or channel_key(entry))
    prefix = f"{country_code}:"
    if raw_key.startswith(prefix):
        return raw_key
    return f"{prefix}{raw_key}"

def normalize_language_codes(value) -> list[str]:
    """Normalize legacy audit-language values while preserving their API."""
    if value is None:
        return []
    if isinstance(value, str):
        values = [
            part.strip()
            for part in re.split(r"[,;/+]", value)
            if part.strip()
        ]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]
    result: list[str] = []
    for raw in values:
        code = normalize_language_code(str(raw or ""))
        if code and code not in result:
            result.append(code)
    return result

def normalize_language_match(value: str) -> str:
    """
    Normalize the four supported language-match states.

    yes          = observed language matches the expected playlist language
    no           = observed language does not match
    unknown      = language has not been confirmed
    multilingual = expected language is present together with other languages
    """
    token = (
        str(value or "")
        .strip()
        .casefold()
        .replace("-", "_")
        .replace(" ", "_")
    )

    aliases = {
        "yes": "yes",
        "match": "yes",
        "matches": "yes",
        "matching": "yes",
        "ok": "yes",
        "true": "yes",

        "no": "no",
        "mismatch": "no",
        "wrong": "no",
        "wrong_language": "no",
        "false": "no",

        "unknown": "unknown",
        "not_tested": "unknown",
        "untested": "unknown",
        "pending": "unknown",

        "multilingual": "multilingual",
        "multi": "multilingual",
        "multiple": "multilingual",
    }

    return aliases.get(token, "")


def legacy_language_is_negative(value: str) -> bool:
    """
    Recognize old generic negative language descriptions without mentioning
    any particular country.

    Examples:
      wrong
      wrong language
      not hungarian
      not slovak
      non-hungarian
      non-czech
    """
    token = " ".join(
        str(value or "")
        .strip()
        .casefold()
        .replace("_", " ")
        .replace("-", " ")
        .split()
    )

    if token in {
        "wrong",
        "wrong language",
        "mismatch",
        "language mismatch",
        "non matching",
        "non matching language",
    }:
        return True

    if token.startswith("not "):
        return True

    if token.startswith("non "):
        return True

    return False


def derive_language_match(
    expected_codes: list[str],
    observed_codes: list[str],
) -> str:
    """
    Derive language_match from expected and observed languages.
    """
    if not expected_codes or not observed_codes:
        return "unknown"

    expected = set(normalize_spoken_language_codes(expected_codes))
    observed = set(normalize_spoken_language_codes(observed_codes))

    if not expected.intersection(observed):
        return "no"

    if len(observed_codes) > 1:
        return "multilingual"

    return "yes"


def resolve_language_info(
    item: dict,
    default_expected=None,
) -> tuple[list[str], list[str], str]:
    """
    Resolve the new language model while remaining compatible with the old
    audit.json language/language_code fields.
    """
    expected_codes = normalize_language_codes(
        item.get("expected_language_codes")
    )

    if not expected_codes:
        expected_codes = normalize_language_codes(
            default_expected
        )

    observed_codes = normalize_language_codes(
        item.get("observed_language_codes")
    )

    legacy_language = str(
        item.get("language") or ""
    ).strip()

    # Old audit rows usually store the observed language as a human-readable
    # name such as "Hungarian", "German" or "Czech".
    if (
        not observed_codes
        and legacy_language
        and legacy_language.casefold() not in {
            "unknown",
            "untested",
            "not tested",
            "not_tested",
        }
        and not legacy_language_is_negative(legacy_language)
    ):
        observed_codes = normalize_language_codes(
            legacy_language
        )

        # Some legacy rows use language_code for the observed language.
        if not observed_codes:
            legacy_code = normalize_language_code(
                str(item.get("language_code") or "")
            )

            if legacy_code:
                observed_codes = [legacy_code]

    raw_match = str(
        item.get("language_match") or ""
    ).strip()

    if raw_match:
        explicit_match = normalize_language_match(
            raw_match
        )

        if explicit_match:
            return (
                expected_codes,
                observed_codes,
                explicit_match,
            )

    # Backwards compatibility with old audit rows.
    if (
        legacy_language_is_negative(legacy_language)
        or normalize_test_status(
            str(item.get("vlc") or "")
        ) == "wrong_language"
        or normalize_test_status(
            str(item.get("samsung") or "")
        ) == "wrong_language"
    ):
        return expected_codes, observed_codes, "no"

    return (
        expected_codes,
        observed_codes,
        derive_language_match(
            expected_codes,
            observed_codes,
        ),
    )


def format_language_codes(codes) -> str:
    normalized = normalize_language_codes(codes)

    if not normalized:
        return "Unknown"

    return ", ".join(normalized)


def language_mismatch_reason(
    expected_codes: list[str],
    observed_codes: list[str],
) -> str:
    if expected_codes and observed_codes:
        return (
            "Observed language(s) "
            f"{format_language_codes(observed_codes)} "
            "do not match expected language(s) "
            f"{format_language_codes(expected_codes)}."
        )

    if observed_codes:
        return (
            "Observed language(s) "
            f"{format_language_codes(observed_codes)} "
            "were marked as not matching this playlist."
        )

    return (
        "Observed language does not match the expected "
        "playlist language."
    )
	
def configured_playlist_country_codes(cfg: dict) -> list[str]:
    """Return publication-country codes enabled by country_outputs."""
    return configured_country_codes(cfg)


def configured_playlist_language_codes(cfg: dict) -> list[str]:
    """Legacy API alias for the old country-as-language configuration."""
    return configured_playlist_country_codes(cfg)


def configured_spoken_language_codes(cfg: dict) -> list[str]:
    """Return supported spoken languages independently of country outputs."""
    return configured_language_codes(cfg)

def audit_playlist_country_code(item: dict) -> str:
    """Return the country bucket to which a saved audit identity belongs."""
    for field in ("playlist_country_code", "playlist_language_code", "country_code"):
        code = normalize_country_code(str(item.get(field) or ""))
        if code:
            return code

    # Compatibility for old rows whose only scope hint was ["HU"]/["SK"]/["CZ"].
    raw_expected = item.get("expected_language_codes")
    if isinstance(raw_expected, list) and len(raw_expected) == 1:
        legacy = legacy_country_scope_from_language_token(raw_expected[0])
        if legacy:
            return legacy
    return ""


def audit_playlist_scope_code(item: dict) -> str:
    """Legacy compatibility alias."""
    return audit_playlist_country_code(item)

def verified_output_country_code(
    audit_row: dict,
    source_country_code: str,
    cfg: dict,
) -> str:
    """Choose publication country without assuming language and country are equivalent."""
    source_code = normalize_country_code(source_country_code) or "HU"
    configured = set(configured_playlist_country_codes(cfg))

    explicit = normalize_country_code(
        str(audit_row.get("output_country_code") or audit_row.get("output_language_code") or "")
    )
    if explicit and (not configured or explicit in configured):
        return explicit

    decision = str(audit_row.get("decision") or "").strip()
    if decision not in {"Verified", "TV verified"}:
        return source_code

    if "verified_country_routes" not in cfg:
        return verified_output_language_code(
            audit_row,
            source_code,
            configured_playlist_country_codes(cfg),
        )

    routed = verified_country_route(
        cfg,
        source_code,
        audit_row.get("observed_language_codes"),
    )
    if routed and (not configured or routed in configured):
        return routed
    return source_code


def verified_output_language_code(
    audit_row: dict,
    source_language_code: str,
    supported_language_codes=None,
) -> str:
    """Legacy helper preserving old HU/SK/CZ one-to-one behavior for callers/tests."""
    source_code = normalize_country_code(source_language_code) or "HU"
    decision = str(audit_row.get("decision") or "").strip()
    if decision not in {"Verified", "TV verified"}:
        return source_code
    observed = normalize_spoken_language_codes(audit_row.get("observed_language_codes"))
    if len(observed) != 1:
        return source_code
    destination_by_language = {"hun": "HU", "slk": "SK", "ces": "CZ"}
    destination = destination_by_language.get(observed[0], "")
    supported_countries = {
        normalize_country_code(str(value or ""))
        for value in (supported_language_codes or [])
    }
    if destination and destination in supported_countries:
        return destination
    return source_code

def language_acceptance_state(
    item: dict,
    supported_language_codes=None,
) -> str:
    """
    Separate spoken-language acceptance from playlist placement.

    match                    expected spoken language is present
    supported_cross_language observed language differs, but is one of the
                             currently published HU/SK/CZ-style languages
    unsupported              observed language is outside current support
    unknown                  language has not been confirmed
    """
    (
        expected_codes,
        observed_codes,
        language_match,
    ) = resolve_language_info(item)

    supported = normalize_spoken_language_codes(
        supported_language_codes
    )
    observed_supported = normalize_spoken_language_codes(observed_codes)

    if language_match in {
        "yes",
        "multilingual",
    }:
        return "match"

    if language_match == "no":
        if (
            observed_codes
            and supported
            and set(observed_supported).intersection(
                supported
            )
        ):
            return "supported_cross_language"

        return "unsupported"

    return "unknown"


def calculate_audit_decision(
    item: dict,
    supported_language_codes=None,
) -> tuple[str, str]:
    """
    Playback/device status for our playlist, not a legal certification.

    Audit/source identity, spoken-language acceptance, and publication
    country are intentionally separate. A technically working stream can be
    Verified when its observed spoken language is supported. Publication
    country changes only through an explicit output country or configured
    country-routing rule.

    Unsupported observed languages still reject the stream.
    """
    explicit = (
        item.get("decision") or "auto"
    ).strip().casefold().replace(" ", "_")

    if explicit in {
        "verified",
        "tv_verified",
        "pc_only",
        "needs_review",
        "rejected",
    }:
        label = {
            "verified": "Verified",
            "tv_verified": "TV verified",
            "pc_only": "PC only",
            "needs_review": "Needs review",
            "rejected": "Rejected",
        }[explicit]

        return (
            label,
            str(item.get("reason") or "").strip(),
        )

    if audit_excluded(item):
        return (
            "Rejected",
            str(
                item.get("reason")
                or "Excluded from this playlist."
            ).strip(),
        )

    vlc = normalize_test_status(
        str(item.get("vlc", ""))
    )

    samsung = normalize_test_status(
        str(item.get("samsung", ""))
    )

    (
        expected_codes,
        observed_codes,
        language_match,
    ) = resolve_language_info(item)

    acceptance = language_acceptance_state(
        item,
        supported_language_codes,
    )

    if acceptance == "unsupported":
        return (
            "Rejected",
            language_mismatch_reason(
                expected_codes,
                observed_codes,
            ),
        )

    cross_language_supported = (
        acceptance
        == "supported_cross_language"
    )

    # Old manual tests used wrong_language to mean "the stream played, but
    # the speech was not the old expected language". Once that observed
    # language is supported, the same result is technically a successful
    # playback test.
    pc_good = (
        vlc in {
            "works",
            "works_with_warning",
        }
        or (
            cross_language_supported
            and vlc == "wrong_language"
        )
    )

    tv_good = (
        samsung == "works"
        or (
            cross_language_supported
            and samsung == "wrong_language"
        )
    )

    if pc_good and tv_good:
        if cross_language_supported:
            return (
                "Verified",
                (
                    "Works on both tested devices. "
                    f"Observed language(s) "
                    f"{format_language_codes(observed_codes)} "
                    "are currently supported. Publication country "
                    "is determined separately by explicit country-routing "
                    "policy."
                ),
            )

        return "Verified", ""

    if tv_good and not pc_good:
        return (
            "TV verified",
            "Works on Samsung; VLC needs another look.",
        )

    if (
        pc_good
        and samsung in {
            "format_error",
            "generic_error",
            "loads",
        }
    ):
        return (
            "PC only",
            "Works in VLC but not on Samsung in the current test.",
        )

    return (
        "Needs review",
        str(item.get("reason") or "").strip(),
    )

def infer_protocol(url: str) -> str:
    value = (url or "").strip().lower()
    if value.startswith("rtmp://"):
        return "RTMP"
    if ".m3u8" in value:
        return "HLS"
    if value.startswith("https://"):
        return "HTTPS"
    if value.startswith("http://"):
        return "HTTP"
    return ""

def canonical_audit_name(value: str) -> str:
    return normalize_text(strip_display_annotations(value or ""))


def normalize_audit_decision_token(value: str) -> str:
    token = (value or "auto").strip().casefold().replace("-", "_").replace(" ", "_")
    return token or "auto"


def audit_status_is_recognized(value: str) -> bool:
    raw = (value or "").strip()
    if not raw:
        return True

    token = raw.casefold().replace(" ", "_")
    normalized = normalize_test_status(raw)

    if normalized != "needs_review":
        return True

    return token == "needs_review"


def audit_excluded(item: dict) -> bool:
    """Return True only for the literal JSON boolean true."""
    return item.get("exclude_from_playlist") is True


def exact_url_audit_matches_entry(
    audit_item: dict,
    entry: dict,
) -> bool:
    """Guard exact-URL audit history by source country, not spoken language."""
    audit_scope = audit_playlist_country_code(audit_item)
    if not audit_scope:
        return True
    entry_scope = normalize_country_code(
        str(entry.get("country_code") or entry.get("language_code") or "")
    )
    if not entry_scope:
        return True
    return audit_scope == entry_scope

def validate_audit_items(
    audit_items: list[dict],
    final_entries: list[dict],
    strict: bool = False,
) -> tuple[list[str], list[str]]:
    """
    Validate audit.json before it can affect playlist selection.

    Returns:
      1. all non-fatal audit warnings
      2. warnings specifically caused by ambiguous legacy channel-level audits

    In normal mode, a legacy channel-level audit that now matches multiple
    current feeds is treated as non-fatal. Its old result must not be applied
    to any of those feeds.

    In strict mode, the same ambiguity is a fatal validation error.

    All genuinely malformed or contradictory audit data remains fatal in
    both modes.
    """
    errors: list[str] = []
    warnings: list[str] = []
    ambiguity_warnings: list[str] = []
	
    allowed_decisions = {
        "auto",
        "verified",
        "tv_verified",
        "pc_only",
        "needs_review",
        "rejected",
    }

    current_by_tvg: dict[str, set[str]] = {}
    current_by_name: dict[str, set[str]] = {}

    current_expected_by_url: dict[str, set[str]] = {}
    current_expected_by_tvg: dict[str, set[str]] = {}
    current_expected_by_name: dict[str, set[str]] = {}
    current_country_by_url: dict[str, set[str]] = {}

    for entry in final_entries:
        url = str(
            entry.get("url") or ""
        ).strip()

        if not url:
            continue

        url_key = canonical_stream_url(url)

        expected_codes = normalize_language_codes(
            entry.get("expected_language_codes")
            or entry.get("language_codes")
            or entry.get("language_code")
        )
        entry_country = normalize_country_code(
            str(entry.get("country_code") or entry.get("language_code") or "")
        )
        if entry_country:
            current_country_by_url.setdefault(url_key, set()).add(entry_country)

        if expected_codes:
            current_expected_by_url.setdefault(
                url_key,
                set(),
            ).update(expected_codes)

        tid = normalized_tvg_id(
            str(entry.get("tvg_id") or "")
        )

        if tid:
            current_by_tvg.setdefault(
                tid,
                set(),
            ).add(url_key)

            if expected_codes:
                current_expected_by_tvg.setdefault(
                    tid,
                    set(),
                ).update(expected_codes)

        for value in (
            entry.get("channel_name"),
            entry.get("display_name"),
            entry.get("tvg_name"),
        ):
            cname = canonical_audit_name(
                str(value or "")
            )

            if not cname:
                continue

            current_by_name.setdefault(
                cname,
                set(),
            ).add(url_key)

            if expected_codes:
                current_expected_by_name.setdefault(
                    cname,
                    set(),
                ).update(expected_codes)

    seen_urls: dict[str, int] = {}
    seen_legacy_keys: dict[tuple[str, str], int] = {}

    for index, raw in enumerate(audit_items, start=1):
        item = dict(raw)
        channel = str(item.get("channel") or item.get("channel_name") or "").strip()
        label = f"audit item #{index}"
        if channel:
            label += f" ({channel})"

        if not channel:
            errors.append(f"{label}: missing channel name.")

        url = str(
            item.get("stream_url") or ""
        ).strip()

        url_key = (
            canonical_stream_url(url)
            if url
            else ""
        )

        tid = normalized_tvg_id(
            str(item.get("tvg_id") or "")
        )

        cname = canonical_audit_name(
            channel
        )

        if url:

            if any(ch.isspace() for ch in url):
                errors.append(
                    f"{label}: malformed stream_url contains whitespace: {url!r}."
                )
            else:
                parsed = urlparse(url)
                if not parsed.scheme or not parsed.netloc:
                    errors.append(f"{label}: malformed stream_url: {url!r}.")

            if url_key in seen_urls:
                first = seen_urls[url_key]
                errors.append(
                    f"{label}: duplicate stream_url {url!r}; "
                    f"already used by audit item #{first}."
                )
            else:
                seen_urls[url_key] = index

        for field in (
            "expected_language_codes",
            "observed_language_codes",
        ):
            if field not in item:
                continue

            raw_codes = item.get(field)

            if raw_codes is None:
                continue

            if not isinstance(raw_codes, list):
                errors.append(
                    f"{label}: {field} must be a JSON list "
                    f"such as [\"HU\"] or [\"HU\", \"SR\"]."
                )
                continue

            for raw_code in raw_codes:
                if (
                    not isinstance(raw_code, str)
                    or not re.fullmatch(
                        r"[A-Za-z]{2,3}",
                        raw_code.strip(),
                    )
                ):
                    errors.append(
                        f"{label}: invalid language code "
                        f"{raw_code!r} in {field}. "
                        "Use 2-3 letter codes such as "
                        "HU, SK, CZ, SR or EN."
                    )

        raw_language_match = str(
            item.get("language_match") or ""
        ).strip()

        if (
            raw_language_match
            and not normalize_language_match(
                raw_language_match
            )
        ):
            errors.append(
                f"{label}: invalid language_match "
                f"{raw_language_match!r}. "
                "Allowed values: yes, no, unknown, "
                "multilingual."
            )
			
        for field in ("vlc", "samsung"):
            raw_status = str(item.get(field) or "")
            if not audit_status_is_recognized(raw_status):
                errors.append(
                    f"{label}: invalid {field} status {raw_status!r}. "
                    "Use a supported canonical status or recognized legacy value."
                )

        decision_token = normalize_audit_decision_token(str(item.get("decision") or "auto"))
        if decision_token not in allowed_decisions:
            errors.append(
                f"{label}: invalid decision {item.get('decision')!r}. "
                f"Allowed values: {', '.join(sorted(allowed_decisions))}."
            )

        if (
            "exclude_from_playlist" in item
            and not isinstance(
                item.get("exclude_from_playlist"),
                bool,
            )
        ):
            errors.append(
                f"{label}: exclude_from_playlist must be true or false."
            )

        exclude = audit_excluded(item)
        if exclude and decision_token in {"verified", "tv_verified", "pc_only"}:
            errors.append(
                f"{label}: exclude_from_playlist=true conflicts with "
                f"decision {item.get('decision')!r}."
            )

        vlc = normalize_test_status(
            str(item.get("vlc") or "")
        )

        samsung = normalize_test_status(
            str(item.get("samsung") or "")
        )

        expected_for_validation = (
            normalize_language_codes(
                item.get("expected_language_codes")
            )
        )

        current_url_countries = (
            sorted(current_country_by_url.get(url_key, set()))
            if url_key else []
        )

        saved_playlist_scope = (
            audit_playlist_scope_code(
                item
            )
        )

        if (
            url_key
            and saved_playlist_scope
            and current_url_countries
            and saved_playlist_scope
            not in current_url_countries
        ):
            warnings.append(
                f"{label}: exact stream URL is currently scoped to "
                f"{', '.join(current_url_countries)}, but the saved audit "
                f"belongs to {saved_playlist_scope} playlist scope. "
                "The saved result will be kept as historical evidence and "
                "will not be applied to this current entry."
            )

        # If the audit does not explicitly say what language was expected,
        # derive it from the current source/playlist entry.
        if not expected_for_validation:
            if url_key:
                expected_for_validation = sorted(
                    current_expected_by_url.get(
                        url_key,
                        set(),
                    )
                )
            elif tid:
                expected_for_validation = sorted(
                    current_expected_by_tvg.get(
                        tid,
                        set(),
                    )
                )
            elif cname:
                expected_for_validation = sorted(
                    current_expected_by_name.get(
                        cname,
                        set(),
                    )
                )

        language_probe = dict(item)

        language_probe[
            "expected_language_codes"
        ] = expected_for_validation

        (
            resolved_expected,
            resolved_observed,
            resolved_match,
        ) = resolve_language_info(
            language_probe
        )

        # If both language lists are present, an explicitly supplied
        # language_match must agree with them.
        if (
            raw_language_match
            and resolved_expected
            and resolved_observed
        ):
            explicit_match = normalize_language_match(
                raw_language_match
            )

            derived_match = derive_language_match(
                resolved_expected,
                resolved_observed,
            )

            if (
                explicit_match
                and explicit_match != derived_match
            ):
                errors.append(
                    f"{label}: language_match "
                    f"{raw_language_match!r} contradicts "
                    "expected/observed language codes "
                    f"(expected={resolved_expected}, "
                    f"observed={resolved_observed}, "
                    f"derived={derived_match})."
                )

        auto_item = dict(language_probe)
        auto_item["decision"] = "auto"
        auto_item["exclude_from_playlist"] = False

        automatic_decision, _ = (
            calculate_audit_decision(
                auto_item
            )
        )

        if decision_token == "verified" and automatic_decision != "Verified":
            errors.append(
                f"{label}: decision Verified contradicts playback/language results "
                f"(VLC={vlc}, Samsung={samsung}, auto={automatic_decision})."
            )

        if decision_token == "tv_verified" and samsung != "works":
            errors.append(
                f"{label}: decision TV verified requires Samsung=works; "
                f"got {samsung}."
            )

        if decision_token == "pc_only" and automatic_decision != "PC only":
            errors.append(
                f"{label}: decision PC only contradicts playback results "
                f"(VLC={vlc}, Samsung={samsung}, auto={automatic_decision})."
            )

        if not url:
            if tid:
                legacy_key = ("tvg", tid)
                matching_urls = current_by_tvg.get(tid, set())
            else:
                legacy_key = ("name", cname)
                matching_urls = current_by_name.get(cname, set())

            if legacy_key[1]:
                if legacy_key in seen_legacy_keys:
                    first = seen_legacy_keys[legacy_key]
                    errors.append(
                        f"{label}: duplicate channel-level audit key "
                        f"{legacy_key[0]}={legacy_key[1]!r}; "
                        f"already used by audit item #{first}."
                    )
                else:
                    seen_legacy_keys[legacy_key] = index

            if len(matching_urls) > 1:
                candidates = ", ".join(sorted(matching_urls))
                message = (
                    f"{label}: Legacy verification for "
                    f"{channel or 'this channel'} became ambiguous after "
                    f"{len(matching_urls)} feeds were discovered. "
                    f"The saved channel-level result was not applied to any "
                    f"current feed. Re-test individual streams. "
                    f"Candidate URLs: {candidates}"
                )

                if strict:
                    errors.append(message)
                else:
                    warnings.append(message)
                    ambiguity_warnings.append(message)
            elif len(matching_urls) == 1:
                only_url = next(iter(matching_urls))
                warnings.append(
                    f"{label}: legacy channel-level audit still matches one current "
                    f"feed ({only_url}). Add stream_url when this row is next edited."
                )

    if errors:
        details = "\n".join(f"  - {message}" for message in errors)
        raise RuntimeError(f"audit.json validation failed:\n{details}")

    return warnings, ambiguity_warnings
	
def audit_match_key(item: dict) -> tuple[str, str]:
    url = str(item.get("stream_url") or item.get("url") or "").strip()
    if url:
        return ("url", canonical_stream_url(url))

    tvg_id = normalized_tvg_id(str(item.get("tvg_id") or ""))
    if tvg_id:
        return ("tvg_id", tvg_id)

    name = normalize_text(str(item.get("channel") or item.get("channel_name") or ""))
    return ("name", name)


def prepare_audit_rows(
    audit_items: list[dict],
    final_entries: list[dict],
    supported_language_codes=None,
    cfg: dict | None = None,
) -> list[dict]:
    """
    Create one audit row PER STREAM URL.

    Important behavior:
    - If a channel has multiple stream URLs, each one gets Feed 1/2,
      Feed 2/2, etc.
    - A saved audit result with an exact stream_url applies only to that stream.
    - Older channel-level audit results without stream_url apply only when the
      current channel has exactly one feed.
    - If a legacy channel-level audit now matches multiple feeds, its saved
      result is not applied to any current feed.
    - Ambiguous legacy results are preserved as historical audit rows.
    """
    # Assign stable feed numbers in current source order.
    counts: dict[str, int] = {}
    for entry in final_entries:
        key = logical_channel_key(entry)
        counts[key] = counts.get(key, 0) + 1

    seen_feed: dict[str, int] = {}
    for entry in final_entries:
        key = logical_channel_key(entry)
        seen_feed[key] = seen_feed.get(key, 0) + 1
        entry["variant_index"] = seen_feed[key]
        entry["variant_count"] = counts[key]

    manual_by_url: dict[str, dict] = {}
    manual_by_tvg_id: dict[str, dict] = {}
    manual_by_name: dict[str, dict] = {}

    for raw in audit_items:
        item = dict(raw)
        url = str(item.get("stream_url") or "").strip()
        tvg_id = normalized_tvg_id(str(item.get("tvg_id") or ""))
        name = canonical_audit_name(str(item.get("channel") or ""))

        if url:
            manual_by_url[canonical_stream_url(url)] = item
        if tvg_id and not url:
            manual_by_tvg_id[tvg_id] = item
        if name and not url:
            manual_by_name[name] = item

    used_manual_keys: set[tuple[str, str]] = set()
    rows: list[dict] = []

    for entry in final_entries:
        url = str(entry.get("url") or "").strip()
        url_key = canonical_stream_url(url)
        tvg_id = str(entry.get("tvg_id") or "").strip()
        clean_name = str(
            entry.get("channel_name")
            or entry.get("display_name")
            or "Unnamed channel"
        ).strip()
        feed_index = int(entry.get("variant_index") or 1)
        feed_count = int(entry.get("variant_count") or 1)

        manual = None
        manual_key = None

        # URL-specific audit is authoritative only when any explicitly
        # recorded expected language/country is compatible with this current
        # entry. Canonically equivalent URL spellings still identify the same
        # stream inside that identity scope.
        if url_key and url_key in manual_by_url:
            candidate_manual = manual_by_url[url_key]

            if exact_url_audit_matches_entry(
                candidate_manual,
                entry,
            ):
                manual = candidate_manual
                manual_key = ("url", url_key)

        # Legacy channel-level results are safe only for a single-feed channel.
        elif feed_count == 1:
            tid = normalized_tvg_id(tvg_id)
            cname = canonical_audit_name(clean_name)

            if tid and tid in manual_by_tvg_id:
                manual = manual_by_tvg_id[tid]
                manual_key = ("tvg", tid)
            elif cname and cname in manual_by_name:
                manual = manual_by_name[cname]
                manual_key = ("name", cname)

        item = {
            "channel": clean_name,
            "tvg_id": tvg_id,
            "source": str(entry.get("source") or ""),
            "discovery": str(entry.get("source") or "Current playlist"),
            "stream_url": url,
            "protocol": infer_protocol(url),

            # Legacy fields retained for backwards compatibility.
            "language": "Unknown",
            "language_code": str(
                entry.get("language_code") or "HU"
            ),

            # New country-independent language model.
            "expected_language_codes": (
                normalize_language_codes(
                    entry.get("language_codes")
                    or entry.get("language_code")
                    or "HU"
                )
            ),
            "country_code": (
                normalize_country_code(
                    str(entry.get("country_code") or entry.get("language_code") or "HU")
                )
                or "HU"
            ),
            "language_codes": normalize_language_codes(
                entry.get("language_codes") or entry.get("language_code") or "HU"
            ),
            "observed_language_codes": [],
            "playlist_country_code": (
                normalize_country_code(
                    str(entry.get("country_code") or entry.get("language_code") or "HU")
                )
                or "HU"
            ),
            # Legacy alias: this field historically stored country scope.
            "playlist_language_code": (
                normalize_country_code(
                    str(entry.get("country_code") or entry.get("language_code") or "HU")
                )
                or "HU"
            ),

            "provenance": (
                "Our curated/test extra"
                if entry.get("source_kind") == "extras"
                else "IPTV-org source (manual playback review)"
            ),
            "source_flags": list(entry.get("source_flags") or []),
            "vlc": "not_tested",
            "samsung": "not_tested",
            "vlc_note": "",
            "samsung_note": "",
            "decision": "auto",
            "reason": "",
            "notes": (
                "Auto-added from current tv.m3u for manual testing."
                if feed_count == 1
                else f"Alternative stream Feed {feed_index}/{feed_count}; test this URL separately."
            ),
            "exclude_from_playlist": False,
            "tested_on": "",
        }

        if manual is not None:
            if manual_key:
                used_manual_keys.add(manual_key)
            for key, value in manual.items():
                if value not in ("", None):
                    item[key] = value

        flags: list[str] = []

        for flag in (
            list(entry.get("source_flags") or [])
            + list(item.get("source_flags") or [])
        ):
            if flag and flag not in flags:
                flags.append(flag)

        item["source_flags"] = flags

        (
            expected_codes,
            observed_codes,
            language_match,
        ) = resolve_language_info(
            item,
            default_expected=(
                entry.get("language_codes")
                or entry.get("language_code")
                or "HU"
            ),
        )

        item[
            "expected_language_codes"
        ] = expected_codes

        item[
            "observed_language_codes"
        ] = observed_codes

        item[
            "language_match"
        ] = language_match

        playlist_country_code = (
            normalize_country_code(
                str(
                    item.get("playlist_country_code")
                    or item.get("playlist_language_code")
                    or entry.get("country_code")
                    or entry.get("language_code")
                    or "HU"
                )
            )
            or "HU"
        )
        item["playlist_country_code"] = playlist_country_code
        item["playlist_language_code"] = playlist_country_code

        language_acceptance = (
            language_acceptance_state(
                item,
                supported_language_codes,
            )
        )

        item[
            "language_acceptance"
        ] = language_acceptance

        decision, auto_reason = (
            calculate_audit_decision(
                item,
                supported_language_codes,
            )
        )

        route_probe = {
            **item,
            "decision": decision,
            "observed_language_codes": observed_codes,
        }
        if cfg is not None:
            output_country_code = verified_output_country_code(
                route_probe,
                str(entry.get("country_code") or entry.get("language_code") or ""),
                cfg,
            )
        else:
            output_country_code = verified_output_language_code(
                route_probe,
                str(entry.get("country_code") or entry.get("language_code") or ""),
                configured_country_codes({"country_outputs": {code: "" for code in ("HU", "SK", "CZ")}}),
            )
        output_language_code = output_country_code

        rows.append({
            "channel": str(item.get("channel") or clean_name).strip(),
            "tvg_id": str(item.get("tvg_id") or tvg_id).strip(),
            "source": str(item.get("source") or entry.get("source") or "").strip(),
            "discovery": str(item.get("discovery") or entry.get("source") or "").strip(),
            "stream_url": str(item.get("stream_url") or url).strip(),
            "protocol": str(item.get("protocol") or infer_protocol(url)).strip(),
            # Legacy fields.
            "language": str(
                item.get("language") or "Unknown"
            ).strip(),
            "language_code": str(
                item.get("language_code")
                or entry.get("language_code")
                or "HU"
            ).strip().upper(),

            # Country scope and publication destination.
            "playlist_country_code": str(
                item.get("playlist_country_code")
                or item.get("playlist_language_code")
                or entry.get("country_code")
                or entry.get("language_code")
                or ""
            ).strip().upper(),
            "output_country_code": output_country_code,
            # Legacy aliases retained for old exports/tools.
            "playlist_language_code": str(
                item.get(
                    "playlist_language_code"
                )
                or entry.get(
                    "language_code"
                )
                or ""
            ).strip().upper(),
            "output_language_code": output_language_code,
            "language_codes": normalize_spoken_language_codes(
                entry.get("language_codes") or expected_codes
            ),
            "expected_language_codes": expected_codes,
            "observed_language_codes": observed_codes,
            "language_match": language_match,
            "language_acceptance": (
                language_acceptance
            ),

            "provenance": str(
                item.get("provenance") or ""
            ).strip(),
            "source_flags": flags,
            "vlc": normalize_test_status(str(item.get("vlc") or "")),
            "samsung": normalize_test_status(str(item.get("samsung") or "")),
            "vlc_note": str(item.get("vlc_note") or "").strip(),
            "samsung_note": str(item.get("samsung_note") or "").strip(),
            "decision": decision,
            "reason": str(item.get("reason") or auto_reason or "").strip(),
            "notes": str(item.get("notes") or "").strip(),
            "exclude_from_playlist": audit_excluded(item),
            "tested_on": str(item.get("tested_on") or "").strip(),
            "in_playlist": True,
            "feed_index": feed_index,
            "feed_count": feed_count,
            "feed_label": (
                f"Feed {feed_index}/{feed_count}"
                if feed_count > 1 else "Single"
            ),
        })

    current_urls: set[str] = set()
    current_by_tvg: dict[str, set[str]] = {}
    current_by_name: dict[str, set[str]] = {}
    current_expected_by_url: dict[str, set[str]] = {}
    current_country_by_url: dict[str, set[str]] = {}

    for entry in final_entries:
        current_url = str(
            entry.get("url") or ""
        ).strip()

        if not current_url:
            continue

        current_url_key = canonical_stream_url(
            current_url
        )

        current_urls.add(current_url_key)

        expected_codes = normalize_language_codes(
            entry.get("language_codes")
            or entry.get("language_code")
            or "HU"
        )
        current_country = normalize_country_code(
            str(entry.get("country_code") or entry.get("language_code") or "")
        )
        if current_country:
            current_country_by_url.setdefault(current_url_key, set()).add(current_country)

        if expected_codes:
            current_expected_by_url.setdefault(
                current_url_key,
                set(),
            ).update(expected_codes)

        current_tvg = normalized_tvg_id(
            str(entry.get("tvg_id") or "")
        )

        if current_tvg:
            current_by_tvg.setdefault(
                current_tvg,
                set(),
            ).add(current_url_key)

        for value in (
            entry.get("channel_name"),
            entry.get("display_name"),
            entry.get("tvg_name"),
        ):
            current_name = canonical_audit_name(
                str(value or "")
            )

            if current_name:
                current_by_name.setdefault(
                    current_name,
                    set(),
                ).add(current_url_key)

    # Keep manually tracked candidates/rejections that are not currently in tv.m3u.
    for raw in audit_items:
        item = dict(raw)
        url = str(item.get("stream_url") or "").strip()
        url_key = canonical_stream_url(url)
        tid = normalized_tvg_id(str(item.get("tvg_id") or ""))
        cname = canonical_audit_name(str(item.get("channel") or ""))

        if url:
            manual_key = ("url", url_key)
        elif tid:
            manual_key = ("tvg", tid)
        else:
            manual_key = ("name", cname)

        if manual_key in used_manual_keys:
            continue

        # An exact URL can still need to remain as historical evidence when
        # its saved expected language/country conflicts with the current entry.
        # Do not discard it merely because that URL exists in current inputs.
        legacy_ambiguous = False
        legacy_matching_urls: set[str] = set()

        if not url:
            if tid:
                legacy_matching_urls = current_by_tvg.get(
                    tid,
                    set(),
                )
            elif cname:
                legacy_matching_urls = current_by_name.get(
                    cname,
                    set(),
                )

            # With one current feed, the legacy audit was already safely
            # attached to that stream above.
            if len(legacy_matching_urls) == 1:
                continue

            # With multiple feeds, keep the old audit only as historical
            # evidence. Never apply it to a current stream.
            legacy_ambiguous = len(legacy_matching_urls) > 1

        legacy_expected_codes: list[str] = []

        for matching_url in legacy_matching_urls:
            for code in current_expected_by_url.get(
                matching_url,
                set(),
            ):
                if code not in legacy_expected_codes:
                    legacy_expected_codes.append(code)

        (
            expected_codes,
            observed_codes,
            language_match,
        ) = resolve_language_info(
            item,
            default_expected=legacy_expected_codes,
        )

        item[
            "expected_language_codes"
        ] = expected_codes

        item[
            "observed_language_codes"
        ] = observed_codes

        item[
            "language_match"
        ] = language_match

        historical_scope = (
            audit_playlist_scope_code(
                item
            )
        )

        if historical_scope:
            item[
                "playlist_language_code"
            ] = historical_scope

        language_acceptance = (
            language_acceptance_state(
                item,
                supported_language_codes,
            )
        )

        item[
            "language_acceptance"
        ] = language_acceptance

        decision, auto_reason = (
            calculate_audit_decision(
                item,
                supported_language_codes,
            )
        )

        history_notes = str(
            item.get("notes") or ""
        ).strip()

        if url_key and url_key in current_expected_by_url:
            saved_scope = (
                audit_playlist_scope_code(
                    item
                )
            )
            current_countries = sorted(
                current_country_by_url.get(url_key, set())
            )

            if (
                saved_scope
                and current_countries
                and saved_scope
                not in current_countries
            ):
                identity_note = (
                    "Historical exact-URL audit only. Saved playlist "
                    f"scope {saved_scope} does not match the current "
                    "entry scope "
                    f"{', '.join(current_countries)}, so this "
                    "verification was not transferred."
                )

                history_notes = " — ".join(
                    part
                    for part in (
                        history_notes,
                        identity_note,
                    )
                    if part
                )

        if legacy_ambiguous:
            ambiguity_note = (
                f"Historical channel-level audit only. "
                f"{len(legacy_matching_urls)} current feeds now match this "
                f"channel, so this saved result was not applied to any of "
                f"them. Re-test the individual stream URLs."
            )

            history_notes = " — ".join(
                part
                for part in (
                    history_notes,
                    ambiguity_note,
                )
                if part
            )
			
        rows.append({
            "channel": str(item.get("channel") or "Unnamed channel").strip(),
            "tvg_id": str(item.get("tvg_id") or "").strip(),
            "source": str(item.get("source") or "").strip(),
            "discovery": str(item.get("discovery") or "").strip(),
            "stream_url": url,
            "protocol": str(item.get("protocol") or infer_protocol(url)).strip(),
            # Legacy fields.
            "language": str(
                item.get("language") or "Unknown"
            ).strip(),
            "language_code": str(
                item.get("language_code") or ""
            ).strip().upper(),

            # Modern country model plus legacy alias.
            "playlist_country_code": str(
                item.get("playlist_country_code")
                or item.get("playlist_language_code")
                or ""
            ).strip().upper(),
            "output_country_code": str(
                item.get("output_country_code")
                or item.get("output_language_code")
                or ""
            ).strip().upper(),
            "playlist_language_code": str(
                item.get("playlist_country_code")
                or item.get("playlist_language_code")
                or ""
            ).strip().upper(),
            "expected_language_codes": expected_codes,
            "observed_language_codes": observed_codes,
            "language_match": language_match,
            "language_acceptance": (
                language_acceptance
            ),

            "provenance": str(
                item.get("provenance") or "Unknown"
            ).strip(),
            "source_flags": list(item.get("source_flags") or []),
            "vlc": normalize_test_status(str(item.get("vlc") or "")),
            "samsung": normalize_test_status(str(item.get("samsung") or "")),
            "vlc_note": str(item.get("vlc_note") or "").strip(),
            "samsung_note": str(item.get("samsung_note") or "").strip(),
            "decision": decision,
            "reason": str(item.get("reason") or auto_reason or "").strip(),
            "notes": history_notes,
            "exclude_from_playlist": audit_excluded(item),
            "tested_on": str(item.get("tested_on") or "").strip(),
            "in_playlist": False,
            "feed_index": 1,
            "feed_count": (
                len(legacy_matching_urls)
                if legacy_ambiguous
                else 1
            ),
            "feed_label": (
                "Legacy audit"
                if legacy_ambiguous
                else "Candidate"
            ),
        })

    priority = {
        "Needs review": 0,
        "TV verified": 1,
        "PC only": 2,
        "Verified": 3,
        "Rejected": 4,
    }

    return sorted(
        rows,
        key=lambda x: (
            priority.get(x["decision"], 9),
            0 if x["in_playlist"] else 1,
            normalize_text(x["channel"]),
            int(x.get("feed_index") or 1),
        ),
    )

def select_playlist_candidates(
    final_entries: list[dict],
    audit_rows: list[dict],
) -> tuple[list[dict], list[dict]]:
    """
    Select playlist feeds using exact stream URLs only.

    prepare_audit_rows() may convert a safe single-feed legacy audit into a
    URL-specific prepared row. Unmatched channel-level history is never used
    here as a fallback.
    """
    audit_by_url = audit_rows_by_stream_url(
        audit_rows
    )

    candidate_entries: list[dict] = []
    excluded_rows: list[dict] = []

    for source_order, entry in enumerate(final_entries):
        url = str(entry.get("url") or "").strip()
        url_key = canonical_stream_url(url)
        audit = audit_by_url.get(url_key)
        decision = audit.get("decision", "Needs review") if audit else "Needs review"
        exclude = audit_excluded(audit) if audit else False

        if exclude or decision == "Rejected":
            excluded_rows.append({
                "channel_name": entry.get("channel_name", ""),
                "tvg_id": entry.get("tvg_id", ""),
                "source": entry.get("source", ""),
                "stream_url": entry.get("url", ""),
                "reason": (
                    (audit or {}).get("reason")
                    or (audit or {}).get("notes")
                    or "Rejected by manual audit"
                ),
            })
            continue

        candidate = dict(entry)
        candidate["_audit"] = audit or {}
        candidate["_decision"] = decision
        candidate["_source_order"] = source_order
        candidate_entries.append(candidate)

    candidate_groups: dict[str, list[dict]] = {}
    for entry in candidate_entries:
        candidate_groups.setdefault(logical_channel_key(entry), []).append(entry)

    def verified_feed_rank(entry: dict) -> tuple:
        audit = entry.get("_audit") or {}
        vlc = normalize_test_status(str(audit.get("vlc") or ""))
        samsung = normalize_test_status(str(audit.get("samsung") or ""))

        vlc_rank = {
            "works": 3,
            "works_with_warning": 2,
        }.get(vlc, 0)

        samsung_rank = 1 if samsung == "works" else 0
        source_rank = -int(entry.get("_source_order") or 0)
        return (vlc_rank, samsung_rank, source_rank)

    selected_candidates: list[dict] = []

    for group in candidate_groups.values():
        verified = [e for e in group if e.get("_decision") == "Verified"]

        if verified:
            winner = max(verified, key=verified_feed_rank)
            selected_candidates.append(winner)

            for entry in group:
                if entry is winner:
                    continue
                excluded_rows.append({
                    "channel_name": entry.get("channel_name", ""),
                    "tvg_id": entry.get("tvg_id", ""),
                    "source": entry.get("source", ""),
                    "stream_url": entry.get("url", ""),
                    "reason": (
                        "Suppressed because another feed for this channel is "
                        "already Verified on both VLC and Samsung."
                    ),
                })
        else:
            selected_candidates.extend(group)

    return selected_candidates, excluded_rows

def audit_rows_by_stream_url(
    audit_rows: list[dict],
) -> dict[str, dict]:
    """
    Build an exact/canonical stream-URL lookup for prepared audit rows.
    """
    result: dict[str, dict] = {}

    for row in audit_rows:
        # Historical rows may intentionally retain the same URL as a current
        # entry after an identity-scope conflict. They must never drive current
        # playlist selection.
        if row.get("in_playlist") is False:
            continue

        url = str(
            row.get("stream_url") or ""
        ).strip()

        if not url:
            continue

        key = canonical_stream_url(url)

        if key in result:
            raise RuntimeError(
                f"Duplicate prepared audit URL: {url}"
            )

        result[key] = row

    return result


def make_test_playlist_candidates(
    final_entries: list[dict],
    audit_rows: list[dict],
) -> list[dict]:
    """
    Keep every current unique stream candidate in the testing playlist.

    Unlike the stable family playlist, test.m3u intentionally keeps:
      - Verified
      - TV verified
      - PC only
      - Needs review
      - Rejected
      - exclude_from_playlist feeds
      - alternative feeds

    Exact duplicate URLs have already been removed earlier in the build.
    """
    audit_by_url = audit_rows_by_stream_url(
        audit_rows
    )

    candidates: list[dict] = []

    for source_order, entry in enumerate(
        final_entries
    ):
        url = str(
            entry.get("url") or ""
        ).strip()

        audit = audit_by_url.get(
            canonical_stream_url(url)
        )

        decision = (
            audit.get(
                "decision",
                "Needs review",
            )
            if audit
            else "Needs review"
        )

        candidate = dict(entry)

        candidate["_audit"] = (
            audit or {}
        )

        candidate["_decision"] = (
            decision
        )

        candidate["_source_order"] = (
            source_order
        )

        candidates.append(
            candidate
        )

    return candidates


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

def stable_block_reason(
    entry: dict,
    cfg: dict,
) -> str:
    """
    Return a reason when a stream is never suitable for the stable
    family playlist even if somebody accidentally marks it Verified.

    The stream still remains available in test.m3u.
    """
    stable_cfg = (
        cfg.get("stable_playlist")
        or {}
    )

    blocked_hosts = [
        str(value).strip().casefold()
        for value in (
            stable_cfg.get(
                "blocked_hosts"
            )
            or [
                "youtube.com",
                "youtube-nocookie.com",
                "youtu.be",
                "googlevideo.com",
                "ythls.onrender.com",
            ]
        )
        if str(value).strip()
    ]

    url = str(
        entry.get("url") or ""
    ).strip()

    hostname = (
        urlparse(url).hostname
        or ""
    ).casefold()

    for blocked_host in blocked_hosts:
        if (
            hostname == blocked_host
            or hostname.endswith(
                "." + blocked_host
            )
        ):
            return (
                "Test-only stream host: "
                f"{hostname}"
            )

    blocked_flags = {
        str(value).strip().casefold()
        for value in (
            stable_cfg.get(
                "blocked_source_flags"
            )
            or ["Offline"]
        )
        if str(value).strip()
    }

    entry_flags = {
        str(value).strip().casefold()
        for value in (
            entry.get(
                "source_flags"
            )
            or []
        )
        if str(value).strip()
    }

    matching_flags = (
        blocked_flags
        & entry_flags
    )

    if matching_flags:
        return (
            "Blocked source flag: "
            + ", ".join(
                sorted(
                    matching_flags
                )
            )
        )

    blocked_terms = [
        str(value).strip().casefold()
        for value in (
            stable_cfg.get(
                "blocked_name_terms"
            )
            or [
                "webcam",
                "web cam",
                "camera",
                "kamera",
                "időkép",
                "idokep",
            ]
        )
        if str(value).strip()
    ]

    searchable_text = " ".join(
        str(
            entry.get(field)
            or ""
        )
        for field in (
            "channel_name",
            "display_name",
            "tvg_name",
            "group_title",
            "source_group_title",
            "source",
        )
    ).casefold()

    for term in blocked_terms:
        if re.search(
            rf"(?<!\w){re.escape(term)}(?!\w)",
            searchable_text,
            flags=re.IGNORECASE,
        ):
            return (
                "Test-only channel type: "
                f"{term}"
            )

    return ""


def select_stable_playlist_candidates(
    final_entries: list[dict],
    audit_rows: list[dict],
    cfg: dict,
) -> tuple[
    list[dict],
    list[dict],
]:
    """
    Select the family-safe playlist.

    Only explicitly TV-safe decisions are accepted:
      - Verified
      - TV verified

    PC-only, Needs-review, Rejected, explicitly excluded, YouTube,
    webcam/camera and Offline feeds remain outside tv.m3u.

    Only one best stable feed is published for each logical channel.
    """
    stable_cfg = (
        cfg.get("stable_playlist")
        or {}
    )

    quality_context = (
        build_feed_quality_context(
            cfg
        )
    )

    allowed_decisions = {
        str(value).strip()
        for value in (
            stable_cfg.get(
                "allowed_decisions"
            )
            or [
                "Verified",
                "TV verified",
            ]
        )
        if str(value).strip()
    }

    all_candidates = (
        route_candidates_to_verified_countries(
            make_test_playlist_candidates(
                final_entries,
                audit_rows,
            ),
            cfg,
        )
    )

    stable_groups: dict[
        str,
        list[dict],
    ] = {}

    excluded_rows: list[dict] = []

    def add_excluded(
        entry: dict,
        reason: str,
    ) -> None:
        excluded_rows.append({
            "channel_name": entry.get(
                "channel_name",
                "",
            ),
            "tvg_id": entry.get(
                "tvg_id",
                "",
            ),
            "source": entry.get(
                "source",
                "",
            ),
            "stream_url": entry.get(
                "url",
                "",
            ),
            "reason": reason,
        })

    for entry in all_candidates:
        audit = (
            entry.get("_audit")
            or {}
        )

        decision = entry.get(
            "_decision",
            "Needs review",
        )

        if audit_excluded(audit):
            add_excluded(
                entry,
                (
                    audit.get("reason")
                    or audit.get("notes")
                    or (
                        "Explicitly excluded "
                        "from stable family playlist."
                    )
                ),
            )
            continue

        if decision == "Rejected":
            add_excluded(
                entry,
                (
                    audit.get("reason")
                    or audit.get("notes")
                    or (
                        "Rejected by manual "
                        "playback/language audit."
                    )
                ),
            )
            continue

        if (
            decision
            not in allowed_decisions
        ):
            add_excluded(
                entry,
                (
                    "Not stable yet: "
                    f"{decision}"
                ),
            )
            continue

        block_reason = (
            stable_block_reason(
                entry,
                cfg,
            )
        )

        if block_reason:
            add_excluded(
                entry,
                block_reason,
            )
            continue

        stable_groups.setdefault(
            logical_channel_key(entry),
            [],
        ).append(
            entry
        )

    def stable_feed_rank(
        entry: dict,
    ) -> tuple:
        quality = score_feed_quality(
            entry,
            cfg,
            context=quality_context,
        )

        entry[
            "_feed_quality_score"
        ] = int(
            quality.get("score")
            or 0
        )

        entry[
            "_feed_quality_summary"
        ] = str(
            quality.get("summary")
            or ""
        )

        source_rank = -int(
            entry.get(
                "_source_order"
            )
            or 0
        )

        return (
            entry[
                "_feed_quality_score"
            ],
            source_rank,
        )

    selected: list[dict] = []

    for group in stable_groups.values():
        winner = max(
            group,
            key=stable_feed_rank,
        )

        selected.append(
            winner
        )

        winner_score = int(
            winner.get(
                "_feed_quality_score"
            )
            or 0
        )

        for entry in group:
            if entry is winner:
                continue

            entry_score = int(
                entry.get(
                    "_feed_quality_score"
                )
                or 0
            )

            add_excluded(
                entry,
                (
                    "Another stable feed for "
                    "this logical channel was "
                    "ranked higher by feed-quality "
                    f"score (winner {winner_score}; "
                    f"this feed {entry_score})."
                ),
            )

    return (
        selected,
        excluded_rows,
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
    """
    Write one generated M3U playlist.

    name_style controls only the visible channel-name prefix:
      status   -> [HU OK] / [SK ?] / [CZ TV] (testing playlist)
      country  -> [HU] / [SK] / [CZ] (shared stable playlist)
      language -> legacy alias for country
      plain    -> no generated prefix (single-country playlists)
    """
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    out_lines = [
        playlist_header(cfg),
        (
            "# Generated automatically: "
            f"{generated}"
        ),
        (
            "# Tomas IPTV "
            "smart builder v19"
        ),
        (
            "# Playlist: "
            f"{playlist_label}"
        ),
        "",
    ]

    valid_name_styles = {
        "status",
        "language",
        "country",
        "plain",
    }

    if name_style not in valid_name_styles:
        raise ValueError(
            f"Unsupported playlist name_style: {name_style!r}"
        )

    for entry in entries:
        entry_lines = entry["lines"]

        if name_style != "status":
            original_display = strip_custom_prefix(
                str(
                    entry.get("published_name")
                    or entry.get("display_name")
                    or "Unnamed channel"
                )
            )

            if name_style in {"language", "country"}:
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
                output_name = f"[{country_code}] {original_display}"
            else:
                output_name = original_display

            entry_lines = rewrite_entry_lines(
                entry_lines,
                output_name,
                str(entry.get("group_title") or ""),
            )

        out_lines.extend(
            entry_lines
        )

        out_lines.append(
            ""
        )

    path.write_text(
        "\n".join(
            out_lines
        ).rstrip()
        + "\n",
        encoding="utf-8",
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
