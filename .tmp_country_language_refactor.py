from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_region(text: str, start: str, end: str, new: str, label: str) -> str:
    start_i = text.find(start)
    if start_i < 0:
        raise SystemExit(f"{label}: start marker not found")
    end_i = text.find(end, start_i)
    if end_i < 0:
        raise SystemExit(f"{label}: end marker not found")
    return text[:start_i] + new.rstrip() + "\n\n" + text[end_i:]


# ---------------------------------------------------------------------------
# build.py
# ---------------------------------------------------------------------------
path = ROOT / "build.py"
text = path.read_text(encoding="utf-8")

text = replace_once(
    text,
    "from identity_overrides import IdentityRegistry, load_identity_registry\n",
    "from identity_overrides import IdentityRegistry, load_identity_registry\n"
    "from country_language import (\n"
    "    configured_country_codes,\n"
    "    configured_language_codes,\n"
    "    legacy_country_scope_from_language_token,\n"
    "    normalize_country_code,\n"
    "    normalize_language_code as normalize_spoken_language_code,\n"
    "    normalize_language_codes as normalize_spoken_language_codes,\n"
    "    source_country_code,\n"
    "    source_language_codes,\n"
    "    verified_country_route,\n"
    ")\n",
    "build imports",
)

text = replace_once(
    text,
    '                "canonical_id": attrs.get("canonical-id", ""),\n',
    '                "canonical_id": attrs.get("canonical-id", ""),\n'
    '                "country_code": attrs.get("country-code", ""),\n'
    '                "language_codes": attrs.get("language-codes", ""),\n',
    "parse country/language attrs",
)

country_name_block = '''def country_name_for_code(\n    cfg: dict,\n    country_code: str,\n) -> str:\n    """Return the human-readable name for one publication country."""\n    code = normalize_country_code(country_code) or str(country_code or "").strip().upper()\n    country_names = cfg.get("country_names") or {}\n    if isinstance(country_names, dict):\n        country = str(country_names.get(code) or "").strip()\n        if country:\n            return country\n    return code or "Other"\n\n\ndef country_name_for_language(\n    cfg: dict,\n    language_code: str,\n) -> str:\n    """Legacy compatibility alias: historical language_code stored country scope."""\n    return country_name_for_code(cfg, language_code)'''
text = replace_region(
    text,
    "def country_name_for_language(\n",
    "def normalize_content_group(\n",
    country_name_block,
    "country name helper",
)

summary_block = '''def summarize_country_stats(\n    entries: list[dict],\n    source_stats: list[dict],\n) -> list[dict]:\n    """Summarize final publication by country, independently of language."""\n    country_codes: set[str] = set()\n    for entry in entries:\n        code = normalize_country_code(\n            str(entry.get("country_code") or entry.get("language_code") or "")\n        )\n        if code:\n            country_codes.add(code)\n    for source in source_stats:\n        code = normalize_country_code(\n            str(source.get("country_code") or source.get("language_code") or "")\n        )\n        if code:\n            country_codes.add(code)\n\n    result: list[dict] = []\n    for code in sorted(country_codes):\n        country_entries = [\n            entry for entry in entries\n            if normalize_country_code(\n                str(entry.get("country_code") or entry.get("language_code") or "")\n            ) == code\n        ]\n        country_sources = [\n            source for source in source_stats\n            if normalize_country_code(\n                str(source.get("country_code") or source.get("language_code") or "")\n            ) == code\n        ]\n        unique_channel_keys = {\n            entry.get("channel_key") for entry in country_entries if entry.get("channel_key")\n        }\n        base_channel_keys = {\n            entry.get("channel_key") for entry in country_entries\n            if entry.get("channel_key") and entry.get("classification") == "Base channel"\n        }\n        added_channel_keys = {\n            entry.get("channel_key") for entry in country_entries\n            if entry.get("channel_key") and entry.get("classification") == "Added channel"\n        }\n        result.append({\n            "country_code": code,\n            "source_count": len(country_sources),\n            "base_source_count": sum(1 for source in country_sources if source.get("kind") == "base"),\n            "unique_channels": len(unique_channel_keys),\n            "stream_urls": len(country_entries),\n            "base_channels": len(base_channel_keys),\n            "added_channels": len(added_channel_keys),\n            "alternative_streams": sum(\n                1 for entry in country_entries\n                if entry.get("classification") == "Alternative stream"\n            ),\n        })\n    return result\n\n\ndef summarize_language_stats(\n    entries: list[dict],\n    source_stats: list[dict],\n) -> list[dict]:\n    """Summarize actual spoken-language metadata using ISO-639-3 codes."""\n    language_codes: set[str] = set()\n    for entry in entries:\n        language_codes.update(normalize_language_codes(entry.get("language_codes")))\n    for source in source_stats:\n        language_codes.update(normalize_language_codes(source.get("language_codes")))\n\n    result: list[dict] = []\n    for code in sorted(language_codes):\n        language_entries = [\n            entry for entry in entries\n            if code in normalize_language_codes(entry.get("language_codes"))\n        ]\n        language_sources = [\n            source for source in source_stats\n            if code in normalize_language_codes(source.get("language_codes"))\n        ]\n        unique_channel_keys = {\n            entry.get("channel_key") for entry in language_entries if entry.get("channel_key")\n        }\n        base_channel_keys = {\n            entry.get("channel_key") for entry in language_entries\n            if entry.get("channel_key") and entry.get("classification") == "Base channel"\n        }\n        added_channel_keys = {\n            entry.get("channel_key") for entry in language_entries\n            if entry.get("channel_key") and entry.get("classification") == "Added channel"\n        }\n        result.append({\n            "language_code": code,\n            "source_count": len(language_sources),\n            "base_source_count": sum(1 for source in language_sources if source.get("kind") == "base"),\n            "unique_channels": len(unique_channel_keys),\n            "stream_urls": len(language_entries),\n            "base_channels": len(base_channel_keys),\n            "added_channels": len(added_channel_keys),\n            "alternative_streams": sum(\n                1 for entry in language_entries\n                if entry.get("classification") == "Alternative stream"\n            ),\n        })\n    return result'''
text = replace_region(
    text,
    "def summarize_language_stats(\n",
    "def load_previous_report(\n",
    summary_block,
    "stats split",
)

# Keep the old singular helper for legacy audit/country tokens. Spoken-language
# lists now use the ISO-639-3 normalizer from country_language.py.
text = replace_region(
    text,
    "def normalize_language_codes(value) -> list[str]:\n",
    "def normalize_language_match(value: str) -> str:\n",
    '''def normalize_language_codes(value) -> list[str]:\n    """Normalize spoken-language lists to ISO-639-3 while accepting legacy values."""\n    return normalize_spoken_language_codes(value)''',
    "spoken language list normalizer",
)

text = replace_once(
    text,
    "            legacy_code = normalize_language_code(\n                str(item.get(\"language_code\") or \"\")\n            )\n",
    "            legacy_code = normalize_spoken_language_code(\n                str(item.get(\"language_code\") or \"\")\n            )\n",
    "legacy observed language conversion",
)

logical_block = '''def logical_channel_key(entry: dict) -> str:\n    """Identify one logical channel inside one publication country."""\n    country_code = (\n        normalize_country_code(\n            str(entry.get("country_code") or entry.get("language_code") or "")\n        )\n        or "UNKNOWN"\n    )\n    raw_key = str(entry.get("channel_key") or channel_key(entry))\n    prefix = f"{country_code}:"\n    if raw_key.startswith(prefix):\n        return raw_key\n    return f"{prefix}{raw_key}"'''
text = replace_region(
    text,
    "def logical_channel_key(entry: dict) -> str:\n",
    "def normalize_language_codes(value) -> list[str]:\n",
    logical_block,
    "country-scoped logical key",
)

configured_block = '''def configured_playlist_country_codes(cfg: dict) -> list[str]:\n    """Return publication-country codes enabled by country_outputs."""\n    return configured_country_codes(cfg)\n\n\ndef configured_playlist_language_codes(cfg: dict) -> list[str]:\n    """Legacy API alias for the old country-as-language configuration."""\n    return configured_playlist_country_codes(cfg)\n\n\ndef configured_spoken_language_codes(cfg: dict) -> list[str]:\n    """Return supported spoken languages independently of country outputs."""\n    return configured_language_codes(cfg)'''
text = replace_region(
    text,
    "def configured_playlist_language_codes(cfg: dict) -> list[str]:\n",
    "def audit_playlist_scope_code(item: dict) -> str:\n",
    configured_block,
    "configured countries/languages",
)

audit_scope_block = '''def audit_playlist_country_code(item: dict) -> str:\n    """Return the country bucket to which a saved audit identity belongs."""\n    for field in ("playlist_country_code", "playlist_language_code", "country_code"):\n        code = normalize_country_code(str(item.get(field) or ""))\n        if code:\n            return code\n\n    # Compatibility for old rows whose only scope hint was ["HU"]/["SK"]/["CZ"].\n    raw_expected = item.get("expected_language_codes")\n    if isinstance(raw_expected, list) and len(raw_expected) == 1:\n        legacy = legacy_country_scope_from_language_token(raw_expected[0])\n        if legacy:\n            return legacy\n    return ""\n\n\ndef audit_playlist_scope_code(item: dict) -> str:\n    """Legacy compatibility alias."""\n    return audit_playlist_country_code(item)'''
text = replace_region(
    text,
    "def audit_playlist_scope_code(item: dict) -> str:\n",
    "def verified_output_language_code(\n",
    audit_scope_block,
    "audit country scope",
)

verified_output_block = '''def verified_output_country_code(\n    audit_row: dict,\n    source_country_code: str,\n    cfg: dict,\n) -> str:\n    """Choose publication country without assuming language and country are equivalent."""\n    source_code = normalize_country_code(source_country_code) or "HU"\n    configured = set(configured_playlist_country_codes(cfg))\n\n    explicit = normalize_country_code(\n        str(audit_row.get("output_country_code") or audit_row.get("output_language_code") or "")\n    )\n    if explicit and (not configured or explicit in configured):\n        return explicit\n\n    decision = str(audit_row.get("decision") or "").strip()\n    if decision not in {"Verified", "TV verified"}:\n        return source_code\n\n    routed = verified_country_route(\n        cfg,\n        source_code,\n        audit_row.get("observed_language_codes"),\n    )\n    if routed and (not configured or routed in configured):\n        return routed\n    return source_code\n\n\ndef verified_output_language_code(\n    audit_row: dict,\n    source_language_code: str,\n    supported_language_codes=None,\n) -> str:\n    """Legacy helper preserving old HU/SK/CZ one-to-one behavior for callers/tests."""\n    source_code = normalize_country_code(source_language_code) or "HU"\n    decision = str(audit_row.get("decision") or "").strip()\n    if decision not in {"Verified", "TV verified"}:\n        return source_code\n    observed = normalize_language_codes(audit_row.get("observed_language_codes"))\n    if len(observed) != 1:\n        return source_code\n    destination_by_language = {"hun": "HU", "slk": "SK", "ces": "CZ"}\n    destination = destination_by_language.get(observed[0], "")\n    supported_countries = {\n        normalize_country_code(str(value or ""))\n        for value in (supported_language_codes or [])\n    }\n    if destination and destination in supported_countries:\n        return destination\n    return source_code'''
text = replace_region(
    text,
    "def verified_output_language_code(\n",
    "def language_acceptance_state(\n",
    verified_output_block,
    "verified output country",
)

exact_scope_block = '''def exact_url_audit_matches_entry(\n    audit_item: dict,\n    entry: dict,\n) -> bool:\n    """Guard exact-URL audit history by source country, not spoken language."""\n    audit_scope = audit_playlist_country_code(audit_item)\n    if not audit_scope:\n        return True\n    entry_scope = normalize_country_code(\n        str(entry.get("country_code") or entry.get("language_code") or "")\n    )\n    if not entry_scope:\n        return True\n    return audit_scope == entry_scope'''
text = replace_region(
    text,
    "def exact_url_audit_matches_entry(\n",
    "def validate_audit_items(\n",
    exact_scope_block,
    "exact audit country guard",
)

# Audit validation: keep spoken expectations and country identity in separate maps.
text = replace_once(
    text,
    "    current_expected_by_url: dict[str, set[str]] = {}\n    current_expected_by_tvg: dict[str, set[str]] = {}\n    current_expected_by_name: dict[str, set[str]] = {}\n",
    "    current_expected_by_url: dict[str, set[str]] = {}\n"
    "    current_expected_by_tvg: dict[str, set[str]] = {}\n"
    "    current_expected_by_name: dict[str, set[str]] = {}\n"
    "    current_country_by_url: dict[str, set[str]] = {}\n",
    "validation country map",
)
text = replace_once(
    text,
    "        expected_codes = normalize_language_codes(\n            entry.get(\"expected_language_codes\")\n            or entry.get(\"language_code\")\n        )\n",
    "        expected_codes = normalize_language_codes(\n"
    "            entry.get(\"expected_language_codes\")\n"
    "            or entry.get(\"language_codes\")\n"
    "            or entry.get(\"language_code\")\n"
    "        )\n"
    "        entry_country = normalize_country_code(\n"
    "            str(entry.get(\"country_code\") or entry.get(\"language_code\") or \"\")\n"
    "        )\n"
    "        if entry_country:\n"
    "            current_country_by_url.setdefault(url_key, set()).add(entry_country)\n",
    "validation spoken expectations",
)
text = replace_once(
    text,
    "        current_url_expected = (\n            sorted(\n                current_expected_by_url.get(\n                    url_key,\n                    set(),\n                )\n            )\n            if url_key\n            else []\n        )\n",
    "        current_url_countries = (\n"
    "            sorted(current_country_by_url.get(url_key, set()))\n"
    "            if url_key else []\n"
    "        )\n",
    "validation current country lookup",
)
text = text.replace("and current_url_expected\n            and saved_playlist_scope\n            not in current_url_expected", "and current_url_countries\n            and saved_playlist_scope\n            not in current_url_countries", 1)
text = text.replace("f\"{', '.join(current_url_expected)}, but the saved audit \"", "f\"{', '.join(current_url_countries)}, but the saved audit \"", 1)

# prepare_audit_rows accepts cfg for explicit country routing while preserving old callers.
text = replace_once(
    text,
    "def prepare_audit_rows(\n    audit_items: list[dict],\n    final_entries: list[dict],\n    supported_language_codes=None,\n) -> list[dict]:\n",
    "def prepare_audit_rows(\n"
    "    audit_items: list[dict],\n"
    "    final_entries: list[dict],\n"
    "    supported_language_codes=None,\n"
    "    cfg: dict | None = None,\n"
    ") -> list[dict]:\n",
    "prepare audit signature",
)
text = replace_once(
    text,
    "            \"expected_language_codes\": (\n                normalize_language_codes(\n                    entry.get(\"language_code\") or \"HU\"\n                )\n            ),\n",
    "            \"expected_language_codes\": (\n"
    "                normalize_language_codes(\n"
    "                    entry.get(\"language_codes\")\n"
    "                    or entry.get(\"language_code\")\n"
    "                    or \"HU\"\n"
    "                )\n"
    "            ),\n"
    "            \"country_code\": (\n"
    "                normalize_country_code(\n"
    "                    str(entry.get(\"country_code\") or entry.get(\"language_code\") or \"HU\")\n"
    "                )\n"
    "                or \"HU\"\n"
    "            ),\n"
    "            \"language_codes\": normalize_language_codes(\n"
    "                entry.get(\"language_codes\") or entry.get(\"language_code\") or \"HU\"\n"
    "            ),\n",
    "audit default country/language",
)
text = replace_once(
    text,
    "            \"playlist_language_code\": (\n                normalize_language_code(\n                    str(\n                        entry.get(\"language_code\")\n                        or \"HU\"\n                    )\n                )\n                or \"HU\"\n            ),\n",
    "            \"playlist_country_code\": (\n"
    "                normalize_country_code(\n"
    "                    str(entry.get(\"country_code\") or entry.get(\"language_code\") or \"HU\")\n"
    "                )\n"
    "                or \"HU\"\n"
    "            ),\n"
    "            # Legacy alias: this field historically stored country scope.\n"
    "            \"playlist_language_code\": (\n"
    "                normalize_country_code(\n"
    "                    str(entry.get(\"country_code\") or entry.get(\"language_code\") or \"HU\")\n"
    "                )\n"
    "                or \"HU\"\n"
    "            ),\n",
    "audit playlist country",
)
text = replace_once(
    text,
    "            default_expected=(\n                entry.get(\"language_code\")\n                or \"HU\"\n            ),\n",
    "            default_expected=(\n"
    "                entry.get(\"language_codes\")\n"
    "                or entry.get(\"language_code\")\n"
    "                or \"HU\"\n"
    "            ),\n",
    "audit default expected spoken language",
)
text = replace_once(
    text,
    "        item[\n            \"playlist_language_code\"\n        ] = (\n            normalize_language_code(\n                str(\n                    item.get(\n                        \"playlist_language_code\"\n                    )\n                    or entry.get(\n                        \"language_code\"\n                    )\n                    or \"HU\"\n                )\n            )\n            or \"HU\"\n        )\n",
    "        playlist_country_code = (\n"
    "            normalize_country_code(\n"
    "                str(\n"
    "                    item.get(\"playlist_country_code\")\n"
    "                    or item.get(\"playlist_language_code\")\n"
    "                    or entry.get(\"country_code\")\n"
    "                    or entry.get(\"language_code\")\n"
    "                    or \"HU\"\n"
    "                )\n"
    "            )\n"
    "            or \"HU\"\n"
    "        )\n"
    "        item[\"playlist_country_code\"] = playlist_country_code\n"
    "        item[\"playlist_language_code\"] = playlist_country_code\n",
    "normalize audit playlist country",
)
text = replace_once(
    text,
    "        output_language_code = (\n            verified_output_language_code(\n                {\n                    **item,\n                    \"decision\": decision,\n                    \"observed_language_codes\": (\n                        observed_codes\n                    ),\n                },\n                str(\n                    entry.get(\n                        \"language_code\"\n                    )\n                    or \"\"\n                ),\n                supported_language_codes,\n            )\n        )\n",
    "        route_probe = {\n"
    "            **item,\n"
    "            \"decision\": decision,\n"
    "            \"observed_language_codes\": observed_codes,\n"
    "        }\n"
    "        if cfg is not None:\n"
    "            output_country_code = verified_output_country_code(\n"
    "                route_probe,\n"
    "                str(entry.get(\"country_code\") or entry.get(\"language_code\") or \"\"),\n"
    "                cfg,\n"
    "            )\n"
    "        else:\n"
    "            output_country_code = verified_output_language_code(\n"
    "                route_probe,\n"
    "                str(entry.get(\"country_code\") or entry.get(\"language_code\") or \"\"),\n"
    "                configured_country_codes({\"country_outputs\": {code: \"\" for code in (\"HU\", \"SK\", \"CZ\")}}),\n"
    "            )\n"
    "        output_language_code = output_country_code\n",
    "audit output country resolution",
)
text = replace_once(
    text,
    "            # New language model.\n            \"playlist_language_code\": str(\n",
    "            # Country scope and publication destination.\n"
    "            \"playlist_country_code\": str(\n"
    "                item.get(\"playlist_country_code\")\n"
    "                or item.get(\"playlist_language_code\")\n"
    "                or entry.get(\"country_code\")\n"
    "                or entry.get(\"language_code\")\n"
    "                or \"\"\n"
    "            ).strip().upper(),\n"
    "            \"output_country_code\": output_country_code,\n"
    "            # Legacy aliases retained for old exports/tools.\n"
    "            \"playlist_language_code\": str(\n",
    "audit output row country fields",
)
text = replace_once(
    text,
    "            \"output_language_code\": output_language_code,\n            \"expected_language_codes\": expected_codes,\n",
    "            \"output_language_code\": output_language_code,\n"
    "            \"language_codes\": normalize_language_codes(\n"
    "                entry.get(\"language_codes\") or expected_codes\n"
    "            ),\n"
    "            \"expected_language_codes\": expected_codes,\n",
    "audit row spoken fields",
)

# Historical audit loop: keep current source country and spoken expectations separate.
text = replace_once(
    text,
    "    current_expected_by_url: dict[str, set[str]] = {}\n\n    for entry in final_entries:\n",
    "    current_expected_by_url: dict[str, set[str]] = {}\n"
    "    current_country_by_url: dict[str, set[str]] = {}\n\n"
    "    for entry in final_entries:\n",
    "historical country map",
)
text = replace_once(
    text,
    "        expected_codes = normalize_language_codes(\n            entry.get(\"language_code\")\n            or \"HU\"\n        )\n",
    "        expected_codes = normalize_language_codes(\n"
    "            entry.get(\"language_codes\")\n"
    "            or entry.get(\"language_code\")\n"
    "            or \"HU\"\n"
    "        )\n"
    "        current_country = normalize_country_code(\n"
    "            str(entry.get(\"country_code\") or entry.get(\"language_code\") or \"\")\n"
    "        )\n"
    "        if current_country:\n"
    "            current_country_by_url.setdefault(current_url_key, set()).add(current_country)\n",
    "historical expected spoken languages",
)
text = replace_once(
    text,
    "            current_expected = sorted(\n                current_expected_by_url.get(\n                    url_key,\n                    set(),\n                )\n            )\n\n            if (\n                saved_scope\n                and current_expected\n                and saved_scope\n                not in current_expected\n            ):\n",
    "            current_countries = sorted(\n"
    "                current_country_by_url.get(url_key, set())\n"
    "            )\n\n"
    "            if (\n"
    "                saved_scope\n"
    "                and current_countries\n"
    "                and saved_scope\n"
    "                not in current_countries\n"
    "            ):\n",
    "historical identity country comparison",
)
text = text.replace("f\"{format_language_codes(current_expected)}, so this \"", "f\"{', '.join(current_countries)}, so this \"", 1)

# Add modern country fields to historical exported audit rows.
text = replace_once(
    text,
    "            # New language model.\n            \"playlist_language_code\": str(\n                item.get(\n                    \"playlist_language_code\"\n                )\n                or \"\"\n            ).strip().upper(),\n",
    "            # Modern country model plus legacy alias.\n"
    "            \"playlist_country_code\": str(\n"
    "                item.get(\"playlist_country_code\")\n"
    "                or item.get(\"playlist_language_code\")\n"
    "                or \"\"\n"
    "            ).strip().upper(),\n"
    "            \"output_country_code\": str(\n"
    "                item.get(\"output_country_code\")\n"
    "                or item.get(\"output_language_code\")\n"
    "                or \"\"\n"
    "            ).strip().upper(),\n"
    "            \"playlist_language_code\": str(\n"
    "                item.get(\"playlist_country_code\")\n"
    "                or item.get(\"playlist_language_code\")\n"
    "                or \"\"\n"
    "            ).strip().upper(),\n",
    "historical country export fields",
)

# Route candidates by explicit output country instead of observed-language bucket.
route_block = '''def route_candidates_to_verified_countries(\n    candidates: list[dict],\n    cfg: dict,\n) -> list[dict]:\n    """Apply audit publication-country decisions without changing spoken language metadata."""\n    supported = set(configured_playlist_country_codes(cfg))\n    routed: list[dict] = []\n    for entry in candidates:\n        candidate = dict(entry)\n        source_code = (\n            normalize_country_code(\n                str(\n                    candidate.get("country_code")\n                    or candidate.get("language_code")\n                    or cfg.get("default_country_code")\n                    or cfg.get("default_language_code")\n                    or "HU"\n                )\n            )\n            or "HU"\n        )\n        audit = candidate.get("_audit") or {}\n        output_code = normalize_country_code(\n            str(audit.get("output_country_code") or audit.get("output_language_code") or "")\n        ) or source_code\n        if output_code not in supported:\n            output_code = source_code\n        candidate["source_country_code"] = source_code\n        candidate["country_code"] = output_code\n        # Legacy entry alias retained so older report/dashboard code keeps working.\n        candidate["language_code"] = output_code\n        candidate["country_name"] = country_name_for_code(cfg, output_code)\n        routed.append(candidate)\n    return routed\n\n\ndef route_candidates_to_verified_languages(\n    candidates: list[dict],\n    cfg: dict,\n) -> list[dict]:\n    """Legacy compatibility alias."""\n    return route_candidates_to_verified_countries(candidates, cfg)'''
text = replace_region(
    text,
    "def route_candidates_to_verified_languages(\n",
    "def stable_block_reason(\n",
    route_block,
    "candidate country routing",
)
text = text.replace("route_candidates_to_verified_languages(\n", "route_candidates_to_verified_countries(\n")

# Publication formatting uses country_code; [HU]/[SK]/[CZ] remain unchanged visually.
text = replace_once(
    text,
    "            lang = str(\n                entry.get(\n                    \"language_code\"\n                )\n                or cfg.get(\n                    \"default_language_code\"\n                )\n                or \"HU\"\n            ).upper()\n",
    "            country_code = (\n"
    "                normalize_country_code(\n"
    "                    str(\n"
    "                        entry.get(\"country_code\")\n"
    "                        or entry.get(\"language_code\")\n"
    "                        or cfg.get(\"default_country_code\")\n"
    "                        or cfg.get(\"default_language_code\")\n"
    "                        or \"HU\"\n"
    "                    )\n"
    "                )\n"
    "                or \"HU\"\n"
    "            )\n",
    "published country variable",
)
text = text.replace('f"[{lang} {suffix}] "', 'f"[{country_code} {suffix}] "')
text = text.replace("country_name_for_language(\n                    cfg,\n                    lang,\n                )", "country_name_for_code(\n                    cfg,\n                    country_code,\n                )")
text = text.replace("language_code=lang,", "language_code=country_code,")
text = replace_once(
    text,
    "            published[\n                \"country_name\"\n            ] = country_name\n",
    "            published[\"country_code\"] = country_code\n"
    "            published[\"language_code\"] = country_code  # legacy alias\n"
    "            published[\n                \"country_name\"\n            ] = country_name\n",
    "published country metadata",
)

# M3U writer keeps old name_style='language' as alias but treats it as country.
text = text.replace("      language -> [HU] / [SK] / [CZ] (shared stable playlist)", "      country  -> [HU] / [SK] / [CZ] (shared stable playlist)\n      language -> legacy alias for country")
text = replace_once(
    text,
    '        "language",\n        "plain",\n',
    '        "language",\n        "country",\n        "plain",\n',
    "name style country option",
)
text = replace_once(
    text,
    "            if name_style == \"language\":\n                language_code = str(\n                    entry.get(\"language_code\")\n                    or cfg.get(\"default_language_code\")\n                    or \"HU\"\n                ).strip().upper()\n\n                output_name = (\n                    f\"[{language_code}] {original_display}\"\n                )\n",
    "            if name_style in {\"language\", \"country\"}:\n"
    "                country_code = (\n"
    "                    normalize_country_code(\n"
    "                        str(\n"
    "                            entry.get(\"country_code\")\n"
    "                            or entry.get(\"language_code\")\n"
    "                            or cfg.get(\"default_country_code\")\n"
    "                            or cfg.get(\"default_language_code\")\n"
    "                            or \"HU\"\n"
    "                        )\n"
    "                    )\n"
    "                    or \"HU\"\n"
    "                )\n"
    "                output_name = f\"[{country_code}] {original_display}\"\n",
    "stable prefix country",
)

# Dashboard wrapper takes both country and spoken-language summaries.
text = replace_once(
    text,
    "    source_stats: list[dict],\n    language_stats: list[dict],\n",
    "    source_stats: list[dict],\n    country_stats: list[dict],\n    language_stats: list[dict],\n",
    "make_dashboard signature",
)
text = replace_once(
    text,
    "        source_stats=source_stats,\n        language_stats=language_stats,\n",
    "        source_stats=source_stats,\n        country_stats=country_stats,\n        language_stats=language_stats,\n",
    "dashboard render call",
)

# Main model: supported spoken languages are no longer inferred from output countries.
text = replace_once(
    text,
    "    supported_language_codes = (\n        configured_playlist_language_codes(\n            cfg\n        )\n    )\n",
    "    supported_language_codes = configured_spoken_language_codes(cfg)\n"
    "    supported_country_codes = configured_playlist_country_codes(cfg)\n",
    "main supported model",
)

text = replace_once(
    text,
    "        language_code = (\n            normalize_language_code(\n                str(\n                    spec.get(\"language_code\")\n                    or cfg.get(\n                        \"default_language_code\"\n                    )\n                    or \"HU\"\n                )\n            )\n            or \"HU\"\n        )\n",
    "        country_code = source_country_code(spec, cfg)\n"
    "        language_codes = source_language_codes(spec, cfg, country_code)\n"
    "        # Historical config/build code called this country bucket language_code.\n"
    "        language_code = country_code\n",
    "source country/language resolution",
)
text = replace_once(
    text,
    "            entry[\"source\"] = name\n            entry[\"source_kind\"] = kind\n            entry[\"language_code\"] = language_code\n",
    "            entry[\"source\"] = name\n"
    "            entry[\"source_kind\"] = kind\n"
    "            entry_country = (\n"
    "                normalize_country_code(str(entry.get(\"country_code\") or \"\"))\n"
    "                or country_code\n"
    "            )\n"
    "            entry_languages = (\n"
    "                normalize_language_codes(entry.get(\"language_codes\"))\n"
    "                or list(language_codes)\n"
    "            )\n"
    "            entry[\"country_code\"] = entry_country\n"
    "            entry[\"language_codes\"] = entry_languages\n"
    "            entry[\"language_code\"] = entry_country  # legacy country alias\n",
    "entry source geography/language",
)

# Identity overrides may now own country and spoken-language identity independently.
old_identity_language = '''                raw_identity_language = str(\n                    canonical_identity.get("language_code")\n                    or ""\n                ).strip()\n\n                if raw_identity_language:\n                    identity_language = normalize_language_code(\n                        raw_identity_language\n                    )\n                    if not identity_language:\n                        raise RuntimeError(\n                            "Invalid canonical identity language_code "\n                            f"{raw_identity_language!r} for {url}"\n                        )\n                    entry["language_code"] = identity_language\n'''
new_identity_language = '''                raw_identity_country = str(\n                    canonical_identity.get("country_code")\n                    or canonical_identity.get("language_code")\n                    or ""\n                ).strip()\n                if raw_identity_country:\n                    identity_country = normalize_country_code(raw_identity_country)\n                    if not identity_country:\n                        raise RuntimeError(\n                            "Invalid canonical identity country_code "\n                            f"{raw_identity_country!r} for {url}"\n                        )\n                    entry["country_code"] = identity_country\n                    entry["language_code"] = identity_country\n\n                raw_identity_languages = canonical_identity.get("language_codes")\n                if raw_identity_languages:\n                    identity_languages = normalize_language_codes(raw_identity_languages)\n                    if not identity_languages:\n                        raise RuntimeError(\n                            "Invalid canonical identity language_codes "\n                            f"{raw_identity_languages!r} for {url}"\n                        )\n                    entry["language_codes"] = identity_languages\n'''
text = replace_once(text, old_identity_language, new_identity_language, "identity geography/language")

text = replace_once(
    text,
    "                spec.get(\"country_name\")\n                or country_name_for_language(\n                    cfg,\n                    entry[\"language_code\"],\n                )\n",
    "                spec.get(\"country_name\")\n"
    "                or country_name_for_code(\n"
    "                    cfg,\n"
    "                    entry[\"country_code\"],\n"
    "                )\n",
    "entry country name",
)
text = replace_once(
    text,
    "                language_code=entry[\"language_code\"],\n",
    "                language_code=entry[\"country_code\"],\n",
    "group country prefix compatibility",
)

text = replace_once(
    text,
    "            \"language_code\": language_code,\n            \"location\": location,\n",
    "            \"country_code\": country_code,\n"
    "            \"language_codes\": list(language_codes),\n"
    "            \"language_code\": country_code,  # legacy country alias\n"
    "            \"location\": location,\n",
    "source stats country/language",
)

text = replace_once(
    text,
    "        supported_language_codes=(\n            supported_language_codes\n        ),\n    )\n",
    "        supported_language_codes=(\n"
    "            supported_language_codes\n"
    "        ),\n"
    "        cfg=cfg,\n"
    "    )\n",
    "prepare audit cfg",
)

# Channel/report metadata and summary split.
text = replace_once(
    text,
    '            "language_code": entry.get("language_code", ""),\n            "name": entry["channel_name"],\n',
    '            "country_code": entry.get("country_code", entry.get("language_code", "")),\n'
    '            "language_codes": list(entry.get("language_codes") or []),\n'
    '            "language_code": entry.get("country_code", entry.get("language_code", "")),\n'
    '            "name": entry["channel_name"],\n',
    "channel report country/language",
)
text = replace_once(
    text,
    "    language_stats = (\n        summarize_language_stats(\n            published_entries,\n            source_stats,\n        )\n    )\n",
    "    country_stats = summarize_country_stats(published_entries, source_stats)\n"
    "    language_stats = summarize_language_stats(published_entries, source_stats)\n",
    "summary split call",
)
text = replace_once(
    text,
    '        name_style="language",\n',
    '        name_style="country",\n',
    "stable shared country prefix",
)

# Country output filtering is now explicitly country_code-based.
text = text.replace("        raw_language_code,\n        relative_path,", "        raw_country_code,\n        relative_path,")
text = replace_once(
    text,
    "        language_code = (\n            normalize_language_code(\n                str(\n                    raw_language_code\n                )\n            )\n            or str(\n                raw_language_code\n            ).strip().upper()\n        )\n",
    "        country_code = (\n"
    "            normalize_country_code(str(raw_country_code))\n"
    "            or str(raw_country_code).strip().upper()\n"
    "        )\n",
    "country output code",
)
text = replace_once(
    text,
    "                    \"language_code\"\n                )\n                or \"\"\n            ).upper()\n            == language_code\n",
    "                    \"country_code\"\n                )\n                or entry.get(\"language_code\")\n                or \"\"\n            ).upper()\n            == country_code\n",
    "country output filter",
)
text = text.replace("country_name_for_language(\n                cfg,\n                language_code,\n            )", "country_name_for_code(\n                cfg,\n                country_code,\n            )")
text = text.replace("country_playlist_counts[\n            language_code\n        ]", "country_playlist_counts[\n            country_code\n        ]")

# Inventory/report exports expose both dimensions.
text = replace_once(
    text,
    '            "country_name": e.get(\n                "country_name",\n                "",\n            ),\n',
    '            "country_code": e.get("country_code", e.get("language_code", "")),\n'
    '            "language_codes": ", ".join(e.get("language_codes") or []),\n'
    '            "country_name": e.get(\n                "country_name",\n                "",\n            ),\n',
    "inventory country/language fields",
)
text = replace_once(
    text,
    '            "country_name",\n            "content_group",\n',
    '            "country_code",\n            "language_codes",\n            "country_name",\n            "content_group",\n',
    "channels csv fields",
)
text = replace_once(
    text,
    '            "playlist_language_code",\n            "output_language_code",\n',
    '            "playlist_country_code",\n            "output_country_code",\n            "playlist_language_code",\n            "output_language_code",\n',
    "audit csv country fields",
)
text = replace_once(text, '        "schema_version": 21,\n', '        "schema_version": 22,\n', "report schema")
text = replace_once(
    text,
    '        "sources": source_stats,\n        "languages": language_stats,\n',
    '        "sources": source_stats,\n        "countries": country_stats,\n        "languages": language_stats,\n        "geography_language_model": {\n            "country_field": "country_code",\n            "language_field": "language_codes",\n            "language_standard": "ISO-639-3",\n            "legacy_country_alias_fields": [\n                "language_code",\n                "playlist_language_code",\n                "output_language_code"\n            ],\n        },\n',
    "report model metadata",
)
text = replace_once(
    text,
    "            source_stats=source_stats,\n            language_stats=language_stats,\n",
    "            source_stats=source_stats,\n            country_stats=country_stats,\n            language_stats=language_stats,\n",
    "dashboard main args",
)

# Console output labels country separately from spoken-language summary.
text = text.replace("        language_code,\n        stream_count,", "        country_code,\n        stream_count,")
text = text.replace('f"Stable {language_code}:"', 'f"Stable {country_code}:"')
text = text.replace("15 - len(language_code)", "15 - len(country_code)")
text = replace_once(
    text,
    "            f\"- [{stats['language_code']}] \"\n",
    "            f\"- [{stats['country_code']}] \"\n",
    "source console country",
)
text = replace_once(
    text,
    "    if language_stats:\n        print()\n        print(\"Language summary:\")\n\n        for stats in language_stats:\n",
    "    if country_stats:\n"
    "        print()\n"
    "        print(\"Country summary:\")\n"
    "        for stats in country_stats:\n"
    "            print(\n"
    "                f\"- {stats['country_code']}: \"\n"
    "                f\"{stats['unique_channels']} channels, \"\n"
    "                f\"{stats['stream_urls']} streams, \"\n"
    "                f\"{stats['base_channels']} base, \"\n"
    "                f\"{stats['added_channels']} added, \"\n"
    "                f\"{stats['alternative_streams']} alternatives\"\n"
    "            )\n\n"
    "    if language_stats:\n"
    "        print()\n"
    "        print(\"Spoken language summary:\")\n\n"
    "        for stats in language_stats:\n",
    "console split summaries",
)

path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# identity_overrides.py
# ---------------------------------------------------------------------------
path = ROOT / "identity_overrides.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '        "language_code",\n    }\n',
    '        "language_code",  # legacy country alias\n        "country_code",\n        "language_codes",\n    }\n',
    "identity fields",
)
text = replace_once(
    text,
    '''            identity = {\n                key: str(raw_identity.get(key) or "").strip()\n                for key in self._IDENTITY_FIELDS\n                if key in raw_identity\n            }\n''',
    '''            identity: dict = {}\n            for key in self._IDENTITY_FIELDS:\n                if key not in raw_identity:\n                    continue\n                if key == "language_codes":\n                    raw_codes = raw_identity.get(key)\n                    if not isinstance(raw_codes, list):\n                        raise RuntimeError(\n                            f"Canonical identity {canonical_id!r} language_codes "\n                            "must be a JSON list."\n                        )\n                    codes = [\n                        str(value or "").strip()\n                        for value in raw_codes\n                        if str(value or "").strip()\n                    ]\n                    if not codes:\n                        raise RuntimeError(\n                            f"Canonical identity {canonical_id!r} language_codes "\n                            "must not be empty when supplied."\n                        )\n                    identity[key] = codes\n                else:\n                    identity[key] = str(raw_identity.get(key) or "").strip()\n''',
    "identity list parsing",
)
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# config.json + identity data
# ---------------------------------------------------------------------------
path = ROOT / "config.json"
cfg = json.loads(path.read_text(encoding="utf-8"))
cfg["default_country_code"] = "HU"
cfg["default_language_codes"] = ["hun"]
cfg["country_language_defaults"] = {
    "HU": ["hun"],
    "SK": ["slk"],
    "CZ": ["ces"],
}
cfg["verified_country_routes"] = [
    {"source_country_code": "HU", "observed_language_code": "slk", "output_country_code": "SK"},
    {"source_country_code": "HU", "observed_language_code": "ces", "output_country_code": "CZ"},
    {"source_country_code": "SK", "observed_language_code": "hun", "output_country_code": "HU"},
    {"source_country_code": "SK", "observed_language_code": "ces", "output_country_code": "CZ"},
    {"source_country_code": "CZ", "observed_language_code": "hun", "output_country_code": "HU"},
    {"source_country_code": "CZ", "observed_language_code": "slk", "output_country_code": "SK"},
]
defaults = cfg["country_language_defaults"]
for section in ("sources", "extras"):
    for item in cfg.get(section, []) or []:
        if not isinstance(item, dict):
            continue
        legacy = str(item.pop("language_code", "") or "").strip().upper()
        country = str(item.get("country_code") or legacy or cfg["default_country_code"]).strip().upper()
        item["country_code"] = country
        item["language_codes"] = item.get("language_codes") or list(defaults.get(country, []))
path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

path = ROOT / "identity_overrides.json"
data = json.loads(path.read_text(encoding="utf-8"))
for identity in (data.get("identities") or {}).values():
    if not isinstance(identity, dict):
        continue
    legacy = str(identity.pop("language_code", "") or "").strip().upper()
    if legacy and not identity.get("country_code"):
        identity["country_code"] = legacy
    if legacy and not identity.get("language_codes"):
        identity["language_codes"] = list(defaults.get(legacy, []))
path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# dashboard.py
# ---------------------------------------------------------------------------
path = ROOT / "dashboard.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "    source_stats: list[dict],\n    language_stats: list[dict],\n",
    "    source_stats: list[dict],\n    country_stats: list[dict],\n    language_stats: list[dict],\n",
    "dashboard signature",
)
text = replace_once(
    text,
    "        output = normalized_country_code(row.get(\"output_language_code\"))\n",
    "        output = normalized_country_code(\n            row.get(\"output_country_code\") or row.get(\"output_language_code\")\n        )\n",
    "dashboard output country",
)
text = replace_once(
    text,
    "        scope = normalized_country_code(row.get(\"playlist_language_code\"))\n",
    "        scope = normalized_country_code(\n            row.get(\"playlist_country_code\") or row.get(\"playlist_language_code\")\n        )\n",
    "dashboard audit country",
)

# Existing language_rows was actually country summary. Split it into two tables.
start = text.find("    language_rows = \"\\n\".join(\n")
end = text.find("\n\t\n    source_row_parts = []", start)
if start < 0 or end < 0:
    raise SystemExit("dashboard summary rows block not found")
new_rows = '''    country_rows = "\\n".join(\n        f"""\n        <tr data-country="{esc(normalized_country_code(s[\"country_code\"]))}">\n          <td><strong>{esc(s[\"country_code\"])}</strong></td>\n          <td>{s[\"source_count\"]}</td>\n          <td>{s[\"base_source_count\"]}</td>\n          <td>{s[\"unique_channels\"]}</td>\n          <td>{s[\"stream_urls\"]}</td>\n          <td>{s[\"base_channels\"]}</td>\n          <td>{s[\"added_channels\"]}</td>\n          <td>{s[\"alternative_streams\"]}</td>\n        </tr>\n        """\n        for s in country_stats\n    )\n\n    language_rows = "\\n".join(\n        f"""\n        <tr>\n          <td><strong>{esc(s[\"language_code\"])}</strong></td>\n          <td>{s[\"source_count\"]}</td>\n          <td>{s[\"base_source_count\"]}</td>\n          <td>{s[\"unique_channels\"]}</td>\n          <td>{s[\"stream_urls\"]}</td>\n          <td>{s[\"base_channels\"]}</td>\n          <td>{s[\"added_channels\"]}</td>\n          <td>{s[\"alternative_streams\"]}</td>\n        </tr>\n        """\n        for s in language_stats\n    )'''
text = text[:start] + new_rows + text[end:]

text = replace_once(
    text,
    '        <tr data-country="{esc(normalized_country_code(s.get("language_code")))}">\n          <td>{esc(s["name"])}</td>\n          <td>{esc(s["language_code"])}</td>\n          <td>{esc(s["kind"])}</td>\n',
    '        <tr data-country="{esc(normalized_country_code(s.get("country_code") or s.get("language_code")))}">\n'
    '          <td>{esc(s["name"])}</td>\n'
    '          <td>{esc(s.get("country_code") or s.get("language_code"))}</td>\n'
    '          <td>{esc(", ".join(s.get("language_codes") or []) or "—")}</td>\n'
    '          <td>{esc(s["kind"])}</td>\n',
    "dashboard source dimensions",
)
text = replace_once(
    text,
    '        entry_country = normalized_country_code(e.get("language_code"))\n',
    '        entry_country = normalized_country_code(e.get("country_code") or e.get("language_code"))\n',
    "dashboard channel country",
)
text = text.replace('a.get("playlist_language_code", "")', 'a.get("playlist_country_code") or a.get("playlist_language_code", "")')
text = text.replace('a.get("output_language_code", "")', 'a.get("output_country_code") or a.get("output_language_code", "")')
text = text.replace('row.get("playlist_language_code")', 'row.get("playlist_country_code") or row.get("playlist_language_code")')
text = text.replace('row.get("output_language_code")', 'row.get("output_country_code") or row.get("output_language_code")')
text = text.replace('a.get("playlist_language_code")', 'a.get("playlist_country_code") or a.get("playlist_language_code")')
text = text.replace('a.get("output_language_code")', 'a.get("output_country_code") or a.get("output_language_code")')
text = text.replace("Verified spoken language routes this stream to", "An explicit verified country-routing rule publishes this stream under")
text = replace_once(
    text,
    '        "LANGUAGE_ROWS": str(language_rows),\n',
    '        "COUNTRY_ROWS": str(country_rows),\n        "LANGUAGE_ROWS": str(language_rows),\n',
    "dashboard country rows context",
)
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# dashboard template
# ---------------------------------------------------------------------------
path = ROOT / "templates" / "dashboard.html"
text = path.read_text(encoding="utf-8")
text = text.replace(
    "rows are verified streams whose spoken language publishes them under a different\n    country from the source/audit scope; these are informational, not duplicate channels.",
    "rows are verified streams whose explicit country-routing rule publishes them under a different\n    country from the source/audit scope; spoken language remains separate metadata.",
)
text = text.replace("<th>Audit/source scope</th>", "<th>Audit/source country</th>")
text = text.replace("<th>Published under</th>", "<th>Published country</th>")
old_summary = '''  <h2>Language summary</h2>\n\n  <p class="muted">\n    Counts are based on the final published playlist.\n    Base channels come from sources whose kind is "base".\n    Added channels were first discovered by non-base sources.\n  </p>\n\n  <div class="table-wrap">\n    <table id="languageTable">\n      <thead>\n        <tr>\n          <th>Language</th>\n          <th>Sources</th>\n          <th>Base sources</th>\n          <th>Unique channels</th>\n          <th>Stream URLs</th>\n          <th>Base channels</th>\n          <th>Added channels</th>\n          <th>Alternative streams</th>\n        </tr>\n      </thead>\n\n      <tbody>\n        @@LANGUAGE_ROWS@@\n      </tbody>\n    </table>\n  </div>\n'''
new_summary = '''  <h2>Country summary</h2>\n\n  <p class="muted">\n    Publication geography is counted independently from spoken-language metadata.\n    Country tabs filter this table; a future German-language channel can therefore\n    remain AT, DE or CH without language deciding its destination.\n  </p>\n\n  <div class="table-wrap">\n    <table id="countryTable">\n      <thead><tr><th>Country</th><th>Sources</th><th>Base sources</th><th>Unique channels</th><th>Stream URLs</th><th>Base channels</th><th>Added channels</th><th>Alternative streams</th></tr></thead>\n      <tbody>@@COUNTRY_ROWS@@</tbody>\n    </table>\n  </div>\n\n  <h2>Spoken language summary</h2>\n  <p class="muted">Languages use ISO-639-3-style codes such as hun, slk, ces and deu. One country may have several languages and one language may appear in several countries.</p>\n  <div class="table-wrap">\n    <table id="languageTable">\n      <thead><tr><th>Language</th><th>Sources</th><th>Base sources</th><th>Unique channels</th><th>Stream URLs</th><th>Base channels</th><th>Added channels</th><th>Alternative streams</th></tr></thead>\n      <tbody>@@LANGUAGE_ROWS@@</tbody>\n    </table>\n  </div>\n'''
text = replace_once(text, old_summary, new_summary, "dashboard template summaries")
text = replace_once(
    text,
    "          <th>Source</th>\n          <th>Language</th>\n          <th>Kind</th>\n",
    "          <th>Source</th>\n          <th>Country</th>\n          <th>Languages</th>\n          <th>Kind</th>\n",
    "source table headers",
)
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# README: replace the misleading language-verification model and add config doc.
# ---------------------------------------------------------------------------
path = ROOT / "README.md"
text = path.read_text(encoding="utf-8")
text = text.replace(
    "4. assigns every entry to its source/audit country scope;\n",
    "4. assigns every entry an explicit source/audit `country_code` and independent spoken `language_codes`;\n",
)
text = text.replace(
    "9. uses confirmed spoken language to route verified streams to HU, SK or CZ when the result is unambiguous;\n",
    "9. evaluates confirmed spoken language independently, then applies only explicitly configured country-routing rules;\n",
)
start = text.find("# Language verification\n")
end = text.find("\n---\n\n# Adding channels", start)
if start < 0 or end < 0:
    raise SystemExit("README language section not found")
section = '''# Country and language metadata\n\nCountry, spoken language and publication destination are separate concepts.\n\nModern source/channel metadata uses:\n\n```json\n{\n  "country_code": "AT",\n  "language_codes": ["deu"]\n}\n```\n\n`country_code` is the publication/audit geography (ISO-3166-style two-letter code). `language_codes` contains spoken/content languages using ISO-639-3-style codes such as `hun`, `slk`, `ces`, `deu`, `srp` or `ron`.\n\nManual audit rows additionally expose:\n\n```text\nplaylist_country_code\noutput_country_code\nexpected_language_codes\nobserved_language_codes\n```\n\nThe first two are countries. The latter two are spoken-language evidence. Existing audit values such as `["HU"]`, `["SK"]` and `["CZ"]` remain accepted and normalize to `hun`, `slk` and `ces`. Historical fields `language_code`, `playlist_language_code` and `output_language_code` remain supported as compatibility aliases for the old country bucket.\n\nVerified streams are **not** generically routed by language. Current HU/SK/CZ cross-routing is explicitly configured in `verified_country_routes`, for example `SK + ces -> CZ`. That preserves today's useful behavior without creating a future rule that would incorrectly force every German stream into Germany or every Hungarian stream into Hungary.\n\nThis allows models such as:\n\n```text\nAustria      -> country AT, language deu\nGermany      -> country DE, language deu\nSerbia       -> country RS, languages srp/hun\nRomania      -> country RO, languages ron/hun\nSwitzerland  -> country CH, languages deu/fra/ita\n```\n\nMultilingual or ambiguous language results are not blindly duplicated across country outputs. Country placement changes only when source geography, canonical identity, a manual output country, or an explicit verified routing rule says it should.\n'''
text = text[:start] + section + text[end:]
text = text.replace('`extras/cz.m3u` is configured with:\n\n```json\n"language_code": "CZ"\n```', '`extras/cz.m3u` is configured with:\n\n```json\n"country_code": "CZ",\n"language_codes": ["ces"]\n```')
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Permanent architecture documentation.
# ---------------------------------------------------------------------------
path = ROOT / "docs" / "country-language-model.md"
path.write_text('''# Country and spoken-language model\n\nTomas IPTV separates publication geography from spoken-language evidence.\n\n## Authoritative fields\n\n- `country_code`: ISO-3166-style publication/audit country, e.g. `HU`, `SK`, `CZ`, `AT`.\n- `language_codes`: ISO-639-3-style spoken/content languages, e.g. `hun`, `slk`, `ces`, `deu`.\n- `playlist_country_code`: country scope to which a saved audit identity belongs.\n- `output_country_code`: country output chosen for a current audited stream.\n- `expected_language_codes` / `observed_language_codes`: spoken-language evidence.\n\n## Backward compatibility\n\nHistorical `language_code`, `playlist_language_code` and `output_language_code` are still accepted. They are treated as legacy country aliases, because that is what the project historically stored in them. Old spoken-language values such as `HU`, `SK`, `CZ`, `Hungarian`, `Slovak` and `Czech` remain accepted and normalize to `hun`, `slk` and `ces`.\n\n## Routing\n\nLanguage does not globally imply country. A verified cross-country move requires either an explicit `output_country_code` or a configured `verified_country_routes` rule matching both source country and observed language. Current HU/SK/CZ behavior is represented by explicit rules such as `SK + ces -> CZ`; adding Serbia later will not cause an RS Hungarian-language channel to move to HU unless a rule explicitly says so.\n\n## Expansion examples\n\n- Austria: `country_code=AT`, `language_codes=[deu]`\n- Germany: `country_code=DE`, `language_codes=[deu]`\n- Serbia: `country_code=RS`, `language_codes=[srp, hun]`\n- Romania: `country_code=RO`, `language_codes=[ron, hun]`\n- Switzerland: `country_code=CH`, `language_codes=[deu, fra, ita]`\n\nThe dashboard and report expose country and spoken-language summaries separately.\n''', encoding="utf-8")

print("country/language refactor applied")
