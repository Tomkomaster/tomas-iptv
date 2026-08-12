#!/usr/bin/env python3
from __future__ import annotations

import re


LEGACY_COUNTRY_LANGUAGE_DEFAULTS = {
    "HU": ["hun"],
    "SK": ["slk"],
    "CZ": ["ces"],
    "RS": ["srp"],
    "RO": ["ron"],
    "DE": ["deu"],
    "AT": ["deu"],
    "PL": ["pol"],
    "HR": ["hrv"],
    "SI": ["slv"],
    "UA": ["ukr"],
}


_LANGUAGE_ALIASES = {
    # Hungarian
    "hu": "hun",
    "hun": "hun",
    "hungarian": "hun",
    "magyar": "hun",
    # Slovak
    "sk": "slk",
    "slk": "slk",
    "slo": "slk",
    "slovak": "slk",
    "slovakian": "slk",
    # Czech
    "cs": "ces",
    "cz": "ces",
    "ces": "ces",
    "cze": "ces",
    "czech": "ces",
    # Serbian
    "sr": "srp",
    "srp": "srp",
    "serbian": "srp",
    "serb": "srp",
    # English
    "en": "eng",
    "eng": "eng",
    "english": "eng",
    # German
    "de": "deu",
    "deu": "deu",
    "ger": "deu",
    "german": "deu",
    # Romanian
    "ro": "ron",
    "ron": "ron",
    "rum": "ron",
    "romanian": "ron",
    # Russian
    "ru": "rus",
    "rus": "rus",
    "russian": "rus",
    # Croatian
    "hr": "hrv",
    "hrv": "hrv",
    "croatian": "hrv",
    # Slovenian
    "sl": "slv",
    "slv": "slv",
    "slovenian": "slv",
    # Ukrainian
    "uk": "ukr",
    "ukr": "ukr",
    "ukrainian": "ukr",
    # Polish
    "pl": "pol",
    "pol": "pol",
    "polish": "pol",
    # French
    "fr": "fra",
    "fra": "fra",
    "fre": "fra",
    "french": "fra",
    # Italian
    "it": "ita",
    "ita": "ita",
    "italian": "ita",
}


SOURCE_COUNTRY_MODES = {
    "fixed",
    "tvg_id",
}


def source_country_mode(spec: dict) -> str:
    """Return how a source assigns publication geography to its entries."""
    raw = str(spec.get("country_mode") or "fixed").strip().casefold()
    raw = raw.replace("-", "_").replace(" ", "_")
    aliases = {
        "fixed": "fixed",
        "source": "fixed",
        "derived": "tvg_id",
        "derive": "tvg_id",
        "tvg": "tvg_id",
        "tvg_id": "tvg_id",
    }
    mode = aliases.get(raw)
    if not mode:
        raise RuntimeError(
            f"Unsupported source country_mode {spec.get('country_mode')!r}. "
            f"Allowed modes: {', '.join(sorted(SOURCE_COUNTRY_MODES))}."
        )
    return mode


def normalize_country_code(value: str) -> str:
    """Normalize one ISO-3166-style two-letter country code."""
    code = str(value or "").strip().upper()
    return code if re.fullmatch(r"[A-Z]{2}", code) else ""


def country_code_from_tvg_id(value: str) -> str:
    """Derive IPTV-org channel geography from the final .cc tvg-id suffix."""
    base = str(value or "").strip().split("@", 1)[0].strip()
    if "." not in base:
        return ""
    return normalize_country_code(base.rsplit(".", 1)[-1])


def normalize_language_code(value: str) -> str:
    """Normalize spoken language metadata to ISO-639-3-style codes.

    Historical Tomas IPTV values such as HU/SK/CZ are intentionally accepted
    as language aliases and become hun/slk/ces. Country normalization is kept
    separate in normalize_country_code().
    """
    raw = str(value or "").strip()
    if not raw:
        return ""

    key = " ".join(
        raw.casefold()
        .replace("_", " ")
        .replace("-", " ")
        .split()
    )

    alias = _LANGUAGE_ALIASES.get(key)
    if alias:
        return alias

    if re.fullmatch(r"[a-z]{3}", key):
        return key

    return ""


def normalize_language_codes(value) -> list[str]:
    """Normalize one or many spoken-language values, preserving order."""
    if value is None:
        return []

    if isinstance(value, str):
        values = [
            part.strip()
            for part in re.split(r"[,;/+]", value)
            if part.strip()
        ]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]

    result: list[str] = []
    for raw in values:
        code = normalize_language_code(str(raw or ""))
        if code and code not in result:
            result.append(code)
    return result


def country_language_defaults(cfg: dict, country_code: str) -> list[str]:
    """Return explicitly configured spoken-language defaults for a country."""
    country = normalize_country_code(country_code)
    if not country:
        return []

    configured = cfg.get("country_language_defaults") or {}
    if isinstance(configured, dict) and country in configured:
        return normalize_language_codes(configured.get(country))

    return list(LEGACY_COUNTRY_LANGUAGE_DEFAULTS.get(country, []))


def source_country_code(spec: dict, cfg: dict) -> str:
    """Resolve a source's country scope with legacy config compatibility."""
    if source_country_mode(spec) == "tvg_id":
        return ""

    for value in (
        spec.get("country_code"),
        # Historical source config used language_code as the country bucket.
        spec.get("language_code"),
        cfg.get("default_country_code"),
        cfg.get("default_language_code"),
    ):
        code = normalize_country_code(str(value or ""))
        if code:
            return code
    return "HU"


def source_language_codes(spec: dict, cfg: dict, country_code: str) -> list[str]:
    """Resolve spoken-language expectations independently of source country."""
    explicit = normalize_language_codes(spec.get("language_codes"))
    if explicit:
        return explicit
    return country_language_defaults(cfg, country_code)


def configured_country_codes(cfg: dict) -> list[str]:
    outputs = cfg.get("country_outputs") or {}
    result: list[str] = []

    if isinstance(outputs, dict):
        for raw in outputs:
            code = normalize_country_code(str(raw or ""))
            if code and code not in result:
                result.append(code)

    if result:
        return result

    fallback = normalize_country_code(
        str(cfg.get("default_country_code") or cfg.get("default_language_code") or "")
    )
    return [fallback or "HU"]


def configured_language_codes(cfg: dict) -> list[str]:
    """Return spoken languages explicitly supported by current project data."""
    result: list[str] = []

    def add(values) -> None:
        for code in normalize_language_codes(values):
            if code not in result:
                result.append(code)

    language_outputs = cfg.get("language_outputs") or {}
    if isinstance(language_outputs, dict):
        add(list(language_outputs))

    for country in configured_country_codes(cfg):
        add(country_language_defaults(cfg, country))

    for section in ("sources", "extras"):
        for item in cfg.get(section, []) or []:
            if isinstance(item, dict):
                add(item.get("language_codes"))

    for route in cfg.get("verified_country_routes", []) or []:
        if isinstance(route, dict):
            add(route.get("observed_language_code"))

    return result


def legacy_country_scope_from_language_token(value: str) -> str:
    """Recover old HU/SK/CZ-style audit scope without generalizing language=country."""
    raw = str(value or "").strip().upper()
    if raw in LEGACY_COUNTRY_LANGUAGE_DEFAULTS:
        return raw
    return ""


def verified_country_route(
    cfg: dict,
    source_country_code: str,
    observed_language_codes,
) -> str:
    """Resolve only explicitly configured source-country/language reroutes."""
    source_country = normalize_country_code(source_country_code)
    observed = normalize_language_codes(observed_language_codes)
    if not source_country or len(observed) != 1:
        return ""

    language = observed[0]
    routes = cfg.get("verified_country_routes") or []
    if not isinstance(routes, list):
        raise RuntimeError("verified_country_routes must be a JSON list.")

    matches: list[str] = []
    for index, route in enumerate(routes, start=1):
        if not isinstance(route, dict):
            raise RuntimeError(f"verified_country_routes item #{index} must be an object.")

        source = normalize_country_code(route.get("source_country_code"))
        observed_code = normalize_language_code(route.get("observed_language_code"))
        output = normalize_country_code(route.get("output_country_code"))

        if not source or not observed_code or not output:
            raise RuntimeError(
                f"verified_country_routes item #{index} requires valid "
                "source_country_code, observed_language_code and output_country_code."
            )

        if source == source_country and observed_code == language:
            matches.append(output)

    if len(set(matches)) > 1:
        raise RuntimeError(
            "Conflicting verified_country_routes for "
            f"{source_country}/{language}: {sorted(set(matches))}"
        )

    return matches[0] if matches else ""
