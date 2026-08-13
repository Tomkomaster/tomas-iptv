#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from country_language import normalize_country_code
from research_priority import PRIORITY_ORDER, normalize_name, normalize_tvg_id


def compile_wanted_channels(payload: dict | None) -> list[dict[str, str]]:
    payload = payload or {}
    if not isinstance(payload, dict):
        raise ValueError("Wanted channel catalog must be a JSON object.")

    schema_version = int(payload.get("schema_version") or 1)
    if schema_version != 1:
        raise ValueError(f"Unsupported wanted channel schema_version: {schema_version}.")

    raw_channels = payload.get("channels") or []
    if not isinstance(raw_channels, list):
        raise ValueError("Wanted channel catalog channels must be a list.")

    compiled: list[dict[str, str]] = []
    seen_names: set[tuple[str, str]] = set()
    seen_ids: set[tuple[str, str]] = set()

    for index, raw in enumerate(raw_channels, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Wanted channel entry #{index} must be an object.")

        country = normalize_country_code(str(raw.get("country_code") or ""))
        if not country:
            raise ValueError(
                f"Wanted channel entry #{index} requires a valid country_code."
            )

        channel = str(raw.get("channel") or "").strip()
        if not channel:
            raise ValueError(f"Wanted channel entry #{index} requires channel.")

        tvg_id = str(raw.get("tvg_id") or "").strip()
        priority = str(raw.get("priority") or "").strip().upper()
        if priority and priority not in PRIORITY_ORDER:
            raise ValueError(
                f"Wanted channel entry #{index} has invalid priority {priority!r}; "
                f"expected one of {', '.join(PRIORITY_ORDER)}."
            )

        name_key = (country, normalize_name(channel))
        if name_key in seen_names:
            raise ValueError(
                f"Duplicate wanted channel name for {country}: {channel!r}."
            )
        seen_names.add(name_key)

        if tvg_id:
            id_key = (country, normalize_tvg_id(tvg_id))
            if id_key in seen_ids:
                raise ValueError(
                    f"Duplicate wanted tvg_id for {country}: {tvg_id!r}."
                )
            seen_ids.add(id_key)

        compiled.append(
            {
                "country_code": country,
                "channel": channel,
                "tvg_id": tvg_id,
                "priority": priority,
                "reason": str(raw.get("reason") or "").strip(),
                "notes": str(raw.get("notes") or "").strip(),
            }
        )

    return compiled


def _load_payload(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Wanted channel catalog {path.name} must be a JSON object.")
    return payload


def load_wanted_channels(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.is_file():
        return []

    payload = _load_payload(path)
    if path.name == "wanted_channels.json":
        merged_channels = list(payload.get("channels") or [])
        for extra_path in sorted(path.parent.glob("wanted_channels_*.json")):
            extra_payload = _load_payload(extra_path)
            schema_version = int(extra_payload.get("schema_version") or 1)
            if schema_version != 1:
                raise ValueError(
                    f"Unsupported wanted channel schema_version in {extra_path.name}: "
                    f"{schema_version}."
                )
            extra_channels = extra_payload.get("channels") or []
            if not isinstance(extra_channels, list):
                raise ValueError(
                    f"Wanted channel catalog {extra_path.name} channels must be a list."
                )
            merged_channels.extend(extra_channels)

        payload = dict(payload)
        payload["channels"] = merged_channels

    return compile_wanted_channels(payload)
