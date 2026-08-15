#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path


ATTR_RE = re.compile(r'([A-Za-z0-9_-]+)="([^"]*)"')
QUALITY_VARIANT_RE = re.compile(
    r'@(SD|HD|FHD|UHD|4K|\d{3,4}P)$',
    re.IGNORECASE,
)
NAME_QUALITY_PAREN_RE = re.compile(
    r"\s*[\[(]\s*(?:FHD|HD|SD|UHD|4K|\d{3,4}P)"
    r"(?:\s*/\s*(?:FHD|HD|SD|UHD|4K|\d{3,4}P))*\s*[\])]\s*$",
    re.IGNORECASE,
)
NAME_QUALITY_SUFFIX_RE = re.compile(
    r"\s+(?:FHD|HD|SD|UHD|4K|\d{3,4}P)\s*$",
    re.IGNORECASE,
)


def quality_base_id(value: str) -> str:
    """Remove only video-quality suffixes from an IPTV-org tvg-id."""
    return QUALITY_VARIANT_RE.sub("", (value or "").strip()).casefold()


def channel_name_key(value: str) -> str:
    """Return a conservative quality-neutral key for exact name fallback.

    This fallback is deliberately not fuzzy. It normalizes only case,
    diacritics, punctuation/spacing, and a trailing video-quality marker.
    """
    value = " ".join((value or "").split())
    previous = None
    while value and value != previous:
        previous = value
        value = NAME_QUALITY_PAREN_RE.sub("", value).strip()
        value = NAME_QUALITY_SUFFIX_RE.sub("", value).strip()

    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold()
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def _extinf_display_name(line: str) -> str:
    """Return the display name after the first non-quoted EXTINF comma."""
    quoted = False
    for index, char in enumerate(line):
        if char == '"':
            quoted = not quoted
        elif char == "," and not quoted:
            return line[index + 1 :].strip()
    return ""


def read_playlist_channels(path: Path) -> list[tuple[str, str]]:
    """Read unique non-empty tvg-id values together with display names."""
    result: list[tuple[str, str]] = []
    seen: set[str] = set()

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line.startswith("#EXTINF:"):
            continue

        attrs = {
            key.casefold(): value.strip()
            for key, value in ATTR_RE.findall(line)
        }
        tvg_id = attrs.get("tvg-id", "").strip()
        if not tvg_id:
            continue

        key = tvg_id.casefold()
        if key in seen:
            continue

        seen.add(key)
        result.append((tvg_id, _extinf_display_name(line)))

    return result


def read_playlist_tvg_ids(path: Path) -> list[str]:
    """Read unique non-empty tvg-id values from the generated playlist."""
    return [tvg_id for tvg_id, _ in read_playlist_channels(path)]


def load_provider_channels(
    epg_root: Path,
    sites: list[str],
) -> tuple[
    dict[str, dict[str, str]],
    dict[str, dict[str, str]],
    dict[str, dict[str, str]],
]:
    """Load exact, quality-variant, and safe unique-name mappings.

    Site order remains provider priority for ID matches. Name fallback is
    deliberately stricter: the normalized provider name must be unique across
    all configured selectors, and the selected row must have a blank xmltv_id.
    A non-empty but different provider ID is identity evidence that name
    fallback must not override.

    A site selector may be either a site directory (for example ``webtv.sk``)
    or one exact ``*.channels.xml`` path beneath ``sites``. The latter keeps
    multi-market providers such as Pluto scoped to a specific market file.
    """
    exact: dict[str, dict[str, str]] = {}
    quality_base: dict[str, dict[str, str]] = {}
    name_candidates: dict[
        str,
        dict[tuple[str, str, str], dict[str, str]],
    ] = defaultdict(dict)

    for site in sites:
        site_path = epg_root / "sites" / site
        if site_path.is_file():
            files = [site_path]
            default_site = site_path.parent.name
        else:
            files = sorted(site_path.glob("*.channels.xml"))
            default_site = site_path.name

        if not files:
            raise RuntimeError(
                f"No channel file found for EPG site selector: {site}"
            )

        for file_path in files:
            root = ET.parse(file_path).getroot()
            for node in root.findall("channel"):
                source_xmltv_id = (node.get("xmltv_id") or "").strip()
                site_id = (node.get("site_id") or "").strip()
                source_site = (node.get("site") or default_site).strip()
                lang = (node.get("lang") or "").strip()
                name = " ".join((node.text or "").split())

                if not site_id or not source_site or not lang or not name:
                    continue

                item = {
                    "site": source_site,
                    "site_id": site_id,
                    "lang": lang,
                    "name": name,
                    "source_xmltv_id": source_xmltv_id,
                }

                name_key = channel_name_key(name)
                if name_key:
                    fingerprint = (source_site, site_id, lang)
                    name_candidates[name_key].setdefault(fingerprint, item)

                if not source_xmltv_id:
                    continue

                # Earlier configured selectors keep priority for ID matches.
                exact.setdefault(source_xmltv_id.casefold(), item)
                quality_base.setdefault(quality_base_id(source_xmltv_id), item)

    unique_name: dict[str, dict[str, str]] = {}
    for name_key, candidates in name_candidates.items():
        if len(candidates) != 1:
            continue
        candidate = next(iter(candidates.values()))
        if candidate["source_xmltv_id"]:
            continue
        unique_name[name_key] = candidate

    return exact, quality_base, unique_name


def prepare_epg_channels(
    playlist_path: Path,
    epg_root: Path,
    sites: list[str],
    output_path: Path,
    report_path: Path,
) -> dict:
    """Generate IPTV-org channels.xml only for IDs used by our playlist."""
    playlist_channels = read_playlist_channels(playlist_path)
    playlist_ids = [tvg_id for tvg_id, _ in playlist_channels]
    exact, quality_base, unique_name = load_provider_channels(epg_root, sites)

    channels_root = ET.Element("channels")
    matched: list[dict[str, str]] = []
    unmatched: list[str] = []
    providers: Counter[str] = Counter()
    match_types: Counter[str] = Counter()

    for playlist_tvg_id, playlist_name in playlist_channels:
        candidate = exact.get(playlist_tvg_id.casefold())
        match_type = "exact"

        if candidate is None:
            candidate = quality_base.get(quality_base_id(playlist_tvg_id))
            match_type = "quality_variant"

        if candidate is None and playlist_name:
            candidate = unique_name.get(channel_name_key(playlist_name))
            match_type = "name"

        if candidate is None:
            unmatched.append(playlist_tvg_id)
            continue

        attrs = {
            "site": candidate["site"],
            "lang": candidate["lang"],
            "xmltv_id": playlist_tvg_id,
            "site_id": candidate["site_id"],
        }
        child = ET.SubElement(channels_root, "channel", attrs)
        child.text = candidate["name"]

        providers[candidate["site"]] += 1
        match_types[match_type] += 1
        matched.append({
            "tvg_id": playlist_tvg_id,
            "provider": candidate["site"],
            "provider_xmltv_id": candidate["source_xmltv_id"],
            "provider_name": candidate["name"],
            "match_type": match_type,
        })

    if not matched and playlist_ids:
        raise RuntimeError(
            "No playlist tvg-id values matched the configured EPG sites."
        )

    tree = ET.ElementTree(channels_root)
    ET.indent(tree, space="  ")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)

    total = len(playlist_ids)
    coverage = len(matched) / total * 100.0 if total else 0.0
    report = {
        "playlist_tvg_ids": total,
        "matched_tvg_ids": len(matched),
        "unmatched_tvg_ids_count": len(unmatched),
        "mapping_coverage_percent": round(coverage, 1),
        "providers": dict(sorted(providers.items())),
        "match_types": dict(sorted(match_types.items())),
        "matched": matched,
        "unmatched_tvg_ids": unmatched,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        "Prepared "
        f"{len(matched)} EPG mappings from {total} playlist tvg-id values "
        f"({coverage:.1f}% mapping coverage)."
    )
    if match_types:
        print(
            "EPG match types: "
            + ", ".join(
                f"{key}={value}" for key, value in sorted(match_types.items())
            )
        )

    if unmatched:
        print(f"Unmatched tvg-id values: {len(unmatched)}")
        for tvg_id in unmatched[:25]:
            print(f"  - {tvg_id}")
        if len(unmatched) > 25:
            print(f"  ... and {len(unmatched) - 25} more")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build a custom IPTV-org EPG channel list for the tvg-id values "
            "in a generated playlist."
        )
    )
    parser.add_argument("--playlist", required=True, type=Path)
    parser.add_argument("--epg-root", required=True, type=Path)
    parser.add_argument("--sites", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    sites = [site.strip() for site in args.sites.split(",") if site.strip()]
    if not sites:
        raise SystemExit("No EPG sites were configured.")

    prepare_epg_channels(
        playlist_path=args.playlist,
        epg_root=args.epg_root,
        sites=sites,
        output_path=args.output,
        report_path=args.report,
    )


if __name__ == "__main__":
    main()
