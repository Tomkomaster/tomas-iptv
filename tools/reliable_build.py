#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import build
from tools.priority_coverage import generate_priority_coverage
from tools.same_build_failover import (
    load_audit_rows,
    probe_verified_redundancy,
    settings_from_config,
    write_report,
)
from tools.stable_build import install_same_build_evidence


def _finish_dashboard(audit_path: Path, config_path: Path) -> None:
    coverage = generate_priority_coverage(
        audit_path=audit_path,
        config_path=config_path,
    )
    summary = []
    for code, country in coverage.get("countries", {}).items():
        priorities = country.get("priorities", {})
        p1 = priorities.get("P1", {})
        p2 = priorities.get("P2", {})
        summary.append(
            f"{code} P1 {p1.get('found', 0)}/{p1.get('total', 0)}, "
            f"P2 {p2.get('found', 0)}/{p2.get('total', 0)}"
        )
    print("Priority coverage: " + "; ".join(summary))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Collect current IPTV candidates, probe redundant manually TV-safe feeds, "
            "then rebuild stable outputs using same-build health evidence."
        )
    )
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--audit", type=Path, default=Path("public/audit.csv"))
    parser.add_argument(
        "--health-output",
        type=Path,
        default=Path("public/same-build-health.json"),
    )
    args = parser.parse_args()

    print("Reliable build pass 1/2: collecting current candidates.")
    build.main(strict=args.strict)

    rows = load_audit_rows(args.audit)
    settings = settings_from_config(args.config)
    report = probe_verified_redundancy(rows, **settings)
    write_report(args.health_output, report)

    summary = report["summary"]
    print(
        "Verified redundancy probe: "
        f"{summary['redundant_channels']} redundant channels, "
        f"{summary['probed_feeds']} feeds, "
        f"{summary['playable']} playable, {summary['failed']} failed, "
        f"{summary['unknown']} unknown."
    )

    if not report.get("streams"):
        print("Reliable build: no redundant manually TV-safe feeds; first pass is final.")
        _finish_dashboard(args.audit, args.config)
        return

    current = install_same_build_evidence(report)
    print(
        "Reliable build pass 2/2: selecting stable feeds using current health for "
        f"{len(current)} verified alternatives."
    )
    build.main(strict=args.strict)
    _finish_dashboard(args.audit, args.config)

    print(
        json.dumps(
            {
                "same_build_failover": True,
                "redundant_channels": summary["redundant_channels"],
                "probed_feeds": summary["probed_feeds"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
