#!/usr/bin/env python3
"""Spoken-language interpretation and explicit publication-country routing.

Country identity and spoken language are intentionally separate. This module
contains the legacy audit-language compatibility layer plus the explicit rules
that can route a verified feed to another publication country.
"""
from __future__ import annotations

import re

from country_language import (
    configured_country_codes,
    configured_language_codes,
    normalize_language_code as normalize_spoken_language_code,
    legacy_country_scope_from_language_token,
    normalize_country_code,
    normalize_language_codes as normalize_spoken_language_codes,
    verified_country_route,
)
from iptv.channel_identity import canonical_stream_url
from iptv.playback_status import normalize_test_status

LANGUAGE_NAME_TO_CODE = {
    "hungarian": "HU",
    "magyar": "HU",
    "hun": "HU",

    "slovak": "SK",
    "slovakian": "SK",
    "slk": "SK",
    "slo": "SK",

    "czech": "CZ",
    "ces": "CZ",
    "cze": "CZ",

    "serbian": "SR",
    "serb": "SR",

    "english": "EN",
    "german": "DE",
    "russian": "RU",
    "romanian": "RO",
    "croatian": "HR",
    "slovenian": "SL",
    "ukrainian": "UK",
    "polish": "PL",
}

def normalize_language_code(value: str) -> str:
    """
    Normalize one project language code.

    Tomas IPTV currently uses the familiar uppercase HU/SK/CZ-style codes.
    Legacy language names such as 'Hungarian' and 'Czech' are accepted for
    backwards compatibility.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""

    name_key = " ".join(
        raw.casefold()
        .replace("_", " ")
        .replace("-", " ")
        .split()
    )

    if name_key in LANGUAGE_NAME_TO_CODE:
        return LANGUAGE_NAME_TO_CODE[name_key]

    upper = raw.upper()

    if re.fullmatch(r"[A-Z]{2,3}", upper):
        return upper

    return ""

def normalize_language_codes(value) -> list[str]:
    """Normalize legacy audit-language values while preserving their API."""
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

def normalize_language_match(value: str) -> str:
    """
    Normalize the four supported language-match states.

    yes          = observed language matches the expected playlist language
    no           = observed language does not match
    unknown      = language has not been confirmed
    multilingual = expected language is present together with other languages
    """
    token = (
        str(value or "")
        .strip()
        .casefold()
        .replace("-", "_")
        .replace(" ", "_")
    )

    aliases = {
        "yes": "yes",
        "match": "yes",
        "matches": "yes",
        "matching": "yes",
        "ok": "yes",
        "true": "yes",

        "no": "no",
        "mismatch": "no",
        "wrong": "no",
        "wrong_language": "no",
        "false": "no",

        "unknown": "unknown",
        "not_tested": "unknown",
        "untested": "unknown",
        "pending": "unknown",

        "multilingual": "multilingual",
        "multi": "multilingual",
        "multiple": "multilingual",
    }

    return aliases.get(token, "")

def legacy_language_is_negative(value: str) -> bool:
    """
    Recognize old generic negative language descriptions without mentioning
    any particular country.

    Examples:
      wrong
      wrong language
      not hungarian
      not slovak
      non-hungarian
      non-czech
    """
    token = " ".join(
        str(value or "")
        .strip()
        .casefold()
        .replace("_", " ")
        .replace("-", " ")
        .split()
    )

    if token in {
        "wrong",
        "wrong language",
        "mismatch",
        "language mismatch",
        "non matching",
        "non matching language",
    }:
        return True

    if token.startswith("not "):
        return True

    if token.startswith("non "):
        return True

    return False

def derive_language_match(
    expected_codes: list[str],
    observed_codes: list[str],
) -> str:
    """
    Derive language_match from expected and observed languages.
    """
    if not expected_codes or not observed_codes:
        return "unknown"

    expected = set(normalize_spoken_language_codes(expected_codes))
    observed = set(normalize_spoken_language_codes(observed_codes))

    if not expected.intersection(observed):
        return "no"

    if len(observed_codes) > 1:
        return "multilingual"

    return "yes"

def resolve_language_info(
    item: dict,
    default_expected=None,
) -> tuple[list[str], list[str], str]:
    """
    Resolve the new language model while remaining compatible with the old
    audit.json language/language_code fields.
    """
    expected_codes = normalize_language_codes(
        item.get("expected_language_codes")
    )

    if not expected_codes:
        expected_codes = normalize_language_codes(
            default_expected
        )

    observed_codes = normalize_language_codes(
        item.get("observed_language_codes")
    )

    legacy_language = str(
        item.get("language") or ""
    ).strip()

    # Old audit rows usually store the observed language as a human-readable
    # name such as "Hungarian", "German" or "Czech".
    if (
        not observed_codes
        and legacy_language
        and legacy_language.casefold() not in {
            "unknown",
            "untested",
            "not tested",
            "not_tested",
        }
        and not legacy_language_is_negative(legacy_language)
    ):
        observed_codes = normalize_language_codes(
            legacy_language
        )

        # Some legacy rows use language_code for the observed language.
        if not observed_codes:
            legacy_code = normalize_language_code(
                str(item.get("language_code") or "")
            )

            if legacy_code:
                observed_codes = [legacy_code]

    raw_match = str(
        item.get("language_match") or ""
    ).strip()

    if raw_match:
        explicit_match = normalize_language_match(
            raw_match
        )

        if explicit_match:
            return (
                expected_codes,
                observed_codes,
                explicit_match,
            )

    # Backwards compatibility with old audit rows.
    if (
        legacy_language_is_negative(legacy_language)
        or normalize_test_status(
            str(item.get("vlc") or "")
        ) == "wrong_language"
        or normalize_test_status(
            str(item.get("samsung") or "")
        ) == "wrong_language"
    ):
        return expected_codes, observed_codes, "no"

    return (
        expected_codes,
        observed_codes,
        derive_language_match(
            expected_codes,
            observed_codes,
        ),
    )

def format_language_codes(codes) -> str:
    normalized = normalize_language_codes(codes)

    if not normalized:
        return "Unknown"

    return ", ".join(normalized)

def language_mismatch_reason(
    expected_codes: list[str],
    observed_codes: list[str],
) -> str:
    if expected_codes and observed_codes:
        return (
            "Observed language(s) "
            f"{format_language_codes(observed_codes)} "
            "do not match expected language(s) "
            f"{format_language_codes(expected_codes)}."
        )

    if observed_codes:
        return (
            "Observed language(s) "
            f"{format_language_codes(observed_codes)} "
            "were marked as not matching this playlist."
        )

    return (
        "Observed language does not match the expected "
        "playlist language."
    )

def configured_playlist_country_codes(cfg: dict) -> list[str]:
    """Return publication-country codes enabled by country_outputs."""
    return configured_country_codes(cfg)

def configured_playlist_language_codes(cfg: dict) -> list[str]:
    """Legacy API alias for the old country-as-language configuration."""
    return configured_playlist_country_codes(cfg)

def configured_spoken_language_codes(cfg: dict) -> list[str]:
    """Return supported spoken languages independently of country outputs."""
    return configured_language_codes(cfg)

def audit_playlist_country_code(item: dict) -> str:
    """Return the country bucket to which a saved audit identity belongs."""
    for field in ("playlist_country_code", "playlist_language_code", "country_code"):
        code = normalize_country_code(str(item.get(field) or ""))
        if code:
            return code

    # Compatibility for old rows whose only scope hint was ["HU"]/["SK"]/["CZ"].
    raw_expected = item.get("expected_language_codes")
    if isinstance(raw_expected, list) and len(raw_expected) == 1:
        legacy = legacy_country_scope_from_language_token(raw_expected[0])
        if legacy:
            return legacy
    return ""

def audit_playlist_scope_code(item: dict) -> str:
    """Legacy compatibility alias."""
    return audit_playlist_country_code(item)

def verified_output_country_code(
    audit_row: dict,
    source_country_code: str,
    cfg: dict,
) -> str:
    """Choose publication country without assuming language and country are equivalent."""
    source_code = normalize_country_code(source_country_code) or "HU"
    configured = set(configured_playlist_country_codes(cfg))

    explicit = normalize_country_code(
        str(audit_row.get("output_country_code") or audit_row.get("output_language_code") or "")
    )
    if explicit and (not configured or explicit in configured):
        return explicit

    decision = str(audit_row.get("decision") or "").strip()
    if decision not in {"Verified", "TV verified"}:
        return source_code

    if "verified_country_routes" not in cfg:
        return verified_output_language_code(
            audit_row,
            source_code,
            configured_playlist_country_codes(cfg),
        )

    routed = verified_country_route(
        cfg,
        source_code,
        audit_row.get("observed_language_codes"),
    )
    if routed and (not configured or routed in configured):
        return routed
    return source_code

def verified_output_language_code(
    audit_row: dict,
    source_language_code: str,
    supported_language_codes=None,
) -> str:
    """Legacy helper preserving old HU/SK/CZ one-to-one behavior for callers/tests."""
    source_code = normalize_country_code(source_language_code) or "HU"
    decision = str(audit_row.get("decision") or "").strip()
    if decision not in {"Verified", "TV verified"}:
        return source_code
    observed = normalize_spoken_language_codes(audit_row.get("observed_language_codes"))
    if len(observed) != 1:
        return source_code
    destination_by_language = {"hun": "HU", "slk": "SK", "ces": "CZ"}
    destination = destination_by_language.get(observed[0], "")
    supported_countries = {
        normalize_country_code(str(value or ""))
        for value in (supported_language_codes or [])
    }
    if destination and destination in supported_countries:
        return destination
    return source_code

def language_acceptance_state(
    item: dict,
    supported_language_codes=None,
) -> str:
    """
    Separate spoken-language acceptance from playlist placement.

    match                    expected spoken language is present
    supported_cross_language observed language differs, but is one of the
                             currently published HU/SK/CZ-style languages
    unsupported              observed language is outside current support
    unknown                  language has not been confirmed
    """
    (
        expected_codes,
        observed_codes,
        language_match,
    ) = resolve_language_info(item)

    supported = normalize_spoken_language_codes(
        supported_language_codes
    )
    observed_supported = normalize_spoken_language_codes(observed_codes)

    if language_match in {
        "yes",
        "multilingual",
    }:
        return "match"

    if language_match == "no":
        if (
            observed_codes
            and supported
            and set(observed_supported).intersection(
                supported
            )
        ):
            return "supported_cross_language"

        return "unsupported"

    return "unknown"


def country_name_for_code(
    cfg: dict,
    country_code: str,
) -> str:
    """Return the human-readable name for one publication country."""
    code = normalize_country_code(country_code) or str(country_code or "").strip().upper()
    country_names = cfg.get("country_names") or {}
    if isinstance(country_names, dict):
        country = str(country_names.get(code) or "").strip()
        if country:
            return country
    return code or "Other"

def country_name_for_language(
    cfg: dict,
    language_code: str,
) -> str:
    """Legacy compatibility alias: historical language_code stored country scope."""
    return country_name_for_code(cfg, language_code)

def route_candidates_to_verified_countries(
    candidates: list[dict],
    cfg: dict,
) -> list[dict]:
    """Apply country routing and attach verified observed spoken-language metadata."""
    supported = set(configured_playlist_country_codes(cfg))
    routed: list[dict] = []
    for entry in candidates:
        candidate = dict(entry)
        source_code = (
            normalize_country_code(
                str(
                    candidate.get("country_code")
                    or candidate.get("language_code")
                    or cfg.get("default_country_code")
                    or cfg.get("default_language_code")
                    or "HU"
                )
            )
            or "HU"
        )
        audit = candidate.get("_audit") or {}
        decision = str(candidate.get("_decision") or audit.get("decision") or "").strip()
        observed_languages = normalize_spoken_language_codes(
            audit.get("observed_language_codes")
        )
        if decision in {"Verified", "TV verified"} and observed_languages:
            candidate["language_codes"] = observed_languages
        else:
            candidate["language_codes"] = normalize_spoken_language_codes(
                candidate.get("language_codes")
            )

        output_code = normalize_country_code(
            str(audit.get("output_country_code") or audit.get("output_language_code") or "")
        ) or verified_output_country_code(
            audit,
            source_code,
            cfg,
        )
        if output_code not in supported:
            output_code = source_code
        candidate["source_country_code"] = source_code
        candidate["country_code"] = output_code
        # Legacy entry alias retained so older report/dashboard code keeps working.
        candidate["language_code"] = output_code
        candidate["country_name"] = country_name_for_code(cfg, output_code)
        routed.append(candidate)
    return routed

def route_candidates_to_verified_languages(
    candidates: list[dict],
    cfg: dict,
) -> list[dict]:
    """Legacy compatibility alias."""
    return route_candidates_to_verified_countries(candidates, cfg)

def build_language_catalog_entries(
    country_entries: list[dict],
    language_only_entries: list[dict],
) -> list[dict]:
    """Build a URL-unique catalog for spoken-language playlists.

    Existing country entries are inserted first and therefore keep authority
    for an exact URL already published by the country build. A language-only
    duplicate may still add additional spoken-language metadata, but it cannot
    steal or rewrite the established country identity.
    """
    result: list[dict] = []
    by_url: dict[str, dict] = {}

    for entry in [*country_entries, *language_only_entries]:
        url = str(entry.get("url") or "").strip()
        url_key = canonical_stream_url(url)
        if not url_key:
            continue

        languages = normalize_spoken_language_codes(
            entry.get("language_codes")
        )

        current = by_url.get(url_key)
        if current is not None:
            current["language_codes"] = normalize_spoken_language_codes(
                [
                    *(current.get("language_codes") or []),
                    *languages,
                ]
            )
            continue

        candidate = dict(entry)
        candidate["language_codes"] = languages
        by_url[url_key] = candidate
        result.append(candidate)

    return result

def entries_for_spoken_language(
    entries: list[dict],
    language_code: str,
) -> list[dict]:
    """Return entries explicitly carrying one normalized spoken language."""
    code = normalize_spoken_language_code(language_code)
    if not code:
        raise ValueError(f"Unsupported spoken language code: {language_code!r}")

    return [
        entry
        for entry in entries
        if code in normalize_spoken_language_codes(
            entry.get("language_codes")
        )
    ]
