#!/usr/bin/env python3
from __future__ import annotations

import copy
import gzip
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


QUALITY_PAREN_RE = re.compile(
    r"\s*[\[(]\s*(?:FHD|HD|SD|UHD|4K)(?:\s*/\s*(?:FHD|HD|SD|UHD|4K))*\s*[\])]\s*",
    re.IGNORECASE,
)
QUALITY_SUFFIX_RE = re.compile(
    r"\s+(?:FHD|HD|SD|UHD|4K)$",
    re.IGNORECASE,
)


def _load_xml(path: Path) -> ET.Element:
    data = path.read_bytes()
    if data.startswith(b"\x1f\x8b"):
        data = gzip.decompress(data)
    root = ET.fromstring(data)
    if root.tag != "tv":
        raise RuntimeError(f"Invalid XMLTV root in {path}: {root.tag!r}")
    return root


def _source_name_key(value: str) -> str:
    value = str(value or "").strip()
    value = QUALITY_PAREN_RE.sub(" ", value)
    value = QUALITY_SUFFIX_RE.sub("", value)
    value = value.casefold()
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _channel_name_keys(channel: ET.Element) -> set[str]:
    keys: set[str] = set()
    for display_name in channel.findall("display-name"):
        key = _source_name_key(display_name.text or "")
        if key:
            keys.add(key)
    return keys


def _cached_fallback_path(
    external_dir: Path,
    country_code: str,
    index: int,
) -> Path:
    return external_dir / f"{country_code}.fallback{index}.xml.gz"


def _download_xmltv(url: str, destination: Path) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")

    for attempt in range(1, 3):
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "tomas-iptv/epg"},
            )
            with urllib.request.urlopen(request, timeout=45) as response:
                temporary.write_bytes(response.read())
            _load_xml(temporary)
            temporary.replace(destination)
            return True
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            print(
                "WARNING: external EPG fallback download failed "
                f"(attempt {attempt}/2): {url}: {exc}"
            )

    return False


def _usable_cached_source(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        _load_xml(path)
        return True
    except Exception as exc:
        print(f"WARNING: ignoring invalid cached external EPG {path}: {exc}")
        path.unlink(missing_ok=True)
        return False


def _combine_xmltv_sources(
    sources: list[Path],
    output_path: Path,
) -> dict[str, int]:
    if not sources:
        raise ValueError("At least one XMLTV source is required.")

    roots = [_load_xml(path) for path in sources]
    combined = ET.Element("tv", dict(roots[0].attrib))

    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    seen_programmes: set[tuple[str, str, str]] = set()
    fallback_channels_added = 0
    fallback_programmes_added = 0

    for source_index, root in enumerate(roots):
        programmes_by_channel: dict[str, list[ET.Element]] = {}
        for programme in root.findall("programme"):
            channel_id = str(programme.get("channel") or "").strip()
            if channel_id:
                programmes_by_channel.setdefault(channel_id, []).append(programme)

        accepted_ids: set[str] = set()
        for channel in root.findall("channel"):
            channel_id = str(channel.get("id") or "").strip()
            if not channel_id:
                continue

            name_keys = _channel_name_keys(channel)
            if source_index > 0 and (
                channel_id in seen_ids
                or bool(name_keys & seen_names)
            ):
                continue

            if channel_id in seen_ids:
                continue

            combined.append(copy.deepcopy(channel))
            seen_ids.add(channel_id)
            seen_names.update(name_keys)
            accepted_ids.add(channel_id)
            if source_index > 0:
                fallback_channels_added += 1

        for channel_id in accepted_ids:
            for programme in programmes_by_channel.get(channel_id, []):
                key = (
                    channel_id,
                    str(programme.get("start") or ""),
                    str(programme.get("stop") or ""),
                )
                if key in seen_programmes:
                    continue
                seen_programmes.add(key)
                combined.append(copy.deepcopy(programme))
                if source_index > 0:
                    fallback_programmes_added += 1

    ET.indent(combined, space="  ")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    xml_bytes = ET.tostring(
        combined,
        encoding="utf-8",
        xml_declaration=True,
    )
    output_path.write_bytes(gzip.compress(xml_bytes))

    return {
        "fallback_channels_added": fallback_channels_added,
        "fallback_programmes_added": fallback_programmes_added,
    }


def prepare_external_guide(
    primary_path: Path | None,
    external_dir: Path | None,
    country_code: str,
    external_cfg: dict,
) -> tuple[Path | None, dict[str, int]]:
    """Materialize a priority-ordered external guide with additive fallbacks.

    The already-downloaded primary guide remains authoritative. Fallback feeds
    only contribute channels whose IDs and quality-neutral display names do not
    collide with an earlier source, preventing a second feed from creating
    ambiguous mappings for channels already covered by the primary source.
    """
    raw_urls = external_cfg.get("fallback_urls") or []
    if isinstance(raw_urls, str):
        raw_urls = [raw_urls]
    fallback_urls = [
        str(value or "").strip()
        for value in raw_urls
        if str(value or "").strip()
    ]

    stats = {
        "fallback_sources_configured": len(fallback_urls),
        "fallback_sources_available": 0,
        "fallback_channels_added": 0,
        "fallback_programmes_added": 0,
    }

    sources: list[Path] = []
    if primary_path is not None and _usable_cached_source(primary_path):
        sources.append(primary_path)

    if external_dir is not None:
        code = str(country_code or "").strip().upper()
        for index, url in enumerate(fallback_urls, start=1):
            destination = _cached_fallback_path(external_dir, code, index)
            if not _usable_cached_source(destination):
                _download_xmltv(url, destination)
            if _usable_cached_source(destination):
                sources.append(destination)
                stats["fallback_sources_available"] += 1

    if not sources:
        return None, stats
    if len(sources) == 1:
        return sources[0], stats

    combined_path = external_dir / ".combined" / f"{country_code.upper()}.xml.gz"
    merge_stats = _combine_xmltv_sources(sources, combined_path)
    stats.update(merge_stats)
    print(
        f"External EPG {country_code.upper()}: added "
        f"{stats['fallback_channels_added']} fallback channels and "
        f"{stats['fallback_programmes_added']} programme entries."
    )
    return combined_path, stats
