from __future__ import annotations

import re
import urllib.request
from pathlib import Path


ATTR_RE = re.compile(r'([A-Za-z0-9_-]+)="([^"]*)"')
VALID_SOURCE_KINDS = {
    "base",
    "alternatives",
    "extras",
    "source",
}


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


def read_local(root: Path, path: str) -> str:
    source_path = root / path
    if not source_path.is_file():
        raise RuntimeError(f"Required local source {path} not found")
    return source_path.read_text(encoding="utf-8-sig")


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


def normalize_source_kind(
    value: str,
    default: str = "source",
) -> str:
    """Normalize and validate one configured source kind."""
    raw = str(value or default).strip().casefold()
    raw = raw.replace("-", "_").replace(" ", "_")

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
        allowed = ", ".join(sorted(VALID_SOURCE_KINDS))
        raise RuntimeError(
            f"Unsupported source kind {value!r}. Allowed kinds: {allowed}."
        )
    return normalized


def source_spec(
    item,
    default_name: str,
    kind: str,
) -> dict:
    """Normalize old string and modern object source definitions."""
    default_kind = normalize_source_kind(kind)

    if isinstance(item, str):
        key = "url" if item.startswith(("http://", "https://")) else "path"
        return {
            "name": default_name,
            "kind": default_kind,
            key: item,
        }

    if isinstance(item, dict):
        result = dict(item)
        result.setdefault("name", default_name)
        result["kind"] = normalize_source_kind(
            result.get("kind"),
            default=default_kind,
        )
        return result

    raise TypeError(f"Unsupported source definition: {item!r}")
