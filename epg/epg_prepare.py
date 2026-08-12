#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


ATTR_RE = re.compile(
    r'([A-Za-z0-9_-]+)="([^"]*)"'
)

QUALITY_VARIANT_RE = re.compile(
    r'@(SD|HD|FHD|UHD|4K|\d{3,4}P)$',
    re.IGNORECASE,
)


def quality_base_id(value: str) -> str:
    """
    Remove only video-quality suffixes from an IPTV-org tvg-id.

    Examples:

        M1.hu@SD -> m1.hu
        M1.hu@HD -> m1.hu

    Region variants such as @Hungary or @Europe are deliberately
    left untouched.
    """
    return QUALITY_VARIANT_RE.sub(
        "",
        (value or "").strip(),
    ).casefold()


def read_playlist_tvg_ids(
    path: Path,
) -> list[str]:
    """
    Read unique non-empty tvg-id values from the generated playlist.
    """
    result: list[str] = []
    seen: set[str] = set()

    for raw_line in path.read_text(
        encoding="utf-8-sig"
    ).splitlines():
        line = raw_line.strip()

        if not line.startswith("#EXTINF:"):
            continue

        attrs = {
            key.casefold(): value.strip()
            for key, value
            in ATTR_RE.findall(line)
        }

        tvg_id = attrs.get(
            "tvg-id",
            "",
        ).strip()

        if not tvg_id:
            continue

        key = tvg_id.casefold()

        if key in seen:
            continue

        seen.add(key)
        result.append(tvg_id)

    return result


def load_provider_channels(
    epg_root: Path,
    sites: list[str],
) -> tuple[
    dict[str, dict[str, str]],
    dict[str, dict[str, str]],
]:
    """
    Load channel mappings from the selected IPTV-org EPG sites.

    Site order acts as provider priority when two providers offer
    the same XMLTV ID.
    """
    exact: dict[
        str,
        dict[str, str],
    ] = {}

    quality_base: dict[
        str,
        dict[str, str],
    ] = {}

    for site in sites:
        site_dir = (
            epg_root
            / "sites"
            / site
        )

        files = sorted(
            site_dir.glob(
                "*.channels.xml"
            )
        )

        if not files:
            raise RuntimeError(
                "No channel file found "
                f"for EPG site: {site}"
            )

        for file_path in files:
            root = ET.parse(
                file_path
            ).getroot()

            for node in root.findall(
                "channel"
            ):
                source_xmltv_id = (
                    node.get(
                        "xmltv_id"
                    )
                    or ""
                ).strip()

                site_id = (
                    node.get(
                        "site_id"
                    )
                    or ""
                ).strip()

                source_site = (
                    node.get(
                        "site"
                    )
                    or site
                ).strip()

                lang = (
                    node.get(
                        "lang"
                    )
                    or ""
                ).strip()

                name = " ".join(
                    (
                        node.text
                        or ""
                    ).split()
                )

                # Blank xmltv_id entries cannot safely be linked
                # to our M3U playlist.
                if (
                    not source_xmltv_id
                    or not site_id
                    or not source_site
                    or not lang
                    or not name
                ):
                    continue

                item = {
                    "site": source_site,
                    "site_id": site_id,
                    "lang": lang,
                    "name": name,
                    "source_xmltv_id": (
                        source_xmltv_id
                    ),
                }

                # setdefault means an earlier site in config.json
                # wins when providers contain the same ID.
                exact.setdefault(
                    source_xmltv_id.casefold(),
                    item,
                )

                quality_base.setdefault(
                    quality_base_id(
                        source_xmltv_id
                    ),
                    item,
                )

    return (
        exact,
        quality_base,
    )


def prepare_epg_channels(
    playlist_path: Path,
    epg_root: Path,
    sites: list[str],
    output_path: Path,
    report_path: Path,
) -> dict:
    """
    Generate a custom IPTV-org channels.xml containing only channels
    that actually occur in our final tv.m3u.
    """
    playlist_ids = (
        read_playlist_tvg_ids(
            playlist_path
        )
    )

    (
        exact,
        quality_base,
    ) = load_provider_channels(
        epg_root,
        sites,
    )

    channels_root = ET.Element(
        "channels"
    )

    matched: list[
        dict[str, str]
    ] = []

    unmatched: list[str] = []

    providers: Counter[str] = (
        Counter()
    )

    for playlist_tvg_id in (
        playlist_ids
    ):
        candidate = exact.get(
            playlist_tvg_id.casefold()
        )

        match_type = "exact"

        if candidate is None:
            candidate = (
                quality_base.get(
                    quality_base_id(
                        playlist_tvg_id
                    )
                )
            )

            match_type = (
                "quality_variant"
            )

        if candidate is None:
            unmatched.append(
                playlist_tvg_id
            )
            continue

        # IMPORTANT:
        #
        # xmltv_id is deliberately changed to the exact tvg-id
        # used by OUR playlist.
        #
        # For example, if the provider knows M1.hu@SD but our
        # playlist contains M1.hu@HD, the generated XMLTV guide
        # will use M1.hu@HD so the IPTV client can match it.
        attrs = {
            "site": (
                candidate["site"]
            ),
            "lang": (
                candidate["lang"]
            ),
            "xmltv_id": (
                playlist_tvg_id
            ),
            "site_id": (
                candidate["site_id"]
            ),
        }

        child = ET.SubElement(
            channels_root,
            "channel",
            attrs,
        )

        child.text = (
            candidate["name"]
        )

        providers[
            candidate["site"]
        ] += 1

        matched.append({
            "tvg_id": (
                playlist_tvg_id
            ),
            "provider": (
                candidate["site"]
            ),
            "provider_xmltv_id": (
                candidate[
                    "source_xmltv_id"
                ]
            ),
            "match_type": (
                match_type
            ),
        })

    if not matched:
        raise RuntimeError(
            "No playlist tvg-id values "
            "matched the configured EPG sites."
        )

    tree = ET.ElementTree(
        channels_root
    )

    ET.indent(
        tree,
        space="  ",
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    tree.write(
        output_path,
        encoding="utf-8",
        xml_declaration=True,
    )

    total = len(
        playlist_ids
    )

    coverage = (
        len(matched)
        / total
        * 100.0
        if total
        else 0.0
    )

    report = {
        "playlist_tvg_ids": (
            total
        ),
        "matched_tvg_ids": (
            len(matched)
        ),
        "unmatched_tvg_ids_count": (
            len(unmatched)
        ),
        "mapping_coverage_percent": (
            round(
                coverage,
                1,
            )
        ),
        "providers": dict(
            sorted(
                providers.items()
            )
        ),
        "matched": matched,
        "unmatched_tvg_ids": (
            unmatched
        ),
    }

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        "Prepared "
        f"{len(matched)} "
        "EPG mappings from "
        f"{total} playlist "
        "tvg-id values "
        f"({coverage:.1f}% "
        "mapping coverage)."
    )

    if unmatched:
        print(
            "Unmatched tvg-id "
            f"values: {len(unmatched)}"
        )

        for tvg_id in (
            unmatched[:25]
        ):
            print(
                f"  - {tvg_id}"
            )

        if len(unmatched) > 25:
            print(
                "  ... and "
                f"{len(unmatched) - 25} "
                "more"
            )

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build a custom IPTV-org "
            "EPG channel list for the "
            "tvg-id values in tv.m3u."
        )
    )

    parser.add_argument(
        "--playlist",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--epg-root",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--sites",
        required=True,
    )

    parser.add_argument(
        "--output",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--report",
        required=True,
        type=Path,
    )

    args = parser.parse_args()

    sites = [
        site.strip()
        for site
        in args.sites.split(",")
        if site.strip()
    ]

    if not sites:
        raise SystemExit(
            "No EPG sites were configured."
        )

    prepare_epg_channels(
        playlist_path=(
            args.playlist
        ),
        epg_root=(
            args.epg_root
        ),
        sites=sites,
        output_path=(
            args.output
        ),
        report_path=(
            args.report
        ),
    )


if __name__ == "__main__":
    main()
