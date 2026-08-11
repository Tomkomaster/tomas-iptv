#!/usr/bin/env python3
from __future__ import annotations

import re


PRIORITY_ORDER = ("P1", "P2", "P3", "P4", "P5")
DEFAULT_LABELS = {
    "P1": "Major national channels",
    "P2": "Major thematic / sports / movie channels",
    "P3": "Regional / local channels",
    "P4": "Web / niche / low-value channels",
    "P5": "Probably not worth pursuing",
}
SELECTORS = ("channel", "tvg_id")


def normalize_name(value: object) -> str:
    text = str(value or "").strip().casefold()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def normalize_tvg_id(value: object) -> str:
    text = str(value or "").strip()
    return re.sub(
        r"@(SD|HD|FHD|UHD|4K|\d{3,4}P)$",
        "",
        text,
        flags=re.I,
    ).casefold()


def normalize_country(value: object) -> str:
    return str(value or "").strip().upper()


def normalize_priority(value: object) -> str:
    priority = str(value or "").strip().upper()
    if priority not in PRIORITY_ORDER:
        raise ValueError(
            f"Invalid research priority {value!r}; expected one of {', '.join(PRIORITY_ORDER)}."
        )
    return priority


def compile_research_priority_policy(payload: dict | None) -> dict:
    payload = payload or {}
    if not isinstance(payload, dict):
        raise ValueError("Research priority policy must be a JSON object.")

    schema_version = int(payload.get("schema_version") or 1)
    if schema_version != 1:
        raise ValueError(f"Unsupported research priority schema_version: {schema_version}.")

    default_priority = normalize_priority(payload.get("default_priority") or "P3")

    labels = dict(DEFAULT_LABELS)
    configured_labels = payload.get("priority_labels") or {}
    if not isinstance(configured_labels, dict):
        raise ValueError("priority_labels must be an object when present.")
    for key, value in configured_labels.items():
        priority = normalize_priority(key)
        label = str(value or "").strip()
        if not label:
            raise ValueError(f"Priority label for {priority} cannot be empty.")
        labels[priority] = label

    exact: dict[tuple[str, str, str], dict] = {}
    entries = payload.get("entries") or []
    if not isinstance(entries, list):
        raise ValueError("Research priority entries must be a list.")

    for index, raw in enumerate(entries, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Research priority entry #{index} must be an object.")

        selectors = [selector for selector in SELECTORS if str(raw.get(selector) or "").strip()]
        if len(selectors) != 1:
            raise ValueError(
                f"Research priority entry #{index} must define exactly one selector: "
                + ", ".join(SELECTORS)
                + "."
            )

        selector = selectors[0]
        priority = normalize_priority(raw.get("priority"))
        country = normalize_country(raw.get("country"))
        if not country:
            raise ValueError(f"Research priority entry #{index} requires country.")

        raw_value = raw.get(selector)
        value = normalize_tvg_id(raw_value) if selector == "tvg_id" else normalize_name(raw_value)
        if not value:
            raise ValueError(f"Research priority entry #{index} has an empty {selector} selector.")

        key = (country, selector, value)
        if key in exact:
            raise ValueError(
                f"Duplicate research priority selector for {country} {selector}={raw_value!r}."
            )

        exact[key] = {
            "priority": priority,
            "label": labels[priority],
            "reason": str(raw.get("reason") or labels[priority]).strip(),
            "matched_by": selector,
        }

    rules: list[dict] = []
    raw_rules = payload.get("rules") or []
    if not isinstance(raw_rules, list):
        raise ValueError("Research priority rules must be a list.")

    for index, raw in enumerate(raw_rules, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Research priority rule #{index} must be an object.")

        priority = normalize_priority(raw.get("priority"))
        contains_any = raw.get("contains_any") or []
        if not isinstance(contains_any, list) or not contains_any:
            raise ValueError(
                f"Research priority rule #{index} requires a non-empty contains_any list."
            )

        patterns = [normalize_name(value) for value in contains_any if normalize_name(value)]
        if not patterns:
            raise ValueError(f"Research priority rule #{index} has no usable patterns.")

        countries = raw.get("countries") or []
        if countries and not isinstance(countries, list):
            raise ValueError(f"Research priority rule #{index} countries must be a list.")
        normalized_countries = {
            normalize_country(value) for value in countries if normalize_country(value)
        }

        rules.append(
            {
                "priority": priority,
                "label": labels[priority],
                "reason": str(raw.get("reason") or labels[priority]).strip(),
                "patterns": patterns,
                "countries": normalized_countries,
                "matched_by": f"rule:{index}",
            }
        )

    return {
        "schema_version": schema_version,
        "default_priority": default_priority,
        "labels": labels,
        "exact": exact,
        "rules": rules,
    }


def resolve_research_priority(row: dict, compiled: dict) -> dict:
    country = normalize_country(row.get("country"))
    tvg_id = normalize_tvg_id(row.get("tvg_id"))
    channel = normalize_name(row.get("channel"))

    if country and tvg_id:
        match = compiled["exact"].get((country, "tvg_id", tvg_id))
        if match:
            return dict(match)

    if country and channel:
        match = compiled["exact"].get((country, "channel", channel))
        if match:
            return dict(match)

    for rule in compiled["rules"]:
        countries = rule.get("countries") or set()
        if countries and country not in countries:
            continue
        if any(pattern in channel for pattern in rule["patterns"]):
            return {
                "priority": rule["priority"],
                "label": rule["label"],
                "reason": rule["reason"],
                "matched_by": rule["matched_by"],
            }

    priority = compiled["default_priority"]
    return {
        "priority": priority,
        "label": compiled["labels"][priority],
        "reason": "Default research tier: regional/local or otherwise uncategorized channel.",
        "matched_by": "default",
    }


def priority_rank(value: object) -> int:
    priority = str(value or "").strip().upper()
    try:
        return PRIORITY_ORDER.index(priority)
    except ValueError:
        return len(PRIORITY_ORDER)
