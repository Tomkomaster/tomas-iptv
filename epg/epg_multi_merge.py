#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date
from pathlib import Path

from epg_cross_country_alias import (
    apply_cross_country_aliases,
    load_cross_country_aliases,
)
from epg_merge import load_external_aliases, merge_guides


NO_FRESH_ERROR = "Merged EPG contains no current/future programme data."


def _external_path(external_dir: Path | None, country_code: str) -> Path | None:
    if external_dir is None:
        return None
    for name in (
        f"{country_code}.xml.gz",
        f"{country_code}.xml",
        f"{country_code}.download",
    ):
        candidate = external_dir / name
        if candidate.is_file():
            return candidate
    return None


def _percent(part: int, total: int) -> float:
    return round(part / total * 100.0, 1) if total else 0.0


def merge_country_guides(
    config_path: Path,
    iptv_guide_path: Path,
    iptv_coverage_path: Path,
    output_path: Path,
    report_path: Path,
    external_dir: Path | None = None,
    aliases_path: Path | None = Path("epg_aliases.json"),
    preferred_iptv_provider: str = "mediaklikk.hu",
    reference_date: date | None = None,
    future_days: int = 7,
) -> dict:
    """Merge EPG independently per country, then recombine the XMLTV output.

    Each stable country playlist is matched only against that country's
    external guide. This prevents a same-named station from another country
    from becoming a cross-country external-name match.
    """
    config_path = config_path.resolve()
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    epg = cfg.get("epg") or {}
    countries_cfg = epg.get("countries") or {}
    country_outputs = cfg.get("country_outputs") or {}

    if not isinstance(countries_cfg, dict) or not countries_cfg:
        raise RuntimeError("epg.countries must contain at least one country.")
    if not isinstance(country_outputs, dict):
        raise RuntimeError("country_outputs must be a JSON object.")

    (
        cross_alias_provider,
        cross_country_aliases,
    ) = load_cross_country_aliases(aliases_path)
    cross_country_external_cache: dict[str, dict] = {}

    combined_root = ET.Element(
        "tv",
        {"generator-info-name": "tomas-iptv merged EPG"},
    )
    matched: list[dict] = []
    unmatched: list[str] = []
    providers: Counter[str] = Counter()
    fresh_providers: Counter[str] = Counter()
    countries: dict[str, dict] = {}
    tvg_id_countries: dict[str, str] = {}
    external_countries: dict[str, dict] = {}
    seen_channel_ids: set[str] = set()
    seen_programmes: set[tuple[str, str, str]] = set()

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)

        for raw_code, raw_country_cfg in countries_cfg.items():
            code = str(raw_code or "").strip().upper()
            country_cfg = raw_country_cfg if isinstance(raw_country_cfg, dict) else {}
            if not code:
                raise RuntimeError("Invalid blank EPG country code.")

            playlist_rel = str(country_outputs.get(code) or "").strip()
            if not playlist_rel:
                raise RuntimeError(f"EPG country {code} has no country_outputs entry.")
            playlist_path = config_path.parent / playlist_rel
            if not playlist_path.is_file():
                raise RuntimeError(f"Country playlist for {code} does not exist: {playlist_path}")

            external_cfg = country_cfg.get("external") or {}
            if not isinstance(external_cfg, dict):
                raise RuntimeError(f"epg.countries.{code}.external must be an object.")
            external_provider = str(
                external_cfg.get("provider") or "epgshare01.online"
            ).strip() or "epgshare01.online"
            country_external_path = _external_path(external_dir, code)

            aliases: dict[str, str] = {}
            if country_external_path is not None:
                aliases = load_external_aliases(
                    aliases_path,
                    external_provider,
                )

            country_output = temp_root / f"{code}.guide.xml"
            country_report_path = temp_root / f"{code}.coverage.json"

            try:
                country_report = merge_guides(
                    playlist_path=playlist_path,
                    iptv_guide_path=iptv_guide_path,
                    iptv_coverage_path=iptv_coverage_path,
                    external_path=country_external_path,
                    external_provider=external_provider,
                    preferred_iptv_provider=preferred_iptv_provider,
                    reference_date=reference_date,
                    future_days=max(future_days, 0),
                    external_aliases=aliases,
                    output_path=country_output,
                    report_path=country_report_path,
                )
            except RuntimeError as exc:
                if (
                    str(exc) != NO_FRESH_ERROR
                    or not country_output.is_file()
                    or not country_report_path.is_file()
                ):
                    raise
                country_report = json.loads(
                    country_report_path.read_text(encoding="utf-8")
                )
                print(
                    f"WARNING: {code} currently has no fresh EPG data; "
                    "keeping its mapped-but-empty coverage in the aggregate."
                )

            country_tree = ET.parse(country_output)
            country_root = country_tree.getroot()
            if country_root.tag != "tv":
                raise RuntimeError(f"Invalid country EPG root for {code}: {country_root.tag!r}")

            apply_cross_country_aliases(
                country_code=code,
                playlist_path=playlist_path,
                country_root=country_root,
                country_report=country_report,
                aliases=cross_country_aliases,
                alias_provider=cross_alias_provider,
                countries_cfg=countries_cfg,
                external_dir=external_dir,
                external_cache=cross_country_external_cache,
                reference_date=reference_date,
                future_days=max(future_days, 0),
            )

            for channel in country_root.findall("channel"):
                channel_id = str(channel.get("id") or "").strip()
                if not channel_id:
                    continue
                if channel_id in seen_channel_ids:
                    raise RuntimeError(
                        f"The same EPG channel ID appears in multiple country outputs: {channel_id}"
                    )
                seen_channel_ids.add(channel_id)
                combined_root.append(copy.deepcopy(channel))
                tvg_id_countries[channel_id] = code

            for programme in country_root.findall("programme"):
                channel_id = str(programme.get("channel") or "").strip()
                key = (
                    channel_id,
                    str(programme.get("start") or ""),
                    str(programme.get("stop") or ""),
                )
                if key in seen_programmes:
                    continue
                seen_programmes.add(key)
                combined_root.append(copy.deepcopy(programme))

            country_matched: list[dict] = []
            for raw_item in country_report.get("matched") or []:
                if not isinstance(raw_item, dict):
                    continue
                item = dict(raw_item)
                item["country_code"] = code
                tvg_id = str(item.get("tvg_id") or "").strip()
                if tvg_id:
                    tvg_id_countries[tvg_id] = code
                country_matched.append(item)
                matched.append(item)

            country_unmatched = [
                str(value).strip()
                for value in (country_report.get("unmatched_tvg_ids") or [])
                if str(value).strip()
            ]
            for tvg_id in country_unmatched:
                tvg_id_countries[tvg_id] = code
                if tvg_id not in unmatched:
                    unmatched.append(tvg_id)

            for provider, count in (country_report.get("providers") or {}).items():
                providers[str(provider)] += int(count or 0)
            for provider, count in (
                country_report.get("fresh_channels_by_provider") or {}
            ).items():
                fresh_providers[str(provider)] += int(count or 0)

            playlist_total = int(country_report.get("playlist_tvg_ids") or 0)
            country_mapped = len(country_matched)
            country_info = (country_report.get("countries") or {}).get(code) or {}
            if not isinstance(country_info, dict):
                country_info = {}
            countries[code] = {
                "playlist_tvg_ids": playlist_total,
                "matched_tvg_ids": country_mapped,
                "unmatched_tvg_ids_count": len(country_unmatched),
                "mapping_coverage_percent": _percent(country_mapped, playlist_total),
                "sites": list(country_info.get("sites") or country_cfg.get("sites") or []),
                "providers": dict(sorted(Counter(
                    str(item.get("provider") or "unknown")
                    for item in country_matched
                ).items())),
            }

            external_info = country_report.get("external") or {}
            if not isinstance(external_info, dict):
                external_info = {}
            external_countries[code] = {
                **external_info,
                "configured": bool(external_cfg.get("url")),
                "downloaded": country_external_path is not None,
            }

    ET.indent(combined_root, space="  ")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(combined_root).write(
        output_path,
        encoding="utf-8",
        xml_declaration=True,
    )

    total = sum(int(info.get("playlist_tvg_ids") or 0) for info in countries.values())
    mapped_total = len(matched)
    latest_dates = [
        str(info.get("latest_programme_date") or "")
        for info in external_countries.values()
        if str(info.get("latest_programme_date") or "")
    ]
    external_providers = {
        str(info.get("provider") or "").strip()
        for info in external_countries.values()
        if str(info.get("provider") or "").strip()
    }
    ambiguous: list[dict] = []
    for code, info in external_countries.items():
        for raw_item in info.get("ambiguous") or []:
            item = dict(raw_item) if isinstance(raw_item, dict) else {"value": raw_item}
            item["country_code"] = code
            ambiguous.append(item)

    explicit_aliases_configured = max(
        [
            int(info.get("explicit_aliases_configured") or 0)
            for info in external_countries.values()
        ]
        or [0]
    )

    cross_country_aliases_used: list[dict] = []
    cross_country_aliases_skipped: list[dict] = []
    for code, info in external_countries.items():
        for raw_item in info.get("cross_country_aliases_used") or []:
            item = dict(raw_item) if isinstance(raw_item, dict) else {"value": raw_item}
            item.setdefault("country_code", code)
            cross_country_aliases_used.append(item)
        for raw_item in info.get("cross_country_aliases_skipped") or []:
            item = dict(raw_item) if isinstance(raw_item, dict) else {"value": raw_item}
            item.setdefault("country_code", code)
            cross_country_aliases_skipped.append(item)

    report = {
        "playlist_tvg_ids": total,
        "matched_tvg_ids": mapped_total,
        "mapping_coverage_percent": _percent(mapped_total, total),
        "matched": matched,
        "unmatched_tvg_ids": unmatched,
        "providers": dict(sorted(providers.items())),
        "countries": countries,
        "tvg_id_countries": tvg_id_countries,
        "fresh_channels_by_provider": dict(sorted(fresh_providers.items())),
        "reference_date": (
            reference_date.isoformat() if reference_date is not None else None
        ),
        "external": {
            "provider": (
                next(iter(external_providers))
                if len(external_providers) == 1
                else "multiple"
                if external_providers
                else ""
            ),
            "available": any(bool(info.get("available")) for info in external_countries.values()),
            "fresh": any(bool(info.get("fresh")) for info in external_countries.values()),
            "latest_programme_date": max(latest_dates) if latest_dates else None,
            "mapped_candidates": sum(
                int(info.get("mapped_candidates") or 0)
                for info in external_countries.values()
            ),
            "explicit_aliases_configured": explicit_aliases_configured,
            "cross_country_aliases_configured": len(cross_country_aliases),
            "cross_country_aliases_used": cross_country_aliases_used,
            "cross_country_aliases_skipped": cross_country_aliases_skipped,
            "ambiguous": ambiguous,
            "countries": external_countries,
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    programme_count = len(combined_root.findall("programme"))
    print(
        "Multi-country merged EPG: "
        f"{mapped_total}/{total} mapped across {len(countries)} countries, "
        f"{programme_count} programme entries."
    )
    for code, info in countries.items():
        external_info = external_countries.get(code) or {}
        print(
            f"- {code}: {info['matched_tvg_ids']}/{info['playlist_tvg_ids']} mapped; "
            f"external downloaded={bool(external_info.get('downloaded'))}, "
            f"fresh={bool(external_info.get('fresh'))}."
        )

    if programme_count == 0:
        raise RuntimeError(NO_FRESH_ERROR)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Merge IPTV-org and country-scoped external XMLTV guides for all "
            "configured Tomas IPTV country outputs."
        )
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--iptv-guide", required=True, type=Path)
    parser.add_argument("--iptv-coverage", required=True, type=Path)
    parser.add_argument("--external-dir", type=Path)
    parser.add_argument(
        "--aliases",
        type=Path,
        default=Path("epg_aliases.json"),
    )
    parser.add_argument(
        "--preferred-iptv-provider",
        default="mediaklikk.hu",
    )
    parser.add_argument("--reference-date", type=date.fromisoformat)
    parser.add_argument("--future-days", type=int, default=7)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    merge_country_guides(
        config_path=args.config,
        iptv_guide_path=args.iptv_guide,
        iptv_coverage_path=args.iptv_coverage,
        external_dir=args.external_dir,
        aliases_path=args.aliases,
        preferred_iptv_provider=args.preferred_iptv_provider,
        reference_date=args.reference_date,
        future_days=max(args.future_days, 0),
        output_path=args.output,
        report_path=args.report,
    )


if __name__ == "__main__":
    main()
