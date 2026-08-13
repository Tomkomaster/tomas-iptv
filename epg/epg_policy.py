from __future__ import annotations

from healthcheck import canonical_stream_url


EPG_POLICY_STATUSES = ("expected", "optional", "not_expected")
EPG_POLICY_SELECTORS = ("stream_url", "tvg_id", "channel")
EPG_COUNTRY_DEFAULTS_KEY = "__country_defaults__"


def _normalize_selector(field: str, value: str) -> str:
    text = str(value or "").strip()
    if field == "stream_url":
        return canonical_stream_url(text)
    return text.casefold()


def compile_epg_policy(payload: dict | None) -> tuple[str, dict[str, dict[str, dict]]]:
    """Validate and index the EPG policy file.

    Each entry must use exactly one stable selector. Stream URL overrides tvg-id,
    which overrides channel name when a stable row is resolved.
    """
    payload = payload or {}
    if not isinstance(payload, dict):
        raise ValueError("EPG policy must be a JSON object.")

    default = str(payload.get("default") or "expected").strip().casefold()
    if default not in EPG_POLICY_STATUSES:
        raise ValueError(
            f"Invalid EPG policy default {default!r}; expected one of "
            + ", ".join(EPG_POLICY_STATUSES)
            + "."
        )

    entries = payload.get("entries") or []
    if not isinstance(entries, list):
        raise ValueError("EPG policy entries must be a list.")

    indexes: dict[str, dict[str, dict]] = {
        selector: {} for selector in EPG_POLICY_SELECTORS
    }

    raw_country_defaults = payload.get("country_defaults") or {}
    if not isinstance(raw_country_defaults, dict):
        raise ValueError("EPG policy country_defaults must be an object.")

    country_defaults: dict[str, str] = {}
    for raw_code, raw_status in raw_country_defaults.items():
        code = str(raw_code or "").strip().upper()
        status = str(raw_status or "").strip().casefold()
        if not code:
            raise ValueError("EPG policy country default has an empty country code.")
        if status not in EPG_POLICY_STATUSES:
            raise ValueError(
                f"Invalid EPG policy country default for {code}: {status!r}."
            )
        country_defaults[code] = status

    indexes[EPG_COUNTRY_DEFAULTS_KEY] = country_defaults

    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"EPG policy entry #{position} must be an object.")

        status = str(entry.get("status") or "").strip().casefold()
        if status not in EPG_POLICY_STATUSES:
            raise ValueError(
                f"EPG policy entry #{position} has invalid status {status!r}."
            )

        selectors = [
            (field, str(entry.get(field) or "").strip())
            for field in EPG_POLICY_SELECTORS
            if str(entry.get(field) or "").strip()
        ]
        if len(selectors) != 1:
            raise ValueError(
                f"EPG policy entry #{position} must define exactly one of "
                + ", ".join(EPG_POLICY_SELECTORS)
                + "."
            )

        field, raw_value = selectors[0]
        key = _normalize_selector(field, raw_value)
        if not key:
            raise ValueError(f"EPG policy entry #{position} has an empty selector.")
        if key in indexes[field]:
            raise ValueError(
                f"Duplicate EPG policy selector {field}={raw_value!r}."
            )

        indexes[field][key] = {
            "status": status,
            "reason": str(entry.get("reason") or "").strip(),
            "name": str(entry.get("name") or "").strip(),
            "matched_by": field,
        }

    return default, indexes


def resolve_epg_policy(
    row: dict,
    *,
    default: str,
    indexes: dict[str, dict[str, dict]],
) -> dict:
    """Resolve one stable row using deterministic selector precedence."""
    values = {
        "stream_url": str(row.get("stream_url") or "").strip(),
        "tvg_id": str(row.get("tvg_id") or "").strip(),
        "channel": str(row.get("channel") or "").strip(),
    }

    for field in EPG_POLICY_SELECTORS:
        value = values[field]
        if not value:
            continue
        key = _normalize_selector(field, value)
        match = indexes.get(field, {}).get(key)
        if match:
            return dict(match)

    country_code = str(
        row.get("output_country_code")
        or row.get("playlist_country_code")
        or row.get("country_code")
        or row.get("output_language_code")
        or row.get("language_code")
        or row.get("playlist_language_code")
        or ""
    ).strip().upper()
    country_defaults = indexes.get(EPG_COUNTRY_DEFAULTS_KEY, {})
    country_status = country_defaults.get(country_code) if country_code else None
    if country_status:
        return {
            "status": country_status,
            "reason": "",
            "name": "",
            "matched_by": "country_default",
        }

    return {
        "status": default,
        "reason": "",
        "name": "",
        "matched_by": "default",
    }
