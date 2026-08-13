#!/usr/bin/env python3
"""Manual playback audit validation, decisions and history preparation.

This module owns the policy that turns saved VLC/Samsung tests into audit
states and attaches that history to current stream identities. Filesystem
loading remains in build_core so this subsystem stays independent of build
root/path state.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from country_language import (
    configured_country_codes,
    normalize_country_code,
    normalize_language_codes as normalize_spoken_language_codes,
)
from iptv.channel_identity import (
    canonical_stream_url,
    logical_channel_key,
    normalize_text,
    normalized_tvg_id,
    strip_display_annotations,
)
from iptv.language_routing import (
    audit_playlist_country_code,
    audit_playlist_scope_code,
    derive_language_match,
    format_language_codes,
    language_acceptance_state,
    language_mismatch_reason,
    normalize_language_codes,
    normalize_language_match,
    resolve_language_info,
    verified_output_country_code,
    verified_output_language_code,
)
from iptv.playback_status import normalize_test_status
from iptv.source_loader import SOURCE_FLAG_RE

def calculate_audit_decision(
    item: dict,
    supported_language_codes=None,
) -> tuple[str, str]:
    """
    Playback/device status for our playlist, not a legal certification.

    Audit/source identity, spoken-language acceptance, and publication
    country are intentionally separate. A technically working stream can be
    Verified when its observed spoken language is supported. Publication
    country changes only through an explicit output country or configured
    country-routing rule.

    Unsupported observed languages still reject the stream.
    """
    explicit = (
        item.get("decision") or "auto"
    ).strip().casefold().replace(" ", "_")

    if explicit in {
        "verified",
        "tv_verified",
        "pc_only",
        "needs_review",
        "rejected",
    }:
        label = {
            "verified": "Verified",
            "tv_verified": "TV verified",
            "pc_only": "PC only",
            "needs_review": "Needs review",
            "rejected": "Rejected",
        }[explicit]

        return (
            label,
            str(item.get("reason") or "").strip(),
        )

    if audit_excluded(item):
        return (
            "Rejected",
            str(
                item.get("reason")
                or "Excluded from this playlist."
            ).strip(),
        )

    vlc = normalize_test_status(
        str(item.get("vlc", ""))
    )

    samsung = normalize_test_status(
        str(item.get("samsung", ""))
    )

    (
        expected_codes,
        observed_codes,
        language_match,
    ) = resolve_language_info(item)

    acceptance = language_acceptance_state(
        item,
        supported_language_codes,
    )

    if acceptance == "unsupported":
        return (
            "Rejected",
            language_mismatch_reason(
                expected_codes,
                observed_codes,
            ),
        )

    cross_language_supported = (
        acceptance
        == "supported_cross_language"
    )

    # Old manual tests used wrong_language to mean "the stream played, but
    # the speech was not the old expected language". Once that observed
    # language is supported, the same result is technically a successful
    # playback test.
    pc_good = (
        vlc in {
            "works",
            "works_with_warning",
        }
        or (
            cross_language_supported
            and vlc == "wrong_language"
        )
    )

    tv_good = (
        samsung == "works"
        or (
            cross_language_supported
            and samsung == "wrong_language"
        )
    )

    if pc_good and tv_good:
        if cross_language_supported:
            return (
                "Verified",
                (
                    "Works on both tested devices. "
                    f"Observed language(s) "
                    f"{format_language_codes(observed_codes)} "
                    "are currently supported. Publication country "
                    "is determined separately by explicit country-routing "
                    "policy."
                ),
            )

        return "Verified", ""

    if tv_good and not pc_good:
        return (
            "TV verified",
            "Works on Samsung; VLC needs another look.",
        )

    if (
        pc_good
        and samsung in {
            "format_error",
            "generic_error",
            "loads",
        }
    ):
        return (
            "PC only",
            "Works in VLC but not on Samsung in the current test.",
        )

    return (
        "Needs review",
        str(item.get("reason") or "").strip(),
    )

def infer_protocol(url: str) -> str:
    value = (url or "").strip().lower()
    if value.startswith("rtmp://"):
        return "RTMP"
    if ".m3u8" in value:
        return "HLS"
    if value.startswith("https://"):
        return "HTTPS"
    if value.startswith("http://"):
        return "HTTP"
    return ""

def canonical_audit_name(value: str) -> str:
    return normalize_text(strip_display_annotations(value or ""))

def normalize_audit_decision_token(value: str) -> str:
    token = (value or "auto").strip().casefold().replace("-", "_").replace(" ", "_")
    return token or "auto"

def audit_status_is_recognized(value: str) -> bool:
    raw = (value or "").strip()
    if not raw:
        return True

    token = raw.casefold().replace(" ", "_")
    normalized = normalize_test_status(raw)

    if normalized != "needs_review":
        return True

    return token == "needs_review"

def audit_excluded(item: dict) -> bool:
    """Return True only for the literal JSON boolean true."""
    return item.get("exclude_from_playlist") is True

def exact_url_audit_matches_entry(
    audit_item: dict,
    entry: dict,
) -> bool:
    """Guard exact-URL audit history by source country, not spoken language."""
    audit_scope = audit_playlist_country_code(audit_item)
    if not audit_scope:
        return True
    entry_scope = normalize_country_code(
        str(entry.get("country_code") or entry.get("language_code") or "")
    )
    if not entry_scope:
        return True
    return audit_scope == entry_scope

def validate_audit_items(
    audit_items: list[dict],
    final_entries: list[dict],
    strict: bool = False,
) -> tuple[list[str], list[str]]:
    """
    Validate audit.json before it can affect playlist selection.

    Returns:
      1. all non-fatal audit warnings
      2. warnings specifically caused by ambiguous legacy channel-level audits

    In normal mode, a legacy channel-level audit that now matches multiple
    current feeds is treated as non-fatal. Its old result must not be applied
    to any of those feeds.

    In strict mode, the same ambiguity is a fatal validation error.

    All genuinely malformed or contradictory audit data remains fatal in
    both modes.
    """
    errors: list[str] = []
    warnings: list[str] = []
    ambiguity_warnings: list[str] = []
	
    allowed_decisions = {
        "auto",
        "verified",
        "tv_verified",
        "pc_only",
        "needs_review",
        "rejected",
    }

    current_by_tvg: dict[str, set[str]] = {}
    current_by_name: dict[str, set[str]] = {}

    current_expected_by_url: dict[str, set[str]] = {}
    current_expected_by_tvg: dict[str, set[str]] = {}
    current_expected_by_name: dict[str, set[str]] = {}
    current_country_by_url: dict[str, set[str]] = {}

    for entry in final_entries:
        url = str(
            entry.get("url") or ""
        ).strip()

        if not url:
            continue

        url_key = canonical_stream_url(url)

        expected_codes = normalize_language_codes(
            entry.get("expected_language_codes")
            or entry.get("language_codes")
            or entry.get("language_code")
        )
        entry_country = normalize_country_code(
            str(entry.get("country_code") or entry.get("language_code") or "")
        )
        if entry_country:
            current_country_by_url.setdefault(url_key, set()).add(entry_country)

        if expected_codes:
            current_expected_by_url.setdefault(
                url_key,
                set(),
            ).update(expected_codes)

        tid = normalized_tvg_id(
            str(entry.get("tvg_id") or "")
        )

        if tid:
            current_by_tvg.setdefault(
                tid,
                set(),
            ).add(url_key)

            if expected_codes:
                current_expected_by_tvg.setdefault(
                    tid,
                    set(),
                ).update(expected_codes)

        for value in (
            entry.get("channel_name"),
            entry.get("display_name"),
            entry.get("tvg_name"),
        ):
            cname = canonical_audit_name(
                str(value or "")
            )

            if not cname:
                continue

            current_by_name.setdefault(
                cname,
                set(),
            ).add(url_key)

            if expected_codes:
                current_expected_by_name.setdefault(
                    cname,
                    set(),
                ).update(expected_codes)

    seen_urls: dict[str, int] = {}
    seen_legacy_keys: dict[tuple[str, str], int] = {}

    for index, raw in enumerate(audit_items, start=1):
        item = dict(raw)
        channel = str(item.get("channel") or item.get("channel_name") or "").strip()
        label = f"audit item #{index}"
        if channel:
            label += f" ({channel})"

        if not channel:
            errors.append(f"{label}: missing channel name.")

        url = str(
            item.get("stream_url") or ""
        ).strip()

        url_key = (
            canonical_stream_url(url)
            if url
            else ""
        )

        tid = normalized_tvg_id(
            str(item.get("tvg_id") or "")
        )

        cname = canonical_audit_name(
            channel
        )

        if url:

            if any(ch.isspace() for ch in url):
                errors.append(
                    f"{label}: malformed stream_url contains whitespace: {url!r}."
                )
            else:
                parsed = urlparse(url)
                if not parsed.scheme or not parsed.netloc:
                    errors.append(f"{label}: malformed stream_url: {url!r}.")

            if url_key in seen_urls:
                first = seen_urls[url_key]
                errors.append(
                    f"{label}: duplicate stream_url {url!r}; "
                    f"already used by audit item #{first}."
                )
            else:
                seen_urls[url_key] = index

        for field in (
            "expected_language_codes",
            "observed_language_codes",
        ):
            if field not in item:
                continue

            raw_codes = item.get(field)

            if raw_codes is None:
                continue

            if not isinstance(raw_codes, list):
                errors.append(
                    f"{label}: {field} must be a JSON list "
                    f"such as [\"HU\"] or [\"HU\", \"SR\"]."
                )
                continue

            for raw_code in raw_codes:
                if (
                    not isinstance(raw_code, str)
                    or not re.fullmatch(
                        r"[A-Za-z]{2,3}",
                        raw_code.strip(),
                    )
                ):
                    errors.append(
                        f"{label}: invalid language code "
                        f"{raw_code!r} in {field}. "
                        "Use 2-3 letter codes such as "
                        "HU, SK, CZ, SR or EN."
                    )

        raw_language_match = str(
            item.get("language_match") or ""
        ).strip()

        if (
            raw_language_match
            and not normalize_language_match(
                raw_language_match
            )
        ):
            errors.append(
                f"{label}: invalid language_match "
                f"{raw_language_match!r}. "
                "Allowed values: yes, no, unknown, "
                "multilingual."
            )
			
        for field in ("vlc", "samsung"):
            raw_status = str(item.get(field) or "")
            if not audit_status_is_recognized(raw_status):
                errors.append(
                    f"{label}: invalid {field} status {raw_status!r}. "
                    "Use a supported canonical status or recognized legacy value."
                )

        decision_token = normalize_audit_decision_token(str(item.get("decision") or "auto"))
        if decision_token not in allowed_decisions:
            errors.append(
                f"{label}: invalid decision {item.get('decision')!r}. "
                f"Allowed values: {', '.join(sorted(allowed_decisions))}."
            )

        if (
            "exclude_from_playlist" in item
            and not isinstance(
                item.get("exclude_from_playlist"),
                bool,
            )
        ):
            errors.append(
                f"{label}: exclude_from_playlist must be true or false."
            )

        exclude = audit_excluded(item)
        if exclude and decision_token in {"verified", "tv_verified", "pc_only"}:
            errors.append(
                f"{label}: exclude_from_playlist=true conflicts with "
                f"decision {item.get('decision')!r}."
            )

        vlc = normalize_test_status(
            str(item.get("vlc") or "")
        )

        samsung = normalize_test_status(
            str(item.get("samsung") or "")
        )

        expected_for_validation = (
            normalize_language_codes(
                item.get("expected_language_codes")
            )
        )

        current_url_countries = (
            sorted(current_country_by_url.get(url_key, set()))
            if url_key else []
        )

        saved_playlist_scope = (
            audit_playlist_scope_code(
                item
            )
        )

        if (
            url_key
            and saved_playlist_scope
            and current_url_countries
            and saved_playlist_scope
            not in current_url_countries
        ):
            warnings.append(
                f"{label}: exact stream URL is currently scoped to "
                f"{', '.join(current_url_countries)}, but the saved audit "
                f"belongs to {saved_playlist_scope} playlist scope. "
                "The saved result will be kept as historical evidence and "
                "will not be applied to this current entry."
            )

        # If the audit does not explicitly say what language was expected,
        # derive it from the current source/playlist entry.
        if not expected_for_validation:
            if url_key:
                expected_for_validation = sorted(
                    current_expected_by_url.get(
                        url_key,
                        set(),
                    )
                )
            elif tid:
                expected_for_validation = sorted(
                    current_expected_by_tvg.get(
                        tid,
                        set(),
                    )
                )
            elif cname:
                expected_for_validation = sorted(
                    current_expected_by_name.get(
                        cname,
                        set(),
                    )
                )

        language_probe = dict(item)

        language_probe[
            "expected_language_codes"
        ] = expected_for_validation

        (
            resolved_expected,
            resolved_observed,
            resolved_match,
        ) = resolve_language_info(
            language_probe
        )

        # If both language lists are present, an explicitly supplied
        # language_match must agree with them.
        if (
            raw_language_match
            and resolved_expected
            and resolved_observed
        ):
            explicit_match = normalize_language_match(
                raw_language_match
            )

            derived_match = derive_language_match(
                resolved_expected,
                resolved_observed,
            )

            if (
                explicit_match
                and explicit_match != derived_match
            ):
                errors.append(
                    f"{label}: language_match "
                    f"{raw_language_match!r} contradicts "
                    "expected/observed language codes "
                    f"(expected={resolved_expected}, "
                    f"observed={resolved_observed}, "
                    f"derived={derived_match})."
                )

        auto_item = dict(language_probe)
        auto_item["decision"] = "auto"
        auto_item["exclude_from_playlist"] = False

        automatic_decision, _ = (
            calculate_audit_decision(
                auto_item
            )
        )

        if decision_token == "verified" and automatic_decision != "Verified":
            errors.append(
                f"{label}: decision Verified contradicts playback/language results "
                f"(VLC={vlc}, Samsung={samsung}, auto={automatic_decision})."
            )

        if decision_token == "tv_verified" and samsung != "works":
            errors.append(
                f"{label}: decision TV verified requires Samsung=works; "
                f"got {samsung}."
            )

        if decision_token == "pc_only" and automatic_decision != "PC only":
            errors.append(
                f"{label}: decision PC only contradicts playback results "
                f"(VLC={vlc}, Samsung={samsung}, auto={automatic_decision})."
            )

        if not url:
            if tid:
                legacy_key = ("tvg", tid)
                matching_urls = current_by_tvg.get(tid, set())
            else:
                legacy_key = ("name", cname)
                matching_urls = current_by_name.get(cname, set())

            if legacy_key[1]:
                if legacy_key in seen_legacy_keys:
                    first = seen_legacy_keys[legacy_key]
                    errors.append(
                        f"{label}: duplicate channel-level audit key "
                        f"{legacy_key[0]}={legacy_key[1]!r}; "
                        f"already used by audit item #{first}."
                    )
                else:
                    seen_legacy_keys[legacy_key] = index

            if len(matching_urls) > 1:
                candidates = ", ".join(sorted(matching_urls))
                message = (
                    f"{label}: Legacy verification for "
                    f"{channel or 'this channel'} became ambiguous after "
                    f"{len(matching_urls)} feeds were discovered. "
                    f"The saved channel-level result was not applied to any "
                    f"current feed. Re-test individual streams. "
                    f"Candidate URLs: {candidates}"
                )

                if strict:
                    errors.append(message)
                else:
                    warnings.append(message)
                    ambiguity_warnings.append(message)
            elif len(matching_urls) == 1:
                only_url = next(iter(matching_urls))
                warnings.append(
                    f"{label}: legacy channel-level audit still matches one current "
                    f"feed ({only_url}). Add stream_url when this row is next edited."
                )

    if errors:
        details = "\n".join(f"  - {message}" for message in errors)
        raise RuntimeError(f"audit.json validation failed:\n{details}")

    return warnings, ambiguity_warnings

def audit_match_key(item: dict) -> tuple[str, str]:
    url = str(item.get("stream_url") or item.get("url") or "").strip()
    if url:
        return ("url", canonical_stream_url(url))

    tvg_id = normalized_tvg_id(str(item.get("tvg_id") or ""))
    if tvg_id:
        return ("tvg_id", tvg_id)

    name = normalize_text(str(item.get("channel") or item.get("channel_name") or ""))
    return ("name", name)

def prepare_audit_rows(
    audit_items: list[dict],
    final_entries: list[dict],
    supported_language_codes=None,
    cfg: dict | None = None,
) -> list[dict]:
    """
    Create one audit row PER STREAM URL.

    Important behavior:
    - If a channel has multiple stream URLs, each one gets Feed 1/2,
      Feed 2/2, etc.
    - A saved audit result with an exact stream_url applies only to that stream.
    - Older channel-level audit results without stream_url apply only when the
      current channel has exactly one feed.
    - If a legacy channel-level audit now matches multiple feeds, its saved
      result is not applied to any current feed.
    - Ambiguous legacy results are preserved as historical audit rows.
    """
    # Assign stable feed numbers in current source order.
    counts: dict[str, int] = {}
    for entry in final_entries:
        key = logical_channel_key(entry)
        counts[key] = counts.get(key, 0) + 1

    seen_feed: dict[str, int] = {}
    for entry in final_entries:
        key = logical_channel_key(entry)
        seen_feed[key] = seen_feed.get(key, 0) + 1
        entry["variant_index"] = seen_feed[key]
        entry["variant_count"] = counts[key]

    manual_by_url: dict[str, dict] = {}
    manual_by_tvg_id: dict[str, dict] = {}
    manual_by_name: dict[str, dict] = {}

    for raw in audit_items:
        item = dict(raw)
        url = str(item.get("stream_url") or "").strip()
        tvg_id = normalized_tvg_id(str(item.get("tvg_id") or ""))
        name = canonical_audit_name(str(item.get("channel") or ""))

        if url:
            manual_by_url[canonical_stream_url(url)] = item
        if tvg_id and not url:
            manual_by_tvg_id[tvg_id] = item
        if name and not url:
            manual_by_name[name] = item

    used_manual_keys: set[tuple[str, str]] = set()
    rows: list[dict] = []

    for entry in final_entries:
        url = str(entry.get("url") or "").strip()
        url_key = canonical_stream_url(url)
        tvg_id = str(entry.get("tvg_id") or "").strip()
        clean_name = str(
            entry.get("channel_name")
            or entry.get("display_name")
            or "Unnamed channel"
        ).strip()
        feed_index = int(entry.get("variant_index") or 1)
        feed_count = int(entry.get("variant_count") or 1)

        manual = None
        manual_key = None

        # URL-specific audit is authoritative only when any explicitly
        # recorded expected language/country is compatible with this current
        # entry. Canonically equivalent URL spellings still identify the same
        # stream inside that identity scope.
        if url_key and url_key in manual_by_url:
            candidate_manual = manual_by_url[url_key]

            if exact_url_audit_matches_entry(
                candidate_manual,
                entry,
            ):
                manual = candidate_manual
                manual_key = ("url", url_key)

        # Legacy channel-level results are safe only for a single-feed channel.
        elif feed_count == 1:
            tid = normalized_tvg_id(tvg_id)
            cname = canonical_audit_name(clean_name)

            if tid and tid in manual_by_tvg_id:
                manual = manual_by_tvg_id[tid]
                manual_key = ("tvg", tid)
            elif cname and cname in manual_by_name:
                manual = manual_by_name[cname]
                manual_key = ("name", cname)

        item = {
            "channel": clean_name,
            "tvg_id": tvg_id,
            "source": str(entry.get("source") or ""),
            "discovery": str(entry.get("source") or "Current playlist"),
            "stream_url": url,
            "protocol": infer_protocol(url),

            # Legacy fields retained for backwards compatibility.
            "language": "Unknown",
            "language_code": str(
                entry.get("language_code") or "HU"
            ),

            # New country-independent language model.
            "expected_language_codes": (
                normalize_language_codes(
                    entry.get("language_codes")
                    or entry.get("language_code")
                    or "HU"
                )
            ),
            "country_code": (
                normalize_country_code(
                    str(entry.get("country_code") or entry.get("language_code") or "HU")
                )
                or "HU"
            ),
            "language_codes": normalize_language_codes(
                entry.get("language_codes") or entry.get("language_code") or "HU"
            ),
            "observed_language_codes": [],
            "playlist_country_code": (
                normalize_country_code(
                    str(entry.get("country_code") or entry.get("language_code") or "HU")
                )
                or "HU"
            ),
            # Legacy alias: this field historically stored country scope.
            "playlist_language_code": (
                normalize_country_code(
                    str(entry.get("country_code") or entry.get("language_code") or "HU")
                )
                or "HU"
            ),

            "provenance": (
                "Our curated/test extra"
                if entry.get("source_kind") == "extras"
                else "IPTV-org source (manual playback review)"
            ),
            "source_flags": list(entry.get("source_flags") or []),
            "vlc": "not_tested",
            "samsung": "not_tested",
            "vlc_note": "",
            "samsung_note": "",
            "decision": "auto",
            "reason": "",
            "notes": (
                "Auto-added from current tv.m3u for manual testing."
                if feed_count == 1
                else f"Alternative stream Feed {feed_index}/{feed_count}; test this URL separately."
            ),
            "exclude_from_playlist": False,
            "tested_on": "",
        }

        if manual is not None:
            if manual_key:
                used_manual_keys.add(manual_key)
            for key, value in manual.items():
                if value not in ("", None):
                    item[key] = value

        flags: list[str] = []

        for flag in (
            list(entry.get("source_flags") or [])
            + list(item.get("source_flags") or [])
        ):
            if flag and flag not in flags:
                flags.append(flag)

        item["source_flags"] = flags

        (
            expected_codes,
            observed_codes,
            language_match,
        ) = resolve_language_info(
            item,
            default_expected=(
                entry.get("language_codes")
                or entry.get("language_code")
                or "HU"
            ),
        )

        item[
            "expected_language_codes"
        ] = expected_codes

        item[
            "observed_language_codes"
        ] = observed_codes

        item[
            "language_match"
        ] = language_match

        playlist_country_code = (
            normalize_country_code(
                str(
                    item.get("playlist_country_code")
                    or item.get("playlist_language_code")
                    or entry.get("country_code")
                    or entry.get("language_code")
                    or "HU"
                )
            )
            or "HU"
        )
        item["playlist_country_code"] = playlist_country_code
        item["playlist_language_code"] = playlist_country_code

        language_acceptance = (
            language_acceptance_state(
                item,
                supported_language_codes,
            )
        )

        item[
            "language_acceptance"
        ] = language_acceptance

        decision, auto_reason = (
            calculate_audit_decision(
                item,
                supported_language_codes,
            )
        )

        route_probe = {
            **item,
            "decision": decision,
            "observed_language_codes": observed_codes,
        }
        if cfg is not None:
            output_country_code = verified_output_country_code(
                route_probe,
                str(entry.get("country_code") or entry.get("language_code") or ""),
                cfg,
            )
        else:
            output_country_code = verified_output_language_code(
                route_probe,
                str(entry.get("country_code") or entry.get("language_code") or ""),
                configured_country_codes({"country_outputs": {code: "" for code in ("HU", "SK", "CZ")}}),
            )
        output_language_code = output_country_code

        rows.append({
            "channel": str(item.get("channel") or clean_name).strip(),
            "tvg_id": str(item.get("tvg_id") or tvg_id).strip(),
            "source": str(item.get("source") or entry.get("source") or "").strip(),
            "discovery": str(item.get("discovery") or entry.get("source") or "").strip(),
            "stream_url": str(item.get("stream_url") or url).strip(),
            "protocol": str(item.get("protocol") or infer_protocol(url)).strip(),
            # Legacy fields.
            "language": str(
                item.get("language") or "Unknown"
            ).strip(),
            "language_code": str(
                item.get("language_code")
                or entry.get("language_code")
                or "HU"
            ).strip().upper(),

            # Country scope and publication destination.
            "playlist_country_code": str(
                item.get("playlist_country_code")
                or item.get("playlist_language_code")
                or entry.get("country_code")
                or entry.get("language_code")
                or ""
            ).strip().upper(),
            "output_country_code": output_country_code,
            # Legacy aliases retained for old exports/tools.
            "playlist_language_code": str(
                item.get(
                    "playlist_language_code"
                )
                or entry.get(
                    "language_code"
                )
                or ""
            ).strip().upper(),
            "output_language_code": output_language_code,
            "language_codes": normalize_spoken_language_codes(
                entry.get("language_codes") or expected_codes
            ),
            "expected_language_codes": expected_codes,
            "observed_language_codes": observed_codes,
            "language_match": language_match,
            "language_acceptance": (
                language_acceptance
            ),

            "provenance": str(
                item.get("provenance") or ""
            ).strip(),
            "source_flags": flags,
            "vlc": normalize_test_status(str(item.get("vlc") or "")),
            "samsung": normalize_test_status(str(item.get("samsung") or "")),
            "vlc_note": str(item.get("vlc_note") or "").strip(),
            "samsung_note": str(item.get("samsung_note") or "").strip(),
            "decision": decision,
            "reason": str(item.get("reason") or auto_reason or "").strip(),
            "notes": str(item.get("notes") or "").strip(),
            "exclude_from_playlist": audit_excluded(item),
            "tested_on": str(item.get("tested_on") or "").strip(),
            "in_playlist": True,
            "feed_index": feed_index,
            "feed_count": feed_count,
            "feed_label": (
                f"Feed {feed_index}/{feed_count}"
                if feed_count > 1 else "Single"
            ),
        })

    current_urls: set[str] = set()
    current_by_tvg: dict[str, set[str]] = {}
    current_by_name: dict[str, set[str]] = {}
    current_expected_by_url: dict[str, set[str]] = {}
    current_country_by_url: dict[str, set[str]] = {}

    for entry in final_entries:
        current_url = str(
            entry.get("url") or ""
        ).strip()

        if not current_url:
            continue

        current_url_key = canonical_stream_url(
            current_url
        )

        current_urls.add(current_url_key)

        expected_codes = normalize_language_codes(
            entry.get("language_codes")
            or entry.get("language_code")
            or "HU"
        )
        current_country = normalize_country_code(
            str(entry.get("country_code") or entry.get("language_code") or "")
        )
        if current_country:
            current_country_by_url.setdefault(current_url_key, set()).add(current_country)

        if expected_codes:
            current_expected_by_url.setdefault(
                current_url_key,
                set(),
            ).update(expected_codes)

        current_tvg = normalized_tvg_id(
            str(entry.get("tvg_id") or "")
        )

        if current_tvg:
            current_by_tvg.setdefault(
                current_tvg,
                set(),
            ).add(current_url_key)

        for value in (
            entry.get("channel_name"),
            entry.get("display_name"),
            entry.get("tvg_name"),
        ):
            current_name = canonical_audit_name(
                str(value or "")
            )

            if current_name:
                current_by_name.setdefault(
                    current_name,
                    set(),
                ).add(current_url_key)

    # Keep manually tracked candidates/rejections that are not currently in tv.m3u.
    for raw in audit_items:
        item = dict(raw)
        url = str(item.get("stream_url") or "").strip()
        url_key = canonical_stream_url(url)
        tid = normalized_tvg_id(str(item.get("tvg_id") or ""))
        cname = canonical_audit_name(str(item.get("channel") or ""))

        if url:
            manual_key = ("url", url_key)
        elif tid:
            manual_key = ("tvg", tid)
        else:
            manual_key = ("name", cname)

        if manual_key in used_manual_keys:
            continue

        # An exact URL can still need to remain as historical evidence when
        # its saved expected language/country conflicts with the current entry.
        # Do not discard it merely because that URL exists in current inputs.
        legacy_ambiguous = False
        legacy_matching_urls: set[str] = set()

        if not url:
            if tid:
                legacy_matching_urls = current_by_tvg.get(
                    tid,
                    set(),
                )
            elif cname:
                legacy_matching_urls = current_by_name.get(
                    cname,
                    set(),
                )

            # With one current feed, the legacy audit was already safely
            # attached to that stream above.
            if len(legacy_matching_urls) == 1:
                continue

            # With multiple feeds, keep the old audit only as historical
            # evidence. Never apply it to a current stream.
            legacy_ambiguous = len(legacy_matching_urls) > 1

        legacy_expected_codes: list[str] = []

        for matching_url in legacy_matching_urls:
            for code in current_expected_by_url.get(
                matching_url,
                set(),
            ):
                if code not in legacy_expected_codes:
                    legacy_expected_codes.append(code)

        (
            expected_codes,
            observed_codes,
            language_match,
        ) = resolve_language_info(
            item,
            default_expected=legacy_expected_codes,
        )

        item[
            "expected_language_codes"
        ] = expected_codes

        item[
            "observed_language_codes"
        ] = observed_codes

        item[
            "language_match"
        ] = language_match

        historical_scope = (
            audit_playlist_scope_code(
                item
            )
        )

        if historical_scope:
            item[
                "playlist_language_code"
            ] = historical_scope

        language_acceptance = (
            language_acceptance_state(
                item,
                supported_language_codes,
            )
        )

        item[
            "language_acceptance"
        ] = language_acceptance

        decision, auto_reason = (
            calculate_audit_decision(
                item,
                supported_language_codes,
            )
        )

        history_notes = str(
            item.get("notes") or ""
        ).strip()

        if url_key and url_key in current_expected_by_url:
            saved_scope = (
                audit_playlist_scope_code(
                    item
                )
            )
            current_countries = sorted(
                current_country_by_url.get(url_key, set())
            )

            if (
                saved_scope
                and current_countries
                and saved_scope
                not in current_countries
            ):
                identity_note = (
                    "Historical exact-URL audit only. Saved playlist "
                    f"scope {saved_scope} does not match the current "
                    "entry scope "
                    f"{', '.join(current_countries)}, so this "
                    "verification was not transferred."
                )

                history_notes = " — ".join(
                    part
                    for part in (
                        history_notes,
                        identity_note,
                    )
                    if part
                )

        if legacy_ambiguous:
            ambiguity_note = (
                f"Historical channel-level audit only. "
                f"{len(legacy_matching_urls)} current feeds now match this "
                f"channel, so this saved result was not applied to any of "
                f"them. Re-test the individual stream URLs."
            )

            history_notes = " — ".join(
                part
                for part in (
                    history_notes,
                    ambiguity_note,
                )
                if part
            )
			
        rows.append({
            "channel": str(item.get("channel") or "Unnamed channel").strip(),
            "tvg_id": str(item.get("tvg_id") or "").strip(),
            "source": str(item.get("source") or "").strip(),
            "discovery": str(item.get("discovery") or "").strip(),
            "stream_url": url,
            "protocol": str(item.get("protocol") or infer_protocol(url)).strip(),
            # Legacy fields.
            "language": str(
                item.get("language") or "Unknown"
            ).strip(),
            "language_code": str(
                item.get("language_code") or ""
            ).strip().upper(),

            # Modern country model plus legacy alias.
            "playlist_country_code": str(
                item.get("playlist_country_code")
                or item.get("playlist_language_code")
                or ""
            ).strip().upper(),
            "output_country_code": str(
                item.get("output_country_code")
                or item.get("output_language_code")
                or ""
            ).strip().upper(),
            "playlist_language_code": str(
                item.get("playlist_country_code")
                or item.get("playlist_language_code")
                or ""
            ).strip().upper(),
            "expected_language_codes": expected_codes,
            "observed_language_codes": observed_codes,
            "language_match": language_match,
            "language_acceptance": (
                language_acceptance
            ),

            "provenance": str(
                item.get("provenance") or "Unknown"
            ).strip(),
            "source_flags": list(item.get("source_flags") or []),
            "vlc": normalize_test_status(str(item.get("vlc") or "")),
            "samsung": normalize_test_status(str(item.get("samsung") or "")),
            "vlc_note": str(item.get("vlc_note") or "").strip(),
            "samsung_note": str(item.get("samsung_note") or "").strip(),
            "decision": decision,
            "reason": str(item.get("reason") or auto_reason or "").strip(),
            "notes": history_notes,
            "exclude_from_playlist": audit_excluded(item),
            "tested_on": str(item.get("tested_on") or "").strip(),
            "in_playlist": False,
            "feed_index": 1,
            "feed_count": (
                len(legacy_matching_urls)
                if legacy_ambiguous
                else 1
            ),
            "feed_label": (
                "Legacy audit"
                if legacy_ambiguous
                else "Candidate"
            ),
        })

    priority = {
        "Needs review": 0,
        "TV verified": 1,
        "PC only": 2,
        "Verified": 3,
        "Rejected": 4,
    }

    return sorted(
        rows,
        key=lambda x: (
            priority.get(x["decision"], 9),
            0 if x["in_playlist"] else 1,
            normalize_text(x["channel"]),
            int(x.get("feed_index") or 1),
        ),
    )

def audit_rows_by_stream_url(
    audit_rows: list[dict],
) -> dict[str, dict]:
    """
    Build an exact/canonical stream-URL lookup for prepared audit rows.
    """
    result: dict[str, dict] = {}

    for row in audit_rows:
        # Historical rows may intentionally retain the same URL as a current
        # entry after an identity-scope conflict. They must never drive current
        # playlist selection.
        if row.get("in_playlist") is False:
            continue

        url = str(
            row.get("stream_url") or ""
        ).strip()

        if not url:
            continue

        key = canonical_stream_url(url)

        if key in result:
            raise RuntimeError(
                f"Duplicate prepared audit URL: {url}"
            )

        result[key] = row

    return result
