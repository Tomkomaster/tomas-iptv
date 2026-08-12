#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import build
import feed_quality


def load_same_build_report(path: Path) -> dict:
    if not path.is_file():
        return {
            "schema_version": 1,
            "selection_only": True,
            "streams": [],
        }
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise RuntimeError("Same-build health report must be a JSON object.")
    if payload.get("selection_only") is not True:
        raise RuntimeError(
            "Refusing to use a same-build health report that is not marked selection_only=true."
        )
    return payload


def same_build_health_by_url(report: dict) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for item in report.get("streams", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("usable_evidence") is not True:
            continue
        url = feed_quality.canonical_stream_url(str(item.get("stream_url") or ""))
        if url:
            index[url] = dict(item)
    return index


def configured_weight_bound(cfg: dict | None) -> int:
    """Upper-bound score spread so a live feed always beats a failed one."""
    weights = dict(feed_quality.DEFAULT_WEIGHTS)
    configured = (
        (((cfg or {}).get("stable_playlist") or {}).get("feed_quality") or {}).get(
            "weights"
        )
        or {}
    )
    if isinstance(configured, dict):
        for key, value in configured.items():
            if key not in weights:
                continue
            try:
                weights[key] = int(value)
            except (TypeError, ValueError):
                continue
    return sum(abs(int(value)) for value in weights.values())


def apply_same_build_selection_guard(
    result: dict,
    entry: dict,
    cfg: dict | None,
    current_health: dict[str, dict],
) -> dict:
    """Apply a score guard only when today's usable probe says this feed failed.

    The guard is deliberately larger than the maximum possible spread of the
    configured quality weights. This encodes playability-first selection while
    preserving the original feed-quality ordering when two feeds share the same
    current playability state.
    """
    output = {
        "score": int(result.get("score") or 0),
        "components": list(result.get("components") or []),
        "summary": str(result.get("summary") or ""),
    }
    audit = entry.get("_audit") or {}
    url = feed_quality.canonical_stream_url(
        str(entry.get("url") or audit.get("stream_url") or "")
    )
    health = current_health.get(url) or {}
    if health.get("success") is not False:
        return output

    guard = configured_weight_bound(cfg) * 2 + 1
    component = {
        "key": "same_build_unplayable",
        "points": -guard,
        "label": (
            "Same-build verified-feed probe failed: "
            + str(health.get("status") or "failure")
        ),
    }
    output["components"].append(component)
    output["score"] += component["points"]
    output["summary"] = "; ".join(
        f"{int(item['points']):+d} {item['label']}"
        for item in output["components"]
    ) or "No quality bonuses or penalties"
    output["same_build_health_status"] = str(health.get("status") or "")
    output["same_build_health_success"] = False
    return output


def install_same_build_evidence(report: dict) -> dict[str, dict]:
    """Patch build's imported quality helpers for this process only."""
    current_health = same_build_health_by_url(report)
    original_context = build.build_feed_quality_context
    original_score = build.score_feed_quality

    def context_wrapper(cfg: dict) -> dict:
        context = original_context(cfg)
        merged_health = dict(context.get("health_by_url") or {})
        # Today's evidence must supersede yesterday's evidence for the same URL.
        merged_health.update(current_health)
        context["health_by_url"] = merged_health
        context["same_build_health_by_url"] = current_health
        return context

    def score_wrapper(
        entry: dict,
        cfg: dict | None = None,
        *,
        context: dict | None = None,
        reference_date=None,
    ) -> dict:
        result = original_score(
            entry,
            cfg,
            context=context,
            reference_date=reference_date,
        )
        return apply_same_build_selection_guard(
            result,
            entry,
            cfg,
            current_health,
        )

    build.build_feed_quality_context = context_wrapper
    build.score_feed_quality = score_wrapper
    return current_health


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run final stable selection using same-build verified-feed health evidence."
    )
    parser.add_argument(
        "--health",
        type=Path,
        default=Path("public/same-build-health.json"),
    )
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    report = load_same_build_report(args.health)
    current = install_same_build_evidence(report)
    print(
        "Final stable build: using same-build health evidence for "
        f"{len(current)} manually TV-safe redundant feeds."
    )
    build.main(strict=args.strict)


if __name__ == "__main__":
    main()
