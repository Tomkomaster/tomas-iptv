#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from healthcheck import probe_stream
from research_exports import channel_key


TV_SAFE_DECISIONS = frozenset({"Verified", "TV verified"})


def truthy(value: object) -> bool:
    return str(value or "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def load_audit_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise RuntimeError(
            f"Same-build failover requires {path}. Run build.py once to collect candidates first."
        )
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def tv_safe_redundant_groups(
    rows: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    """Return only current logical channels with 2+ manually TV-safe feeds."""
    grouped: dict[str, list[dict[str, str]]] = {}

    for row in rows:
        decision = str(row.get("decision") or "").strip()
        url = str(row.get("stream_url") or "").strip()
        if decision not in TV_SAFE_DECISIONS:
            continue
        if not truthy(row.get("in_playlist")):
            continue
        if truthy(row.get("exclude_from_playlist")):
            continue
        if not url:
            continue
        grouped.setdefault(channel_key(row), []).append(row)

    return {
        key: group
        for key, group in grouped.items()
        if len(group) >= 2
    }


def probe_verified_redundancy(
    rows: list[dict[str, str]],
    *,
    workers: int = 8,
    timeout: float = 8.0,
    slow_start_seconds: float = 6.0,
    max_segment_tries: int = 2,
    probe_fn=probe_stream,
) -> dict:
    """Probe only redundant feeds that are already manually TV-safe.

    Automated probing never changes audit decisions. A failed probe is only
    same-build selection evidence between alternatives that were already
    marked Verified or TV verified by a human.
    """
    groups = tv_safe_redundant_groups(rows)
    candidates = [row for group in groups.values() for row in group]
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    results: list[dict | None] = [None] * len(candidates)

    def run_probe(row: dict[str, str]) -> dict:
        return probe_fn(
            {"stream_url": str(row.get("stream_url") or "").strip()},
            timeout=timeout,
            slow_start_seconds=slow_start_seconds,
            max_segment_tries=max_segment_tries,
        )

    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as executor:
        futures = {
            executor.submit(run_probe, row): index
            for index, row in enumerate(candidates)
        }

        for future in as_completed(futures):
            index = futures[future]
            row = candidates[index]
            try:
                probe = future.result()
                success = probe.get("success")
                usable_evidence = isinstance(success, bool)
            except Exception as exc:
                probe = {
                    "status": "Probe error",
                    "success": None,
                    "startup_seconds": None,
                    "redirected": False,
                    "request_count": 0,
                    "probe_type": "Unknown",
                    "detail": f"Unexpected same-build probe error: {exc}",
                    "final_url": str(row.get("stream_url") or ""),
                    "http_status": None,
                    "tls_certificate_warning": False,
                    "tls_certificate_detail": "",
                }
                usable_evidence = False

            results[index] = {
                "channel": str(row.get("channel") or "").strip(),
                "country_code": str(
                    row.get("output_country_code")
                    or row.get("playlist_country_code")
                    or row.get("playlist_language_code")
                    or ""
                ).strip().upper(),
                "tvg_id": str(row.get("tvg_id") or "").strip(),
                "stream_url": str(row.get("stream_url") or "").strip(),
                "decision": str(row.get("decision") or "").strip(),
                "checked_at": checked_at,
                "selection_only": True,
                "usable_evidence": usable_evidence,
                "actionable_failure": usable_evidence and probe.get("success") is False,
                "manual_retest_recommended": False,
                **probe,
            }

    streams = [item for item in results if item is not None]
    status_counts = Counter(str(item.get("status") or "Unknown") for item in streams)
    playable = sum(1 for item in streams if item.get("success") is True)
    failed = sum(1 for item in streams if item.get("success") is False)
    unknown = sum(1 for item in streams if item.get("success") is None)

    return {
        "schema_version": 1,
        "generated_at": checked_at,
        "selection_only": True,
        "manual_testing_authority": (
            "Same-build probes never create verification, never modify audit.json, and "
            "never make Needs review/PC only/Rejected feeds eligible for the stable playlist."
        ),
        "scope": "Only logical channels with at least two current Verified/TV verified feeds.",
        "settings": {
            "workers": max(1, int(workers)),
            "timeout_seconds": timeout,
            "slow_start_seconds": slow_start_seconds,
            "max_segment_tries": max_segment_tries,
        },
        "summary": {
            "redundant_channels": len(groups),
            "probed_feeds": len(streams),
            "playable": playable,
            "failed": failed,
            "unknown": unknown,
            "status_counts": dict(sorted(status_counts.items())),
        },
        "streams": streams,
    }


def settings_from_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    health = cfg.get("health") or {}
    failover = (cfg.get("stable_playlist") or {}).get("same_build_failover") or {}
    return {
        "workers": int(failover.get("workers") or health.get("workers") or 8),
        "timeout": float(
            failover.get("timeout_seconds") or health.get("timeout_seconds") or 8
        ),
        "slow_start_seconds": float(
            failover.get("slow_start_seconds")
            or health.get("slow_start_seconds")
            or 6
        ),
        "max_segment_tries": int(
            failover.get("max_segment_tries")
            or health.get("max_segment_tries")
            or 2
        ),
    }


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Probe redundant manually TV-safe feeds before final stable selection."
    )
    parser.add_argument("--audit", type=Path, default=Path("public/audit.csv"))
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("public/same-build-health.json"),
    )
    args = parser.parse_args()

    rows = load_audit_rows(args.audit)
    settings = settings_from_config(args.config)
    report = probe_verified_redundancy(rows, **settings)
    write_report(args.output, report)

    summary = report["summary"]
    print(
        "Same-build verified failover probe: "
        f"{summary['redundant_channels']} redundant channels, "
        f"{summary['probed_feeds']} feeds probed, "
        f"{summary['playable']} playable, {summary['failed']} failed, "
        f"{summary['unknown']} unknown."
    )


if __name__ == "__main__":
    main()
