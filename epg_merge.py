#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import gzip
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from epg_prepare import quality_base_id


ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
STATUS_PREFIX_RE = re.compile(
    r"^\[[A-Z]{2}\s+[^\]]+\]\s*",
    re.IGNORECASE,
)
RESOLUTION_RE = re.compile(
    r"\s*[\[(]\s*\d{3,4}p\s*[\])]\s*",
    re.IGNORECASE,
)
NOT_247_RE = re.compile(
    r"\s*\[Not\s+24/7\]\s*",
    re.IGNORECASE,
)
HD_SUFFIX_RE = re.compile(
    r"\s+HD$",
    re.IGNORECASE,
)

METHOD_RANK = {
    "external_explicit_alias": 4,
    "external_exact_id": 3,
    "external_quality_id": 2,
    "external_unique_name": 1,
}


def read_playlist_rows(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    pending: tuple[str, str] | None = None

    for raw_line in path.read_text(
        encoding="utf-8-sig"
    ).splitlines():
        line = raw_line.strip()

        if line.startswith("#EXTINF:"):
            attrs = dict(
                ATTR_RE.findall(line)
            )
            tvg_id = (
                attrs.get("tvg-id")
                or ""
            ).strip()
            name = (
                line.rsplit(",", 1)[-1].strip()
                if "," in line
                else ""
            )
            pending = (
                tvg_id,
                name,
            )
            continue

        if (
            line
            and not line.startswith("#")
            and pending is not None
        ):
            if pending[0]:
                rows.append(pending)
            pending = None

    by_id: dict[str, str] = {}
    for tvg_id, name in rows:
        by_id.setdefault(
            tvg_id,
            name,
        )

    return list(
        by_id.items()
    )


def channel_name_key(value: str) -> str:
    """
    Normalize only known generated metadata around a channel name.

    This deliberately does NOT do fuzzy matching or accent folding.
    """
    value = unicodedata.normalize(
        "NFKC",
        value or "",
    ).strip()

    value = STATUS_PREFIX_RE.sub(
        "",
        value,
    )
    value = NOT_247_RE.sub(
        " ",
        value,
    )
    value = RESOLUTION_RE.sub(
        " ",
        value,
    )
    value = HD_SUFFIX_RE.sub(
        "",
        value,
    )

    value = value.casefold()
    value = re.sub(
        r"[^\w]+",
        " ",
        value,
        flags=re.UNICODE,
    )

    return " ".join(
        value.split()
    )


def load_xml(path: Path) -> ET.Element:
    data = path.read_bytes()
    if data.startswith(b"\x1f\x8b"):
        data = gzip.decompress(data)

    root = ET.fromstring(data)
    if root.tag != "tv":
        raise RuntimeError(
            f"Invalid XMLTV root in {path}: {root.tag!r}"
        )
    return root


def programme_date(
    programme: ET.Element,
) -> date | None:
    value = (
        programme.get("start")
        or ""
    ).strip()

    match = re.match(
        r"(\d{8})",
        value,
    )
    if not match:
        return None

    try:
        return datetime.strptime(
            match.group(1),
            "%Y%m%d",
        ).date()
    except ValueError:
        return None


def is_fresh_programme(
    programme: ET.Element,
    reference_date: date,
    future_days: int,
) -> bool:
    value = programme_date(
        programme
    )
    if value is None:
        return False

    return (
        reference_date
        <= value
        <= reference_date
        + timedelta(days=future_days)
    )


def build_external_mapping(
    playlist_rows: list[tuple[str, str]],
    external_root: ET.Element,
    explicit_aliases: dict[str, str] | None = None,
) -> tuple[
    dict[str, dict[str, str]],
    list[dict[str, object]],
]:
    exact = {
        tvg_id.casefold(): tvg_id
        for tvg_id, _ in playlist_rows
    }

    quality: dict[
        str,
        list[str],
    ] = defaultdict(list)

    names: dict[
        str,
        list[str],
    ] = defaultdict(list)

    for tvg_id, name in playlist_rows:
        quality[
            quality_base_id(tvg_id)
        ].append(tvg_id)

        key = channel_name_key(
            name
        )
        if key:
            names[key].append(
                tvg_id
            )

    proposals: dict[
        str,
        list[dict[str, str]],
    ] = defaultdict(list)

    playlist_id_set = {
        tvg_id
        for tvg_id, _
        in playlist_rows
    }
    external_id_set = {
        (channel.get("id") or "").strip()
        for channel
        in external_root.findall("channel")
        if (channel.get("id") or "").strip()
    }

    # Explicit aliases are hand-audited identities. They intentionally outrank
    # all generated matching methods. Missing historical aliases are ignored
    # safely when either side is not present in the current inputs.
    for target, external_id in (explicit_aliases or {}).items():
        target = str(target or "").strip()
        external_id = str(external_id or "").strip()
        if (
            not target
            or not external_id
            or target not in playlist_id_set
            or external_id not in external_id_set
        ):
            continue
        proposals[target].append({
            "external_id": external_id,
            "method": "external_explicit_alias",
        })

    for channel in external_root.findall(
        "channel"
    ):
        external_id = (
            channel.get("id")
            or ""
        ).strip()
        if not external_id:
            continue

        target = exact.get(
            external_id.casefold()
        )
        method = (
            "external_exact_id"
        )

        if target is None:
            candidates = quality.get(
                quality_base_id(
                    external_id
                ),
                [],
            )
            if len(candidates) == 1:
                target = candidates[0]
                method = (
                    "external_quality_id"
                )

        if target is None:
            candidates: set[str] = set()
            for display_name in channel.findall(
                "display-name"
            ):
                key = channel_name_key(
                    display_name.text
                    or ""
                )
                if key:
                    candidates.update(
                        names.get(
                            key,
                            [],
                        )
                    )

            if len(candidates) == 1:
                target = next(
                    iter(candidates)
                )
                method = (
                    "external_unique_name"
                )

        if target is not None:
            proposals[target].append({
                "external_id": (
                    external_id
                ),
                "method": method,
            })

    mapping: dict[
        str,
        dict[str, str],
    ] = {}
    ambiguous: list[
        dict[str, object]
    ] = []

    for target, items in proposals.items():
        best_rank = max(
            METHOD_RANK[
                item["method"]
            ]
            for item in items
        )
        best = [
            item
            for item in items
            if METHOD_RANK[
                item["method"]
            ] == best_rank
        ]

        if len(best) != 1:
            # When the playlist explicitly asks for @SD or @HD and the
            # external guide contains otherwise-identical HD/non-HD entries,
            # resolve only that declared quality variant. This is not fuzzy
            # matching: all candidates already matched the same channel name.
            variant = re.search(
                r"@(SD|HD)(?:$|@)",
                target,
                re.IGNORECASE,
            )
            if variant:
                wants_hd = (
                    variant.group(1).upper() == "HD"
                )
                quality_matches = [
                    candidate
                    for candidate in best
                    if bool(
                        re.search(
                            r"(?:^|[._-])HD(?:[._-]|$)",
                            candidate["external_id"],
                            re.IGNORECASE,
                        )
                    ) == wants_hd
                ]
                if len(quality_matches) == 1:
                    best = quality_matches

        if len(best) != 1:
            ambiguous.append({
                "tvg_id": target,
                "candidates": best,
            })
            continue

        item = best[0]
        mapping[
            item["external_id"]
        ] = {
            "tvg_id": target,
            "method": item[
                "method"
            ],
        }

    return (
        mapping,
        ambiguous,
    )


def programme_index(
    root: ET.Element,
) -> dict[str, list[ET.Element]]:
    result: dict[
        str,
        list[ET.Element],
    ] = defaultdict(list)

    for programme in root.findall(
        "programme"
    ):
        channel_id = (
            programme.get("channel")
            or ""
        ).strip()
        if channel_id:
            result[channel_id].append(
                programme
            )

    return result


def channel_index(
    root: ET.Element,
) -> dict[str, ET.Element]:
    result: dict[
        str,
        ET.Element,
    ] = {}

    for channel in root.findall(
        "channel"
    ):
        channel_id = (
            channel.get("id")
            or ""
        ).strip()
        if channel_id:
            result.setdefault(
                channel_id,
                channel,
            )

    return result


def fresh_count(
    programmes: list[ET.Element],
    reference_date: date,
    future_days: int,
) -> int:
    return sum(
        1
        for programme in programmes
        if is_fresh_programme(
            programme,
            reference_date,
            future_days,
        )
    )


def merge_guides(
    playlist_path: Path,
    iptv_guide_path: Path,
    iptv_coverage_path: Path,
    output_path: Path,
    report_path: Path,
    external_path: Path | None = None,
    external_provider: str = "epgshare01.online",
    preferred_iptv_provider: str = "mediaklikk.hu",
    reference_date: date | None = None,
    future_days: int = 7,
    external_aliases: dict[str, str] | None = None,
) -> dict:
    if reference_date is None:
        reference_date = datetime.now(
            ZoneInfo(
                "Europe/Budapest"
            )
        ).date()

    playlist_rows = read_playlist_rows(
        playlist_path
    )
    playlist_ids = [
        tvg_id
        for tvg_id, _ in playlist_rows
    ]
    playlist_set = set(
        playlist_ids
    )

    iptv_root = load_xml(
        iptv_guide_path
    )
    iptv_channels = channel_index(
        iptv_root
    )
    iptv_programmes = programme_index(
        iptv_root
    )

    iptv_coverage = json.loads(
        iptv_coverage_path.read_text(
            encoding="utf-8"
        )
    )

    iptv_match: dict[
        str,
        dict,
    ] = {}
    for item in (
        iptv_coverage.get(
            "matched"
        )
        or []
    ):
        if not isinstance(
            item,
            dict,
        ):
            continue
        tvg_id = str(
            item.get("tvg_id")
            or ""
        ).strip()
        if tvg_id:
            iptv_match[
                tvg_id
            ] = item

    external_root: (
        ET.Element | None
    ) = None
    external_mapping: dict[
        str,
        dict[str, str],
    ] = {}
    external_ambiguous: list[
        dict[str, object]
    ] = []
    external_channels: dict[
        str,
        ET.Element,
    ] = {}
    external_programmes_by_source: dict[
        str,
        list[ET.Element],
    ] = {}
    external_programmes_by_target: dict[
        str,
        list[ET.Element],
    ] = defaultdict(list)
    external_source_for_target: dict[
        str,
        str,
    ] = {}
    external_method_for_target: dict[
        str,
        str,
    ] = {}
    external_fresh = False
    external_latest_date: (
        date | None
    ) = None

    if (
        external_path is not None
        and external_path.is_file()
    ):
        try:
            external_root = load_xml(
                external_path
            )
            (
                external_mapping,
                external_ambiguous,
            ) = build_external_mapping(
                playlist_rows,
                external_root,
                explicit_aliases=external_aliases,
            )
            external_channels = channel_index(
                external_root
            )
            external_programmes_by_source = programme_index(
                external_root
            )

            all_external_dates = [
                value
                for programmes
                in external_programmes_by_source.values()
                for programme in programmes
                if (
                    value := programme_date(
                        programme
                    )
                )
            ]
            if all_external_dates:
                external_latest_date = max(
                    all_external_dates
                )

            for (
                external_id,
                info,
            ) in external_mapping.items():
                tvg_id = info[
                    "tvg_id"
                ]
                programmes = (
                    external_programmes_by_source.get(
                        external_id,
                        [],
                    )
                )
                external_programmes_by_target[
                    tvg_id
                ].extend(
                    programmes
                )
                external_source_for_target[
                    tvg_id
                ] = external_id
                external_method_for_target[
                    tvg_id
                ] = info[
                    "method"
                ]

            external_fresh = any(
                fresh_count(
                    programmes,
                    reference_date,
                    future_days,
                )
                > 0
                for programmes
                in external_programmes_by_target.values()
            )

            if not external_fresh:
                print(
                    "WARNING: external EPG source has no current/future "
                    "programme data; ignoring it."
                )
        except Exception as exc:
            print(
                "WARNING: external EPG source could not be used: "
                f"{exc}"
            )
            external_root = None
            external_mapping = {}
            external_programmes_by_target = defaultdict(list)
            external_source_for_target = {}
            external_method_for_target = {}
            external_fresh = False

    selected: dict[
        str,
        dict[str, object],
    ] = {}

    for tvg_id in playlist_ids:
        iptv_item = iptv_match.get(
            tvg_id
        )
        iptv_provider = str(
            (
                iptv_item
                or {}
            ).get(
                "provider"
            )
            or ""
        ).strip()
        iptv_items = iptv_programmes.get(
            tvg_id,
            [],
        )
        iptv_fresh = fresh_count(
            iptv_items,
            reference_date,
            future_days,
        )

        ext_items = (
            external_programmes_by_target.get(
                tvg_id,
                [],
            )
            if external_fresh
            else []
        )
        ext_fresh = fresh_count(
            ext_items,
            reference_date,
            future_days,
        )

        # Prefer the broadcaster-focused mediaklikk scraper when it is
        # actually producing current data. Use the broad external feed next,
        # and horizon/other IPTV-org providers as live fallback.
        if (
            iptv_provider
            == preferred_iptv_provider
            and iptv_fresh > 0
        ):
            selected[tvg_id] = {
                "kind": "iptv",
                "provider": (
                    iptv_provider
                ),
                "programmes": (
                    iptv_items
                ),
                "fresh": iptv_fresh,
            }
            continue

        if ext_fresh > 0:
            selected[tvg_id] = {
                "kind": "external",
                "provider": (
                    external_provider
                ),
                "programmes": (
                    ext_items
                ),
                "fresh": ext_fresh,
            }
            continue

        if iptv_fresh > 0:
            selected[tvg_id] = {
                "kind": "iptv",
                "provider": (
                    iptv_provider
                    or "iptv-org"
                ),
                "programmes": (
                    iptv_items
                ),
                "fresh": iptv_fresh,
            }
            continue

        # Preserve a deterministic mapped-but-empty record so health output
        # can distinguish "known mapping" from "has current programmes".
        if (
            external_fresh
            and tvg_id
            in external_source_for_target
        ):
            selected[tvg_id] = {
                "kind": "external",
                "provider": (
                    external_provider
                ),
                "programmes": (
                    ext_items
                ),
                "fresh": 0,
            }
            continue

        if iptv_item is not None:
            selected[tvg_id] = {
                "kind": "iptv",
                "provider": (
                    iptv_provider
                    or "iptv-org"
                ),
                "programmes": (
                    iptv_items
                ),
                "fresh": 0,
            }

    output_root = ET.Element(
        "tv",
        {
            "generator-info-name": (
                "tomas-iptv merged EPG"
            ),
        },
    )

    matched: list[
        dict[str, object]
    ] = []
    provider_counts: Counter[str] = Counter()
    fresh_provider_counts: Counter[str] = Counter()

    for tvg_id in playlist_ids:
        choice = selected.get(
            tvg_id
        )
        if choice is None:
            continue

        kind = str(
            choice["kind"]
        )
        provider = str(
            choice["provider"]
        )
        provider_counts[
            provider
        ] += 1
        if int(
            choice["fresh"]
        ) > 0:
            fresh_provider_counts[
                provider
            ] += 1

        if kind == "external":
            source_id = (
                external_source_for_target.get(
                    tvg_id,
                    "",
                )
            )
            source_channel = (
                external_channels.get(
                    source_id
                )
            )
            method = (
                external_method_for_target.get(
                    tvg_id,
                    "external",
                )
            )
            match_item = {
                "tvg_id": tvg_id,
                "provider": provider,
                "provider_xmltv_id": source_id,
                "match_type": method,
                "fresh_programmes": int(
                    choice["fresh"]
                ),
            }
        else:
            source_id = tvg_id
            source_channel = (
                iptv_channels.get(
                    tvg_id
                )
            )
            match_item = dict(
                iptv_match.get(
                    tvg_id,
                    {},
                )
            )
            match_item[
                "tvg_id"
            ] = tvg_id
            match_item[
                "provider"
            ] = provider
            match_item[
                "fresh_programmes"
            ] = int(
                choice["fresh"]
            )

        if source_channel is None:
            source_channel = ET.Element(
                "channel",
                {"id": tvg_id},
            )
            display_name = ET.SubElement(
                source_channel,
                "display-name",
            )
            display_name.text = dict(
                playlist_rows
            ).get(
                tvg_id,
                tvg_id,
            )

        channel_copy = copy.deepcopy(
            source_channel
        )
        channel_copy.set(
            "id",
            tvg_id,
        )
        output_root.append(
            channel_copy
        )

        matched.append(
            match_item
        )

        seen_programmes: set[
            tuple[str, str, str]
        ] = set()
        for programme in choice[
            "programmes"
        ]:
            programme_copy = copy.deepcopy(
                programme
            )
            programme_copy.set(
                "channel",
                tvg_id,
            )
            key = (
                tvg_id,
                (
                    programme_copy.get(
                        "start"
                    )
                    or ""
                ),
                (
                    programme_copy.get(
                        "stop"
                    )
                    or ""
                ),
            )
            if key in seen_programmes:
                continue
            seen_programmes.add(
                key
            )
            output_root.append(
                programme_copy
            )

    ET.indent(
        output_root,
        space="  ",
    )
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    ET.ElementTree(
        output_root
    ).write(
        output_path,
        encoding="utf-8",
        xml_declaration=True,
    )

    matched_ids = {
        str(item["tvg_id"])
        for item in matched
    }
    unmatched = [
        tvg_id
        for tvg_id in playlist_ids
        if tvg_id not in matched_ids
    ]

    total = len(
        playlist_ids
    )
    mapped = len(
        matched
    )

    report = {
        "playlist_tvg_ids": total,
        "matched_tvg_ids": mapped,
        "mapping_coverage_percent": round(
            (
                mapped / total * 100.0
                if total
                else 0.0
            ),
            1,
        ),
        "matched": matched,
        "unmatched_tvg_ids": unmatched,
        "providers": dict(
            sorted(
                provider_counts.items()
            )
        ),
        "fresh_channels_by_provider": dict(
            sorted(
                fresh_provider_counts.items()
            )
        ),
        "reference_date": (
            reference_date.isoformat()
        ),
        "external": {
            "provider": (
                external_provider
            ),
            "available": (
                external_root is not None
            ),
            "fresh": external_fresh,
            "latest_programme_date": (
                external_latest_date.isoformat()
                if external_latest_date
                else None
            ),
            "mapped_candidates": len(
                {
                    info["tvg_id"]
                    for info
                    in external_mapping.values()
                }
            ),
            "explicit_aliases_configured": len(
                external_aliases or {}
            ),
            "ambiguous": (
                external_ambiguous
            ),
        },
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
        ) + "\n",
        encoding="utf-8",
    )

    fresh_total = sum(
        1
        for choice in selected.values()
        if int(choice["fresh"]) > 0
    )

    print(
        "Merged EPG: "
        f"{mapped}/{total} mapped, "
        f"{fresh_total}/{total} with current/future programme data."
    )
    for provider in sorted(
        provider_counts
    ):
        print(
            f"- {provider}: "
            f"{fresh_provider_counts.get(provider, 0)}/"
            f"{provider_counts[provider]} selected channels current."
        )

    if external_root is not None:
        print(
            f"External {external_provider}: "
            f"fresh={external_fresh}, "
            "latest programme date="
            f"{external_latest_date or 'unknown'}, "
            f"ambiguous mappings={len(external_ambiguous)}."
        )

    if not any(
        int(choice["fresh"]) > 0
        for choice in selected.values()
    ):
        raise RuntimeError(
            "Merged EPG contains no current/future programme data."
        )

    # Defensive invariant: never publish IDs outside the generated playlist.
    if not matched_ids.issubset(
        playlist_set
    ):
        raise RuntimeError(
            "Merged EPG contains a channel not present in the playlist."
        )

    return report


def load_external_aliases(
    path: Path | None,
    external_provider: str,
) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}

    data = json.loads(
        path.read_text(encoding="utf-8")
    )
    if not isinstance(data, dict):
        raise RuntimeError(
            "EPG alias file must contain a JSON object."
        )

    provider = str(
        data.get("provider") or ""
    ).strip()
    if (
        provider
        and provider != external_provider
    ):
        raise RuntimeError(
            "EPG alias provider mismatch: "
            f"{provider!r} != {external_provider!r}"
        )

    raw_aliases = data.get("aliases") or {}
    if not isinstance(raw_aliases, dict):
        raise RuntimeError(
            "EPG alias file 'aliases' must be a JSON object."
        )

    aliases: dict[str, str] = {}
    for raw_target, raw_external in raw_aliases.items():
        target = str(raw_target or "").strip()
        external_id = str(raw_external or "").strip()
        if not target or not external_id:
            raise RuntimeError(
                "EPG aliases may not contain blank IDs."
            )
        if target in aliases:
            raise RuntimeError(
                f"Duplicate EPG alias target: {target}"
            )
        aliases[target] = external_id

    return aliases


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Merge the broad EPGshare Hungary XMLTV feed with live "
            "IPTV-org provider fallbacks, rewriting all channel IDs to "
            "the exact tvg-id values used by the generated playlist."
        )
    )
    parser.add_argument(
        "--playlist",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--iptv-guide",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--iptv-coverage",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--external",
        type=Path,
    )
    parser.add_argument(
        "--external-provider",
        default="epgshare01.online",
    )
    parser.add_argument(
        "--aliases",
        type=Path,
        default=Path("epg_aliases.json"),
        help=(
            "Optional explicit external-ID alias file. "
            "Defaults to epg_aliases.json when present."
        ),
    )
    parser.add_argument(
        "--preferred-iptv-provider",
        default="mediaklikk.hu",
    )
    parser.add_argument(
        "--reference-date",
        type=date.fromisoformat,
    )
    parser.add_argument(
        "--future-days",
        type=int,
        default=7,
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

    external_aliases = load_external_aliases(
        args.aliases,
        args.external_provider,
    )

    merge_guides(
        playlist_path=args.playlist,
        iptv_guide_path=args.iptv_guide,
        iptv_coverage_path=args.iptv_coverage,
        external_path=args.external,
        external_provider=args.external_provider,
        preferred_iptv_provider=args.preferred_iptv_provider,
        reference_date=args.reference_date,
        future_days=max(
            args.future_days,
            0,
        ),
        external_aliases=external_aliases,
        output_path=args.output,
        report_path=args.report,
    )


if __name__ == "__main__":
    main()
