#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path


GRAB_CHANNEL_RE = re.compile(
    r"\[\d+/\d+\]\s+([^\s]+)\s+\([^)]*\)\s+-\s+([^\s]+)\s+-"
)
HTTP_ERROR_RE = re.compile(
    r"ERR:\s+Request failed with status code\s+(\d{3})",
    re.IGNORECASE,
)


def analyse_epg_health(
    coverage_path: Path,
    guide_path: Path,
    output_path: Path,
    grab_log_path: Path | None = None,
) -> dict:
    coverage = json.loads(
        coverage_path.read_text(
            encoding="utf-8"
        )
    )

    matched = coverage.get("matched") or []
    if not isinstance(matched, list):
        raise RuntimeError(
            "EPG coverage report has invalid matched data."
        )

    provider_by_tvg: dict[str, str] = {}
    mapped_by_provider: Counter[str] = Counter()

    for item in matched:
        if not isinstance(item, dict):
            continue
        tvg_id = str(item.get("tvg_id") or "").strip()
        provider = str(item.get("provider") or "unknown").strip() or "unknown"
        if not tvg_id:
            continue
        provider_by_tvg[tvg_id] = provider
        mapped_by_provider[provider] += 1

    root = ET.parse(guide_path).getroot()
    if root.tag != "tv":
        raise RuntimeError(
            f"Invalid XMLTV root element: {root.tag!r}"
        )

    programme_counts: Counter[str] = Counter()
    for programme in root.findall("programme"):
        channel_id = str(
            programme.get("channel") or ""
        ).strip()
        if channel_id:
            programme_counts[channel_id] += 1

    populated_ids = {
        tvg_id
        for tvg_id in provider_by_tvg
        if programme_counts.get(tvg_id, 0) > 0
    }

    populated_by_provider: Counter[str] = Counter()
    programmes_by_provider: Counter[str] = Counter()

    for tvg_id, provider in provider_by_tvg.items():
        count = programme_counts.get(tvg_id, 0)
        if count:
            populated_by_provider[provider] += 1
            programmes_by_provider[provider] += count

    http_errors_by_provider: dict[str, Counter[str]] = defaultdict(Counter)
    grab_errors_total = 0

    if grab_log_path and grab_log_path.is_file():
        current_provider = "unknown"
        current_tvg_id = ""

        for raw_line in grab_log_path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines():
            match = GRAB_CHANNEL_RE.search(raw_line)
            if match:
                current_provider = match.group(1).strip() or "unknown"
                current_tvg_id = match.group(2).strip()
                continue

            error = HTTP_ERROR_RE.search(raw_line)
            if error:
                status = error.group(1)
                http_errors_by_provider[current_provider][status] += 1
                grab_errors_total += 1

    playlist_total = int(
        coverage.get("playlist_tvg_ids") or 0
    )
    mapped_total = len(provider_by_tvg)
    populated_total = len(populated_ids)

    actual_coverage = (
        populated_total / playlist_total * 100.0
        if playlist_total
        else 0.0
    )

    mapped_effectiveness = (
        populated_total / mapped_total * 100.0
        if mapped_total
        else 0.0
    )

    providers: dict[str, dict] = {}
    provider_names = sorted(
        set(mapped_by_provider)
        | set(populated_by_provider)
        | set(http_errors_by_provider)
    )

    for provider in provider_names:
        mapped_count = mapped_by_provider.get(provider, 0)
        populated_count = populated_by_provider.get(provider, 0)
        providers[provider] = {
            "mapped_channels": mapped_count,
            "channels_with_programmes": populated_count,
            "channels_without_programmes": max(
                mapped_count - populated_count,
                0,
            ),
            "programme_entries": programmes_by_provider.get(provider, 0),
            "effective_percent": round(
                (
                    populated_count / mapped_count * 100.0
                    if mapped_count
                    else 0.0
                ),
                1,
            ),
            "http_errors": dict(
                sorted(
                    http_errors_by_provider.get(
                        provider,
                        Counter(),
                    ).items()
                )
            ),
        }

    missing_programmes = [
        {
            "tvg_id": tvg_id,
            "provider": provider_by_tvg[tvg_id],
        }
        for tvg_id in provider_by_tvg
        if tvg_id not in populated_ids
    ]

    if populated_total == 0:
        status = "failed"
    elif populated_total < mapped_total:
        status = "degraded"
    else:
        status = "healthy"

    report = {
        "status": status,
        "playlist_tvg_ids": playlist_total,
        "mapped_tvg_ids": mapped_total,
        "mapped_coverage_percent": round(
            (
                mapped_total / playlist_total * 100.0
                if playlist_total
                else 0.0
            ),
            1,
        ),
        "channels_with_programmes": populated_total,
        "actual_programme_coverage_percent": round(
            actual_coverage,
            1,
        ),
        "mapped_channels_effective_percent": round(
            mapped_effectiveness,
            1,
        ),
        "programme_entries": sum(programme_counts.values()),
        "grab_http_errors_total": grab_errors_total,
        "providers": providers,
        "mapped_without_programmes_count": len(missing_programmes),
        "mapped_without_programmes": missing_programmes,
    }

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    output_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    print(
        "EPG health: "
        f"{populated_total}/{playlist_total} playlist channels "
        "have actual programme data "
        f"({actual_coverage:.1f}%)."
    )
    print(
        "EPG mappings: "
        f"{mapped_total}/{playlist_total}; "
        f"only {populated_total}/{mapped_total or 0} mapped channels "
        "produced programmes."
    )

    for provider, info in providers.items():
        errors = info["http_errors"]
        error_text = (
            ", ".join(
                f"HTTP {code} x{count}"
                for code, count in errors.items()
            )
            if errors
            else "no captured HTTP errors"
        )
        print(
            f"- {provider}: "
            f"{info['channels_with_programmes']}/"
            f"{info['mapped_channels']} mapped channels populated; "
            f"{error_text}."
        )

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Measure actual XMLTV programme coverage after the EPG grab."
        )
    )
    parser.add_argument(
        "--coverage",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--guide",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--grab-log",
        type=Path,
    )
    args = parser.parse_args()

    report = analyse_epg_health(
        coverage_path=args.coverage,
        guide_path=args.guide,
        output_path=args.output,
        grab_log_path=args.grab_log,
    )

    if report["channels_with_programmes"] == 0:
        raise SystemExit(
            "EPG health failed: no mapped playlist channel has programme data."
        )


if __name__ == "__main__":
    main()
