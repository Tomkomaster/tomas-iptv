#!/usr/bin/env python3
"""Compact, human-maintained storage contract for ``audit.json``.

``audit.json`` is the Git-tracked authority for manual playback facts and
deliberate routing/exclusion decisions. Automated probe/health/EPG telemetry
belongs in generated Pages JSON such as ``health.json``,
``same-build-health.json`` and ``epg-health.json``.

The build enriches manual rows with derived context at runtime. The complete
operational view is published under ``report.json -> audit.channels`` and
``audit.csv`` instead of being written back into the manual source file.
"""
from __future__ import annotations

from country_language import normalize_country_code, normalize_language_codes
from iptv.playback_status import normalize_test_status


MANUAL_AUDIT_SCHEMA_VERSION = 2
MANUAL_AUDIT_STORAGE_KIND = "manual_only"

MACHINE_TELEMETRY_FIELDS = frozenset({
    "success",
    "checked_at",
    "generated_at",
    "startup_seconds",
    "request_count",
    "redirected",
    "final_url",
    "consecutive_failures",
    "last_success_at",
    "last_failure_at",
    "stream_state",
    "actionable_failure",
    "tls_certificate_warning",
    "tls_certificate_detail",
})
MACHINE_TELEMETRY_PREFIXES = (
    "probe_",
    "health_",
    "epg_",
    "http_",
    "automatic_",
)

# Runtime/build context reconstructed by prepare_audit_rows().
GENERATED_CONTEXT_FIELDS = frozenset({
    "source",
    "protocol",
    "language_codes",
    "playlist_language_code",
    "output_language_code",
    "country_code",
    "language_acceptance",
    "in_playlist",
    "in_stable_playlist",
    "feed_index",
    "feed_count",
    "feed_label",
})

MANUAL_FIELD_ORDER = (
    "channel",
    "stream_url",
    "tvg_id",
    "playlist_country_code",
    "output_country_code",
    "expected_language_codes",
    "observed_language_codes",
    "language_match",
    "vlc",
    "samsung",
    "vlc_note",
    "samsung_note",
    "decision",
    "exclude_from_playlist",
    "tested_on",
    "reason",
    "notes",
    "provenance",
    "discovery",
    "source_flags",
    # Retained only for a legacy row whose language text cannot yet be
    # normalized into observed_language_codes.
    "language",
    "language_code",
)

_UNKNOWN_LANGUAGE_TEXT = {
    "",
    "unknown",
    "untested",
    "not tested",
    "not_tested",
    "pending",
}


def machine_telemetry_fields(item: dict) -> list[str]:
    """Return fields that belong in generated telemetry, not audit.json."""
    found: list[str] = []
    for raw_key in item:
        key = str(raw_key or "").strip()
        token = key.casefold()
        if (
            token in MACHINE_TELEMETRY_FIELDS
            or token.startswith(MACHINE_TELEMETRY_PREFIXES)
            or token.endswith("_latency_ms")
            or token.endswith("_latency_seconds")
        ):
            found.append(key)
    return sorted(found)


def compact_manual_audit_item(item: dict) -> dict:
    """Remove generated/default duplication while preserving manual facts."""
    out = dict(item)

    telemetry = machine_telemetry_fields(out)
    if telemetry:
        raise ValueError(
            "Machine telemetry does not belong in audit.json: "
            + ", ".join(telemetry)
        )

    # Migrate old country aliases before dropping generated compatibility aliases.
    if not out.get("playlist_country_code"):
        legacy_scope = normalize_country_code(
            str(out.get("playlist_language_code") or out.get("country_code") or "")
        )
        if legacy_scope:
            out["playlist_country_code"] = legacy_scope

    if not out.get("output_country_code"):
        legacy_output = normalize_country_code(
            str(out.get("output_language_code") or "")
        )
        if legacy_output:
            out["output_country_code"] = legacy_output

    for field in GENERATED_CONTEXT_FIELDS:
        out.pop(field, None)

    for field in ("playlist_country_code", "output_country_code"):
        if field in out:
            code = normalize_country_code(str(out.get(field) or ""))
            if code:
                out[field] = code
            else:
                out.pop(field, None)

    for field in ("expected_language_codes", "observed_language_codes"):
        codes = normalize_language_codes(out.get(field))
        if codes:
            out[field] = codes
        else:
            out.pop(field, None)

    # Convert legacy human language text to the modern explicit human fact.
    observed = list(out.get("observed_language_codes") or [])
    legacy_language = str(out.get("language") or "").strip()
    legacy_token = " ".join(
        legacy_language.casefold().replace("_", " ").split()
    )
    if not observed and legacy_token not in _UNKNOWN_LANGUAGE_TEXT:
        observed = normalize_language_codes([legacy_language])
        if not observed:
            observed = normalize_language_codes([
                str(out.get("language_code") or "")
            ])
        if observed:
            out["observed_language_codes"] = observed

    if observed or legacy_token in _UNKNOWN_LANGUAGE_TEXT:
        out.pop("language", None)
        out.pop("language_code", None)

    # Missing values are the compact representation of automatic decisions.
    decision = str(out.get("decision") or "auto").strip()
    if decision.casefold().replace(" ", "_") == "auto":
        out.pop("decision", None)

    # Keep an explicitly recorded exclusion boolean, including False. Manual
    # playback audits use this to distinguish an intentionally retained feed
    # from a row that has never had an exclusion decision recorded.

    for field in ("vlc", "samsung"):
        status = normalize_test_status(str(out.get(field) or ""))
        if status == "not_tested":
            out.pop(field, None)
        else:
            out[field] = status

    for field in (
        "stream_url",
        "tvg_id",
        "vlc_note",
        "samsung_note",
        "reason",
        "tested_on",
        "notes",
        "provenance",
        "discovery",
    ):
        if field in out and not str(out.get(field) or "").strip():
            out.pop(field, None)

    if not out.get("source_flags"):
        out.pop("source_flags", None)

    compact: dict = {}
    for field in MANUAL_FIELD_ORDER:
        if field in out:
            compact[field] = out[field]
    # Preserve unknown future manual fields rather than silently deleting them.
    for field, value in out.items():
        if field not in compact:
            compact[field] = value
    return compact


def compact_manual_audit_payload(payload) -> dict:
    """Return schema-v2 manual-only payload from list or legacy object form."""
    if isinstance(payload, dict):
        items = payload.get("channels")
        extras = {
            key: value
            for key, value in payload.items()
            if key not in {"schema_version", "storage", "channels"}
        }
    else:
        items = payload
        extras = {}

    if not isinstance(items, list):
        raise RuntimeError("audit.json must contain a channels list.")

    channels = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"audit item #{index} must be a JSON object.")
        channels.append(compact_manual_audit_item(item))

    return {
        "schema_version": MANUAL_AUDIT_SCHEMA_VERSION,
        "storage": MANUAL_AUDIT_STORAGE_KIND,
        **extras,
        "channels": channels,
    }
