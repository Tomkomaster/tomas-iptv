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


def strip_display_annotations(name: str) -> str:
    value = " ".join((name or "").split()).strip()
    old = None
    while value and value != old:
        old = value
        value = QUALITY_SUFFIX_RE.sub("", value).strip()
    return value or "Unnamed channel"


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def normalized_tvg_id(tvg_id: str) -> str:
    value = (tvg_id or "").strip()
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
	
def channel_key(entry: dict) -> str:
    """
    Identify a logical channel.

    Priority:
      1. tvg-id, with @SD/@HD-style variants collapsed
      2. tvg-name
      3. cleaned display name
    """
    tvg_id = normalized_tvg_id(entry.get("tvg_id", ""))
    if tvg_id:
        return f"id:{tvg_id}"

    tvg_name = normalize_text(entry.get("tvg_name", ""))
    if tvg_name:
        return f"name:{tvg_name}"

    return f"name:{normalize_text(strip_display_annotations(entry.get('display_name', '')))}"



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

def country_name_for_language(
    cfg: dict,
    language_code: str,
) -> str:
    """
    Return the human-readable country/group prefix for a playlist language.

    Examples:
      HU -> Hungary
      SK -> Slovakia
      CZ -> Czechia

    Unknown codes safely fall back to the code itself.
    """
    code = str(
        language_code or ""
    ).strip().upper()

    country_names = cfg.get(
        "country_names"
    ) or {}

    if isinstance(country_names, dict):
        country = str(
            country_names.get(code) or ""
        ).strip()

        if country:
            return country

    return code or "Other"


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

def summarize_language_stats(
    entries: list[dict],
    source_stats: list[dict],
) -> list[dict]:
    """
    Summarize the final published playlist by language.

    Channel counts are logical-channel counts.
    Stream counts are actual published stream URLs.
    """
    language_codes: set[str] = set()

    for entry in entries:
        code = normalize_language_code(
            str(
                entry.get(
                    "language_code"
                )
                or ""
            )
        )

        if code:
            language_codes.add(code)

    for source in source_stats:
        code = normalize_language_code(
            str(
                source.get(
                    "language_code"
                )
                or ""
            )
        )

        if code:
            language_codes.add(code)

    result: list[dict] = []

    for code in sorted(language_codes):
        language_entries = [
            entry
            for entry in entries
            if normalize_language_code(
                str(
                    entry.get(
                        "language_code"
                    )
                    or ""
                )
            ) == code
        ]

        language_sources = [
            source
            for source in source_stats
            if normalize_language_code(
                str(
                    source.get(
                        "language_code"
                    )
                    or ""
                )
            ) == code
        ]

        unique_channel_keys = {
            entry.get("channel_key")
            for entry in language_entries
            if entry.get("channel_key")
        }

        base_channel_keys = {
            entry.get("channel_key")
            for entry in language_entries
            if (
                entry.get("channel_key")
                and entry.get(
                    "classification"
                ) == "Base channel"
            )
        }

        added_channel_keys = {
            entry.get("channel_key")
            for entry in language_entries
            if (
                entry.get("channel_key")
                and entry.get(
                    "classification"
                ) == "Added channel"
            )
        }

        result.append({
            "language_code": code,

            "source_count": len(
                language_sources
            ),

            "base_source_count": sum(
                1
                for source in language_sources
                if source.get("kind") == "base"
            ),

            "unique_channels": len(
                unique_channel_keys
            ),

            "stream_urls": len(
                language_entries
            ),

            "base_channels": len(
                base_channel_keys
            ),

            "added_channels": len(
                added_channel_keys
            ),

            "alternative_streams": sum(
                1
                for entry in language_entries
                if entry.get(
                    "classification"
                ) == "Alternative stream"
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

    "slovak": "SK",
    "slovakian": "SK",

    "czech": "CZ",

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
    """
    Identify a logical channel inside one language/country playlist.

    channel_key() intentionally remains language-agnostic so SD/HD variants
    and equivalent source metadata still collapse. This helper adds the
    playlist language only where cross-source grouping needs it.
    """
    language_code = (
        normalize_language_code(
            str(entry.get("language_code") or "")
        )
        or "UNKNOWN"
    )

    raw_key = str(
        entry.get("channel_key")
        or channel_key(entry)
    )

    prefix = f"{language_code}:"
    if raw_key.startswith(prefix):
        return raw_key

    return f"{prefix}{raw_key}"


def normalize_language_codes(value) -> list[str]:
    """
    Normalize a language-code list while preserving order and removing
    duplicates.

    New audit data should use JSON lists, for example:
      ["HU"]
      ["HU", "SR"]

    Strings are also accepted to make migration and legacy data easier.
    """
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

    expected = set(expected_codes)
    observed = set(observed_codes)

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
	
def calculate_audit_decision(item: dict) -> tuple[str, str]:
    """
    Playback/device status for our playlist, not a legal certification.

    Language matching is country-agnostic:
      yes          -> acceptable
      multilingual -> acceptable because the expected language is present
      no           -> rejected
      unknown      -> language alone does not decide the result
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
                or "Excluded from this language playlist."
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

    if language_match == "no":
        return (
            "Rejected",
            language_mismatch_reason(
                expected_codes,
                observed_codes,
            ),
        )

    pc_good = vlc in {
        "works",
        "works_with_warning",
    }

    tv_good = samsung == "works"

    if pc_good and tv_good:
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

    for entry in final_entries:
        url = str(
            entry.get("url") or ""
        ).strip()

        if not url:
            continue

        url_key = canonical_stream_url(url)

        expected_codes = normalize_language_codes(
            entry.get("expected_language_codes")
            or entry.get("language_code")
        )

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


def prepare_audit_rows(audit_items: list[dict], final_entries: list[dict]) -> list[dict]:
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

        # URL-specific audit is always authoritative. Canonically equivalent
        # URL spellings identify the same stream.
        if url_key and url_key in manual_by_url:
            manual = manual_by_url[url_key]
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
                    entry.get("language_code") or "HU"
                )
            ),
            "observed_language_codes": [],

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
                entry.get("language_code")
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

        decision, auto_reason = (
            calculate_audit_decision(item)
        )

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

            # New language model.
            "expected_language_codes": expected_codes,
            "observed_language_codes": observed_codes,
            "language_match": language_match,

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
            entry.get("language_code")
            or "HU"
        )

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

        if url_key and url_key in current_urls:
            continue

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

        decision, auto_reason = (
            calculate_audit_decision(item)
        )

        history_notes = str(
            item.get("notes") or ""
        ).strip()

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

            # New language model.
            "expected_language_codes": expected_codes,
            "observed_language_codes": observed_codes,
            "language_match": language_match,

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
    audit_by_url: dict[str, dict] = {}

    for row in audit_rows:
        url = str(row.get("stream_url") or "").strip()
        if not url:
            continue

        url_key = canonical_stream_url(url)

        if url_key in audit_by_url:
            raise RuntimeError(f"Duplicate prepared audit URL: {url}")

        audit_by_url[url_key] = row

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
        make_test_playlist_candidates(
            final_entries,
            audit_rows,
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
        audit = (
            entry.get("_audit")
            or {}
        )

        decision = entry.get(
            "_decision",
            "Needs review",
        )

        decision_rank = {
            "TV verified": 1,
            "Verified": 2,
        }.get(
            decision,
            0,
        )

        vlc = normalize_test_status(
            str(
                audit.get("vlc")
                or ""
            )
        )

        samsung = (
            normalize_test_status(
                str(
                    audit.get(
                        "samsung"
                    )
                    or ""
                )
            )
        )

        vlc_rank = {
            "works": 3,
            "works_with_warning": 2,
        }.get(
            vlc,
            0,
        )

        samsung_rank = (
            1
            if samsung == "works"
            else 0
        )

        source_rank = -int(
            entry.get(
                "_source_order"
            )
            or 0
        )

        return (
            decision_rank,
            vlc_rank,
            samsung_rank,
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

        for entry in group:
            if entry is winner:
                continue

            add_excluded(
                entry,
                (
                    "Another stable feed for "
                    "this logical channel was "
                    "ranked higher."
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

            lang = str(
                entry.get(
                    "language_code"
                )
                or cfg.get(
                    "default_language_code"
                )
                or "HU"
            ).upper()

            suffix = (
                playlist_status_suffix(
                    decision
                )
            )

            original_display = (
                strip_custom_prefix(
                    entry.get(
                        "display_name",
                        "",
                    )
                )
            )

            feed_suffix = (
                (
                    f" [Feed "
                    f"{visible_index}/"
                    f"{visible_count}]"
                )
                if visible_count > 1
                else ""
            )

            published_name = (
                f"[{lang} {suffix}] "
                f"{original_display}"
                f"{feed_suffix}"
            )

            country_name = str(
                entry.get(
                    "country_name"
                )
                or country_name_for_language(
                    cfg,
                    lang,
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
                    language_code=lang,
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


def write_m3u_playlist(
    path: Path,
    cfg: dict,
    entries: list[dict],
    generated: str,
    playlist_label: str,
) -> None:
    """
    Write one generated M3U playlist.
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

    for entry in entries:
        out_lines.extend(
            entry["lines"]
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
) -> str:
    title = str(cfg.get("site_title") or "Tomas IPTV")
    epg_cfg = cfg.get("epg") or {}

    epg_link_html = ""

    if (
        isinstance(epg_cfg, dict)
        and epg_cfg.get("enabled")
        and str(
            epg_cfg.get("public_url") or ""
        ).strip()
    ):
        epg_link_html = (
            '<a href="guide.xml">'
            'EPG programme guide (guide.xml)'
            '</a>'
            ' · '
            '<a href="epg-coverage.json">'
            'EPG coverage report'
            '</a>'
        )
		
    total_streams = len(final_entries)
    total_channels = len(unique_channels)
    total_duplicates = len(duplicate_rows)
    total_alternatives = sum(1 for e in final_entries if e["classification"] == "Alternative stream")
    added_from_nonbase = sum(1 for e in final_entries if e["classification"] == "Added channel")
    audit_verified = sum(1 for e in audit_rows if e["decision"] == "Verified")
    audit_tv_verified = sum(1 for e in audit_rows if e["decision"] == "TV verified")
    audit_pc_only = sum(1 for e in audit_rows if e["decision"] == "PC only")
    audit_review = sum(1 for e in audit_rows if e["decision"] == "Needs review")
    audit_rejected = sum(1 for e in audit_rows if e["decision"] == "Rejected")
    audit_current = [e for e in audit_rows if e["in_playlist"]]
    audit_both_tested = sum(
        1 for e in audit_current
        if is_tested_status(e["vlc"]) and is_tested_status(e["samsung"])
    )
    audit_vlc_pending = sum(
        1 for e in audit_current
        if not is_tested_status(e["vlc"])
    )
    audit_samsung_pending = sum(
        1 for e in audit_current
        if not is_tested_status(e["samsung"])
    )

    def esc(v) -> str:
        return html.escape(str(v or ""))

    audit_warning_html = ""

    if audit_ambiguity_warnings:
        warning_items = "".join(
            f"<li>{esc(message)}</li>"
            for message in audit_ambiguity_warnings
        )

        audit_warning_html = f"""
        <div class="panel warning-panel">
          <strong>
            ⚠ Audit warnings ({len(audit_ambiguity_warnings)})
          </strong>
          <p>
            One or more old channel-level verification results became
            ambiguous because multiple current feeds now exist. The old
            results were not applied to any current stream.
          </p>
          <ul>
            {warning_items}
          </ul>
        </div>
        """
		
    source_options = "\n".join(
        f'<option value="{esc(s["name"])}">{esc(s["name"])}</option>'
        for s in source_stats
    )

    language_rows = "\n".join(
        f"""
        <tr>
          <td><strong>{esc(s["language_code"])}</strong></td>
          <td>{s["source_count"]}</td>
          <td>{s["base_source_count"]}</td>
          <td>{s["unique_channels"]}</td>
          <td>{s["stream_urls"]}</td>
          <td>{s["base_channels"]}</td>
          <td>{s["added_channels"]}</td>
          <td>{s["alternative_streams"]}</td>
        </tr>
        """
        for s in language_stats
    )
	
    source_rows = "\n".join(
        f"""
        <tr>
          <td>{esc(s["name"])}</td>
          <td>{esc(s["language_code"])}</td>
          <td>{esc(s["kind"])}</td>
          <td>{s["raw_entries"]}</td>
          <td>{s["unique_channels_in_source"]}</td>
          <td>{s["kept_stream_urls"]}</td>
          <td>{s["base_channels_contributed"]}</td>
          <td>{s["added_channels_contributed"]}</td>
          <td>{s["alternative_streams"]}</td>
          <td>{s["duplicate_urls_ignored"]}</td>
        </tr>
        """
        for s in source_stats
    )

    channel_rows = []
    for e in final_entries:
        classification = e["classification"]
        badge_class = {
            "Base channel": "base",
            "Added channel": "added",
            "Alternative stream": "alt",
        }.get(classification, "base")

        channel_rows.append(
            f"""
            <tr data-source="{esc(e["source"])}" data-status="{esc(classification)}">
              <td class="channel">{esc(e["channel_name"])}</td>
              <td>{esc(e.get("tvg_id", ""))}</td>
              <td>{esc(e.get("group_title", ""))}</td>
              <td>{esc(e["source"])}</td>
              <td><span class="badge {badge_class}">{esc(classification)}</span></td>
              <td class="url"><a href="{esc(e["url"])}" target="_blank" rel="noopener">stream</a></td>
            </tr>
            """
        )

    def test_badge(value: str) -> str:
        labels = {
            "works": ("✓ Works", "verified"),
            "works_with_warning": ("✓ Works*", "pc"),
            "loads": ("… Loads", "review"),
            "mrl_error": ("MRL error", "rejected"),
            "format_error": ("Format error", "rejected"),
            "generic_error": ("Player error", "rejected"),
            "wrong_language": ("Wrong language", "rejected"),
            "not_tested": ("? Not tested", "review"),
            "needs_review": ("? Review", "review"),
            "n/a": ("N/A", "base"),
        }
        label, css = labels.get(value, (value or "?", "review"))
        return f'<span class="badge {css}">{esc(label)}</span>'

    def language_match_badge(value: str) -> str:
        labels = {
            "yes": (
                "✓ Match",
                "verified",
            ),
            "multilingual": (
                "✓ Multilingual",
                "tv",
            ),
            "no": (
                "Wrong language",
                "rejected",
            ),
            "unknown": (
                "? Unknown",
                "review",
            ),
        }

        label, css = labels.get(
            value,
            (
                value or "? Unknown",
                "review",
            ),
        )

        return (
            f'<span class="badge {css}">'
            f'{esc(label)}</span>'
        )
		
    audit_table_rows = []
    for a in audit_rows:
        decision_css = {
            "Verified": "verified",
            "TV verified": "tv",
            "PC only": "pc",
            "Needs review": "review",
            "Rejected": "rejected",
        }.get(a["decision"], "review")

        in_test_playlist = (
            '<span class="badge verified">Yes</span>'
            if a.get(
                "in_playlist"
            )
            else (
                '<span class="badge base">'
                'No</span>'
            )
        )

        in_stable_playlist = (
            '<span class="badge verified">Yes</span>'
            if a.get(
                "in_stable_playlist"
            )
            else (
                '<span class="badge base">'
                'No</span>'
            )
        )

        reason_notes = " — ".join(
            part for part in [a.get("reason", ""), a.get("notes", "")] if part
        )

        stream_link = (
            f'<a href="{esc(a["stream_url"])}" target="_blank" rel="noopener">stream</a>'
            if a.get("stream_url")
            else "—"
        )

        audit_table_rows.append(
            f"""
            <tr data-audit-decision="{esc(a["decision"])}" data-audit-vlc="{esc(a["vlc"])}" data-audit-samsung="{esc(a["samsung"])}">
              <td class="channel">{esc(a["channel"])}</td>
              <td>{esc(a.get("feed_label", "Single"))}</td>
              <td>{esc(a.get("tvg_id", "") or "—")}</td>
              <td>{esc(a.get("source", "") or "—")}</td>
              <td>{esc(a["discovery"])}</td>
              <td>{esc(a["protocol"] or "—")}</td>
              <td>{esc(format_language_codes(a.get("expected_language_codes")))}</td>
              <td>{esc(format_language_codes(a.get("observed_language_codes")))}</td>
              <td>{language_match_badge(a.get("language_match", "unknown"))}</td>
              <td>{esc(a["provenance"])}</td>
              <td>{esc(", ".join(a.get("source_flags") or []) or "—")}</td>
              <td>{test_badge(a["vlc"])}<div class="detail">{esc(a.get("vlc_note", ""))}</div></td>
              <td>{test_badge(a["samsung"])}<div class="detail">{esc(a.get("samsung_note", ""))}</div></td>
              <td><span class="badge {decision_css}">{esc(a["decision"])}</span></td>
              <td>{in_test_playlist}</td>
              <td>{in_stable_playlist}</td>
              <td>{esc(reason_notes or "—")}</td>
              <td class="url">{stream_link}</td>
            </tr>
            """
        )

    previous = changes.get("previous_generated_at")
    if previous:
        added_names = changes.get("added_channels", [])
        removed_names = changes.get("removed_channels", [])

        def list_items(values: list[str], empty_text: str) -> str:
            if not values:
                return f"<li>{esc(empty_text)}</li>"
            return "".join(f"<li>{esc(v)}</li>" for v in values)

        change_html = f"""
        <div class="change-grid">
          <div class="panel">
            <h3>Added since previous build <span class="count positive">+{len(added_names)}</span></h3>
            <details {'open' if added_names else ''}>
              <summary>Show channels</summary>
              <ul>{list_items(added_names, "No channels added.")}</ul>
            </details>
          </div>
          <div class="panel">
            <h3>Removed since previous build <span class="count negative">-{len(removed_names)}</span></h3>
            <details {'open' if removed_names else ''}>
              <summary>Show channels</summary>
              <ul>{list_items(removed_names, "No channels removed.")}</ul>
            </details>
          </div>
        </div>
        <p class="muted">Compared with report generated {esc(previous)}.</p>
        """
    else:
        change_html = """
        <div class="panel">
          <strong>No previous report was available for comparison.</strong>
          <p class="muted">After the next successful build, this section will show channels added and removed since the previous deployment.</p>
        </div>
        """

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>
:root {{
  color-scheme: light dark;
  --bg: #0d1117;
  --card: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --muted: #8b949e;
  --accent: #58a6ff;
  --good: #3fb950;
  --purple: #a371f7;
  --warn: #d29922;
  --bad: #f85149;
}}
@media (prefers-color-scheme: light) {{
  :root {{
    --bg: #ffffff;
    --card: #f6f8fa;
    --border: #d0d7de;
    --text: #1f2328;
    --muted: #656d76;
    --accent: #0969da;
    --good: #1a7f37;
    --purple: #8250df;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.45;
}}
main {{ max-width: 1500px; margin: 0 auto; padding: 28px 20px 60px; }}
h1 {{ margin-bottom: 4px; }}
h2 {{ margin-top: 34px; }}
a {{ color: var(--accent); }}
.muted {{ color: var(--muted); }}
.links {{ display: flex; gap: 14px; flex-wrap: wrap; margin: 18px 0; }}
.cards {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin: 20px 0;
}}
.card, .panel {{
  border: 1px solid var(--border);
  background: var(--card);
  border-radius: 10px;
  padding: 16px;
}}
.warning-panel {{
  border-color: var(--warn);
  border-left: 5px solid var(--warn);
  margin: 18px 0;
}}

.warning-panel strong {{
  color: var(--warn);
}}

.warning-panel ul {{
  margin-bottom: 0;
}}
.card .value {{ font-size: 1.8rem; font-weight: 750; }}
.card .label {{ color: var(--muted); font-size: .92rem; }}
.table-wrap {{
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: 10px;
}}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  text-align: left;
  vertical-align: top;
}}
th {{
  position: sticky;
  top: 0;
  background: var(--card);
  z-index: 1;
}}
tr:last-child td {{ border-bottom: 0; }}
.channel {{ font-weight: 650; min-width: 220px; }}
.url {{ white-space: nowrap; }}
.badge {{
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: .82rem;
  font-weight: 700;
  white-space: nowrap;
}}
.badge.base {{ border: 1px solid var(--border); }}
.badge.added {{ color: var(--good); border: 1px solid var(--good); }}
.badge.alt {{ color: var(--purple); border: 1px solid var(--purple); }}
.badge.verified {{ color: var(--good); border: 1px solid var(--good); }}
.badge.review {{ color: var(--warn); border: 1px solid var(--warn); }}
.badge.rejected {{ color: var(--bad); border: 1px solid var(--bad); }}
.badge.tv {{ color: var(--accent); border: 1px solid var(--accent); }}
.badge.pc {{ color: var(--purple); border: 1px solid var(--purple); }}
.detail {{ color: var(--muted); font-size: .76rem; margin-top: 4px; max-width: 360px; }}
.audit-summary {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin: 12px 0 18px;
}}
.controls {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  margin: 14px 0;
}}
input, select {{
  width: 100%;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--card);
  color: var(--text);
}}
.change-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
}}
.count {{ font-size: .9rem; }}
.positive {{ color: var(--good); }}
.negative {{ color: #f85149; }}
details ul {{ max-height: 260px; overflow: auto; }}
@media (max-width: 780px) {{
  .controls {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<main>
  <h1>{esc(title)}</h1>
  <p class="muted">Generated automatically: {esc(generated)}</p>

  <div class="links">
    <a href="tv.m3u">Stable family playlist (tv.m3u)</a>
    <a href="test.m3u">Testing playlist (test.m3u)</a>
    <a href="hu.m3u">Stable Hungary (hu.m3u)</a>
    <a href="sk.m3u">Stable Slovakia (sk.m3u)</a>
    {epg_link_html}
    <a href="channels.csv">Channel inventory (CSV)</a>
    <a href="duplicates.csv">Ignored duplicate URLs (CSV)</a>
    <a href="excluded.csv">Excluded from playlist (CSV)</a>
    <a href="audit.csv">Manual verification (CSV)</a>
    <a href="report.json">Machine report (JSON)</a>
  </div>

  <div class="cards">
    <div class="card"><div class="value">{total_channels}</div><div class="label">Unique channels</div></div>
    <div class="card"><div class="value">{total_streams}</div><div class="label">Unique stream URLs</div></div>
    <div class="card"><div class="value">{added_from_nonbase}</div><div class="label">Channels added beyond base</div></div>
    <div class="card"><div class="value">{total_alternatives}</div><div class="label">Alternative streams kept</div></div>
    <div class="card"><div class="value">{total_duplicates}</div><div class="label">Duplicate URLs ignored</div></div>
  </div>

  {audit_warning_html}

  <h2>Manual verification</h2>
  <p class="muted">
    This is our persistent playback test log. “Verified” means it worked in both VLC
    and the Samsung test. “TV verified” means Samsung worked even if VLC did not;
    “PC only” means VLC worked but Samsung did not. Provenance is tracked separately,
    so these labels are not legal certifications.
  </p>

  <div class="audit-summary">
    <div class="card"><div class="value">{len(audit_current)}</div><div class="label">Channels/streams in testing queue</div></div>
    <div class="card"><div class="value">{audit_both_tested}</div><div class="label">Tested on both devices</div></div>
    <div class="card"><div class="value">{audit_vlc_pending}</div><div class="label">VLC tests remaining</div></div>
    <div class="card"><div class="value">{audit_samsung_pending}</div><div class="label">Samsung tests remaining</div></div>
    <div class="card"><div class="value">{audit_verified}</div><div class="label">✓ Verified both</div></div>
    <div class="card"><div class="value">{audit_tv_verified}</div><div class="label">TV verified</div></div>
    <div class="card"><div class="value">{audit_pc_only}</div><div class="label">PC only</div></div>
    <div class="card"><div class="value">{audit_review}</div><div class="label">? Needs review</div></div>
    <div class="card"><div class="value">{audit_rejected}</div><div class="label">✕ Rejected</div></div>
  </div>

  <div class="controls">
    <input id="auditSearch" type="search" placeholder="Search manual tests...">
    <select id="auditDecisionFilter">
      <option value="">All manual decisions</option>
      <option value="Verified">Verified</option>
      <option value="TV verified">TV verified</option>
      <option value="PC only">PC only</option>
      <option value="Needs review">Needs review</option>
      <option value="Rejected">Rejected</option>
    </select>
    <select id="auditVlcFilter">
      <option value="">All VLC statuses</option>
      <option value="works">VLC works</option>
      <option value="works_with_warning">VLC works with warning</option>
      <option value="loads">VLC keeps loading</option>
      <option value="mrl_error">VLC MRL error</option>
      <option value="wrong_language">VLC wrong language</option>
      <option value="not_tested">VLC not tested</option>
    </select>
    <select id="auditSamsungFilter">
      <option value="">All Samsung statuses</option>
      <option value="works">Samsung works</option>
      <option value="format_error">Samsung unsupported format</option>
      <option value="generic_error">Samsung generic error</option>
      <option value="loads">Samsung keeps loading</option>
      <option value="wrong_language">Samsung wrong language</option>
      <option value="not_tested">Samsung not tested</option>
    </select>
  </div>
  <p id="auditVisibleCount" class="muted"></p>

  <div class="table-wrap">
    <table id="auditTable">
      <thead>
        <tr>
          <th>Channel</th>
          <th>Feed</th>
          <th>TVG ID</th>
          <th>Source</th>
          <th>Discovery</th>
          <th>Protocol</th>
          <th>Expected language</th>
          <th>Observed language</th>
          <th>Language match</th>
          <th>Provenance</th>
          <th>Source flag</th>
          <th>VLC</th>
          <th>Samsung</th>
          <th>Decision</th>
          <th>In test playlist</th>
          <th>In stable family playlist</th>
          <th>Reason / notes</th>
          <th>URL</th>
        </tr>
      </thead>
      <tbody>{''.join(audit_table_rows)}</tbody>
    </table>
  </div>

  <h2>Language summary</h2>

  <p class="muted">
    Counts are based on the final published playlist.
    Base channels come from sources whose kind is "base".
    Added channels were first discovered by non-base sources.
  </p>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Language</th>
          <th>Sources</th>
          <th>Base sources</th>
          <th>Unique channels</th>
          <th>Stream URLs</th>
          <th>Base channels</th>
          <th>Added channels</th>
          <th>Alternative streams</th>
        </tr>
      </thead>

      <tbody>
        {language_rows}
      </tbody>
    </table>
  </div>
  
  <h2>Source contribution</h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Source</th>
          <th>Language</th>
          <th>Kind</th>
          <th>Raw entries</th>
          <th>Unique channels in source</th>
          <th>Stream URLs kept</th>
          <th>Base channels</th>
          <th>Added channels</th>
          <th>Alternative streams</th>
          <th>Duplicate URLs ignored</th>
        </tr>
      </thead>
      <tbody>{source_rows}</tbody>
    </table>
  </div>

  <h2>Changes since previous build</h2>
  {change_html}

  <h2>Channel inventory</h2>
  <p class="muted">
    “Base channel” means the channel was first introduced by a source
    whose kind is "base".
    “Added channel” means it was first introduced by a non-base source,
    such as alternatives or extras.
    “Alternative stream” means the logical channel already existed and
    another source supplied a different stream URL.
  </p>

  <div class="controls">
    <input id="search" type="search" placeholder="Search channel, TVG ID, group or URL...">
    <select id="sourceFilter">
      <option value="">All sources</option>
      {source_options}
    </select>
    <select id="statusFilter">
      <option value="">All classifications</option>
      <option value="Base channel">Base channel</option>
      <option value="Added channel">Added channel</option>
      <option value="Alternative stream">Alternative stream</option>
    </select>
  </div>

  <p id="visibleCount" class="muted"></p>

  <div class="table-wrap">
    <table id="channels">
      <thead>
        <tr>
          <th>Channel</th>
          <th>TVG ID</th>
          <th>Group</th>
          <th>Source</th>
          <th>Result</th>
          <th>URL</th>
        </tr>
      </thead>
      <tbody>
        {''.join(channel_rows)}
      </tbody>
    </table>
  </div>
</main>

<script>
const search = document.getElementById('search');
const sourceFilter = document.getElementById('sourceFilter');
const statusFilter = document.getElementById('statusFilter');
const rows = Array.from(document.querySelectorAll('#channels tbody tr'));
const visibleCount = document.getElementById('visibleCount');

function applyFilters() {{
  const q = search.value.trim().toLowerCase();
  const source = sourceFilter.value;
  const status = statusFilter.value;
  let shown = 0;

  for (const row of rows) {{
    const matchesText = !q || row.innerText.toLowerCase().includes(q);
    const matchesSource = !source || row.dataset.source === source;
    const matchesStatus = !status || row.dataset.status === status;
    const show = matchesText && matchesSource && matchesStatus;
    row.style.display = show ? '' : 'none';
    if (show) shown++;
  }}

  visibleCount.textContent = `Showing ${{shown}} of ${{rows.length}} stream entries`;
}}

const auditSearch = document.getElementById('auditSearch');
const auditDecisionFilter = document.getElementById('auditDecisionFilter');
const auditVlcFilter = document.getElementById('auditVlcFilter');
const auditSamsungFilter = document.getElementById('auditSamsungFilter');
const auditRows = Array.from(document.querySelectorAll('#auditTable tbody tr'));
const auditVisibleCount = document.getElementById('auditVisibleCount');

function applyAuditFilters() {{
  const q = auditSearch.value.trim().toLowerCase();
  const decision = auditDecisionFilter.value;
  const vlc = auditVlcFilter.value;
  const samsung = auditSamsungFilter.value;
  let shown = 0;

  for (const row of auditRows) {{
    const matchesText = !q || row.innerText.toLowerCase().includes(q);
    const matchesDecision = !decision || row.dataset.auditDecision === decision;
    const matchesVlc = !vlc || row.dataset.auditVlc === vlc;
    const matchesSamsung = !samsung || row.dataset.auditSamsung === samsung;
    const show = matchesText && matchesDecision && matchesVlc && matchesSamsung;
    row.style.display = show ? '' : 'none';
    if (show) shown++;
  }}

  auditVisibleCount.textContent = `Showing ${{shown}} of ${{auditRows.length}} manually reviewed/candidate channels`;
}}

auditSearch.addEventListener('input', applyAuditFilters);
auditDecisionFilter.addEventListener('change', applyAuditFilters);
auditVlcFilter.addEventListener('change', applyAuditFilters);
auditSamsungFilter.addEventListener('change', applyAuditFilters);
applyAuditFilters();

search.addEventListener('input', applyFilters);
sourceFilter.addEventListener('change', applyFilters);
statusFilter.addEventListener('change', applyFilters);
applyFilters();
</script>
</body>
</html>
"""


def main(strict: bool = False) -> None:
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    audit_items = load_audit(cfg.get("audit_path", "audit.json"))

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

        language_code = (
            normalize_language_code(
                str(
                    spec.get("language_code")
                    or cfg.get(
                        "default_language_code"
                    )
                    or "HU"
                )
            )
            or "HU"
        )

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

        source_keys = {channel_key(e) for e in entries}
        kept = 0
        new_channels = 0

        base_channels = 0
        added_channels = 0
        alternatives = 0

        duplicate_urls = 0

        for entry in entries:
            url = (entry.get("url") or "").strip()
            if not url:
                continue

            url_key = canonical_stream_url(url)
            key = channel_key(entry)
            clean_name = strip_display_annotations(entry.get("display_name", ""))
            entry["channel_key"] = key
            entry["channel_name"] = clean_name
            entry["source"] = name
            entry["source_kind"] = kind
            entry["language_code"] = language_code
            logical_key = logical_channel_key(entry)

            country_name = str(
                spec.get("country_name")
                or country_name_for_language(
                    cfg,
                    language_code,
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
                language_code=language_code,
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
                    "first_source": name,
                    "first_source_kind": kind,
                    "language_code": (
                        language_code
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
            "language_code": language_code,
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

    audit_rows = prepare_audit_rows(audit_items, final_entries)
    test_candidates = (
        make_test_playlist_candidates(
            final_entries,
            audit_rows,
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
            "language_code": entry.get("language_code", ""),
            "name": entry["channel_name"],
            "tvg_id": entry.get("tvg_id", ""),
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

    language_stats = (
        summarize_language_stats(
            published_entries,
            source_stats,
        )
    )
	
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
                r"[A-Z]{2,3}:(?:id|name):.+",
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

    # Main stable family playlist.
    write_m3u_playlist(
        out_path,
        cfg,
        published_entries,
        generated,
        "Stable family playlist",
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
        raw_language_code,
        relative_path,
    ) in country_outputs.items():
        language_code = (
            normalize_language_code(
                str(
                    raw_language_code
                )
            )
            or str(
                raw_language_code
            ).strip().upper()
        )

        country_entries = [
            entry
            for entry
            in published_entries
            if str(
                entry.get(
                    "language_code"
                )
                or ""
            ).upper()
            == language_code
        ]

        country_path = (
            ROOT
            / str(
                relative_path
            )
        )

        country_name = (
            country_name_for_language(
                cfg,
                language_code,
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
        )

        country_playlist_counts[
            language_code
        ] = len(
            country_entries
        )

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

            "country_name",
            "content_group",
            "source_group_title",
            "group_title",

            "test_status",
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

            "expected_language_codes",
            "observed_language_codes",
            "language_match",

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
        "schema_version": 19,
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
        "languages": language_stats,

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

    (public_dir / "index.html").write_text(
        make_dashboard(
            cfg=cfg,
            generated=generated,
            final_entries=published_entries,
            unique_channels=unique_channels,
            source_stats=source_stats,
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
        language_code,
        stream_count,
    ) in sorted(
        country_playlist_counts.items()
    ):
        print(
            f"Stable {language_code}:"
            f"{' ' * max(1, 15 - len(language_code))}"
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
            f"- [{stats['language_code']}] "
            f"{stats['name']} "
            f"({stats['kind']}): "
            f"{stats['raw_entries']} raw, "
            f"{stats['base_channels_contributed']} base, "
            f"{stats['added_channels_contributed']} added, "
            f"{stats['alternative_streams']} alternatives, "
            f"{stats['duplicate_urls_ignored']} duplicate URLs ignored"
        )

    if language_stats:
        print()
        print("Language summary:")

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
