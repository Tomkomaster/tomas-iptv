#!/usr/bin/env python3
from __future__ import annotations

from healthcheck import canonical_stream_url


VALID_HEALTH_POLICIES = {"normal", "event_based"}
SELECTORS = ("stream_url", "tvg_id", "channel")


def normalize_policy(value: object) -> str:
    policy = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if policy not in VALID_HEALTH_POLICIES:
        raise ValueError(
            f"Invalid health policy {value!r}; expected one of "
            + ", ".join(sorted(VALID_HEALTH_POLICIES))
            + "."
        )
    return policy


def normalize_selector(selector: str, value: object) -> str:
    text = str(value or "").strip()
    if selector == "stream_url":
        return canonical_stream_url(text)
    return text.casefold()


def compile_health_policy(payload: dict | None) -> tuple[str, dict[str, dict[str, dict]]]:
    payload = payload or {}
    if not isinstance(payload, dict):
        raise ValueError("Health policy must be a JSON object.")

    schema_version = int(payload.get("schema_version") or 1)
    if schema_version != 1:
        raise ValueError(f"Unsupported health policy schema_version: {schema_version}.")

    default = normalize_policy(payload.get("default") or "normal")
    indexes = {selector: {} for selector in SELECTORS}

    entries = payload.get("entries") or []
    if not isinstance(entries, list):
        raise ValueError("Health policy entries must be a list.")

    for index, raw in enumerate(entries, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Health policy entry #{index} must be an object.")

        selectors = [selector for selector in SELECTORS if str(raw.get(selector) or "").strip()]
        if len(selectors) != 1:
            raise ValueError(
                f"Health policy entry #{index} must define exactly one selector: "
                + ", ".join(SELECTORS)
                + "."
            )

        selector = selectors[0]
        normalized = normalize_selector(selector, raw.get(selector))
        if not normalized:
            raise ValueError(f"Health policy entry #{index} has an empty {selector} selector.")
        if normalized in indexes[selector]:
            raise ValueError(
                f"Duplicate health policy selector for {selector}={raw.get(selector)!r}."
            )

        policy = normalize_policy(raw.get("health_policy") or raw.get("policy"))
        indexes[selector][normalized] = {
            "health_policy": policy,
            "reason": str(raw.get("reason") or "").strip(),
            "matched_by": selector,
            "name": str(raw.get("name") or raw.get(selector) or "").strip(),
        }

    return default, indexes


def resolve_health_policy(
    row: dict,
    *,
    default: str,
    indexes: dict[str, dict[str, dict]],
) -> dict:
    for selector in SELECTORS:
        normalized = normalize_selector(selector, row.get(selector))
        if not normalized:
            continue
        match = indexes.get(selector, {}).get(normalized)
        if match:
            return dict(match)

    return {
        "health_policy": default,
        "reason": (
            "Normal 24/7 health policy: automated failures build a daily failure streak."
            if default == "normal"
            else "Default event-based policy."
        ),
        "matched_by": "default",
        "name": str(row.get("channel") or "").strip(),
    }
