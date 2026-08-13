#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from epg_prepare import prepare_epg_channels, read_playlist_tvg_ids


NO_IPTV_MATCH_ERROR = "No playlist tvg-id values matched the configured EPG sites."


def _percent(part: int, total: int) -> float:
    return round(part / total * 100.0, 1) if total else 0.0


def _external_epg_configured(country_cfg: dict) -> bool:
    external = country_cfg.get("external") or {}
    return (
        isinstance(external, dict)
        and bool(str(external.get("url") or "").strip())
    )


def _empty_country_report(playlist_path: Path) -> dict:
    playlist_ids = read_playlist_tvg_ids(playlist_path)
    return {
        "playlist_tvg_ids": len(playlist_ids),
        "matched_tvg_ids": 0,
        "unmatched_tvg_ids_count": len(playlist_ids),
        "mapping_coverage_percent": 0.0,
        "providers": {},
        "matched": [],
        "unmatched_tvg_ids": playlist_ids,
    }


def prepare_country_epg(
    config_path: Path,
    epg_root: Path,
    output_path: Path,
    report_path: Path,
) -> dict:
    """Prepare one deterministic IPTV-org EPG mapping per configured country.

    The existing epg_prepare matcher remains authoritative. This function only
    scopes provider priority to each country playlist and then combines the
    resulting channel XML/report into the single guide input used downstream.

    A country with a configured external XMLTV source may legitimately have
    zero IPTV-org matches. In that case we preserve zero-match coverage and let
    the downstream external merge provide programme data for that country.
    """
    config_path = config_path.resolve()
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    epg = cfg.get("epg") or {}
    countries = epg.get("countries") or {}
    country_outputs = cfg.get("country_outputs") or {}

    if not isinstance(countries, dict) or not countries:
        raise RuntimeError(
            "EPG is enabled but epg.countries is empty or invalid."
        )

    if not isinstance(country_outputs, dict):
        raise RuntimeError("country_outputs must be a JSON object.")

    combined_root = ET.Element("channels")
    combined_matched: list[dict] = []
    combined_unmatched: list[str] = []
    provider_counts: Counter[str] = Counter()
    country_reports: dict[str, dict] = {}
    tvg_id_countries: dict[str, str] = {}
    seen_xmltv_ids: dict[str, str] = {}

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)

        for raw_code, raw_country_cfg in countries.items():
            code = str(raw_code or "").strip().upper()
            country_cfg = raw_country_cfg or {}
            if not code or not isinstance(country_cfg, dict):
                raise RuntimeError("Invalid EPG country configuration entry.")

            sites = [
                str(site).strip()
                for site in (country_cfg.get("sites") or [])
                if str(site).strip()
            ]
            if not sites:
                raise RuntimeError(
                    f"EPG country {code} has no configured IPTV-org sites."
                )

            playlist_rel = str(country_outputs.get(code) or "").strip()
            if not playlist_rel:
                raise RuntimeError(
                    f"EPG country {code} has no country_outputs entry."
                )

            playlist_path = config_path.parent / playlist_rel
            if not playlist_path.is_file():
                raise RuntimeError(
                    f"Country playlist for {code} does not exist: {playlist_path}"
                )

            country_xml = tmp_root / f"{code}.channels.xml"
            country_report_path = tmp_root / f"{code}.coverage.json"

            try:
                report = prepare_epg_channels(
                    playlist_path=playlist_path,
                    epg_root=epg_root,
                    sites=sites,
                    output_path=country_xml,
                    report_path=country_report_path,
                )
            except RuntimeError as exc:
                if (
                    str(exc) != NO_IPTV_MATCH_ERROR
                    or not _external_epg_configured(country_cfg)
                ):
                    raise

                report = _empty_country_report(playlist_path)
                empty_root = ET.Element("channels")
                ET.ElementTree(empty_root).write(
                    country_xml,
                    encoding="utf-8",
                    xml_declaration=True,
                )
                country_report_path.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(
                    f"WARNING: {code} has no IPTV-org EPG mappings; "
                    "continuing with its configured external EPG source."
                )

            country_tree = ET.parse(country_xml)
            for channel in country_tree.getroot().findall("channel"):
                xmltv_id = str(channel.get("xmltv_id") or "").strip()
                if not xmltv_id:
                    continue

                previous_country = seen_xmltv_ids.get(xmltv_id)
                if previous_country and previous_country != code:
                    raise RuntimeError(
                        "The same playlist tvg-id appears in multiple country "
                        f"outputs: {xmltv_id} ({previous_country}, {code})."
                    )
                if previous_country:
                    continue

                seen_xmltv_ids[xmltv_id] = code
                tvg_id_countries[xmltv_id] = code
                combined_root.append(copy.deepcopy(channel))

            country_matched: list[dict] = []
            for item in report.get("matched") or []:
                if not isinstance(item, dict):
                    continue
                enriched = dict(item)
                enriched["country_code"] = code
                country_matched.append(enriched)
                combined_matched.append(enriched)
                tvg_id = str(enriched.get("tvg_id") or "").strip()
                if tvg_id:
                    tvg_id_countries[tvg_id] = code

            country_unmatched = [
                str(value).strip()
                for value in (report.get("unmatched_tvg_ids") or [])
                if str(value).strip()
            ]
            for tvg_id in country_unmatched:
                tvg_id_countries[tvg_id] = code
                combined_unmatched.append(tvg_id)

            for provider, count in (report.get("providers") or {}).items():
                provider_counts[str(provider)] += int(count or 0)

            playlist_total = int(report.get("playlist_tvg_ids") or 0)
            matched_total = len(country_matched)
            country_reports[code] = {
                "playlist_tvg_ids": playlist_total,
                "matched_tvg_ids": matched_total,
                "unmatched_tvg_ids_count": len(country_unmatched),
                "mapping_coverage_percent": _percent(
                    matched_total,
                    playlist_total,
                ),
                "sites": sites,
                "providers": report.get("providers") or {},
                "matched": country_matched,
                "unmatched_tvg_ids": country_unmatched,
            }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(combined_root)
    ET.indent(tree, space="  ")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)

    playlist_total = sum(
        int(info.get("playlist_tvg_ids") or 0)
        for info in country_reports.values()
    )
    matched_total = len(combined_matched)

    aggregate = {
        "playlist_tvg_ids": playlist_total,
        "matched_tvg_ids": matched_total,
        "unmatched_tvg_ids_count": len(combined_unmatched),
        "mapping_coverage_percent": _percent(matched_total, playlist_total),
        "providers": dict(sorted(provider_counts.items())),
        "countries": country_reports,
        "tvg_id_countries": tvg_id_countries,
        "matched": combined_matched,
        "unmatched_tvg_ids": combined_unmatched,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        "Country-aware EPG mapping: "
        f"{matched_total}/{playlist_total} tvg-id values mapped "
        f"({_percent(matched_total, playlist_total):.1f}%)."
    )
    for code, info in country_reports.items():
        print(
            f"- {code}: {info['matched_tvg_ids']}/"
            f"{info['playlist_tvg_ids']} mapped "
            f"({info['mapping_coverage_percent']:.1f}%)."
        )

    return aggregate


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare IPTV-org EPG mappings with country-specific provider priority."
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--epg-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    prepare_country_epg(
        config_path=args.config,
        epg_root=args.epg_root,
        output_path=args.output,
        report_path=args.report,
    )


if __name__ == "__main__":
    main()
