#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
import sys
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path
from iptv.deduplication import (
    collect_source_entries,
    extract_source_flags,
)
from iptv.publication import (
    normalize_content_group,
    rewrite_extinf_line,
    rewrite_entry_lines,
    playlist_status_suffix,
    prepare_published_entries,
)
from iptv.stable_selection import stable_block_reason
from iptv.stable_selection import select_stable_playlist_candidates as _select_stable_playlist_candidates
from iptv.feed_selection import (
    select_playlist_candidates,
    make_test_playlist_candidates,
)
from iptv.audit import (
    calculate_audit_decision,
    infer_protocol,
    canonical_audit_name,
    normalize_audit_decision_token,
    audit_status_is_recognized,
    audit_excluded,
    exact_url_audit_matches_entry,
    validate_audit_items,
    audit_match_key,
    prepare_audit_rows,
    audit_rows_by_stream_url,
)
from iptv.language_routing import (
    country_name_for_code,
    country_name_for_language,
    route_candidates_to_verified_countries,
    route_candidates_to_verified_languages,
    build_language_catalog_entries,
    entries_for_spoken_language,
    LANGUAGE_NAME_TO_CODE,
    normalize_language_code,
    normalize_language_codes,
    normalize_language_match,
    legacy_language_is_negative,
    derive_language_match,
    resolve_language_info,
    format_language_codes,
    language_mismatch_reason,
    configured_playlist_country_codes,
    configured_playlist_language_codes,
    configured_spoken_language_codes,
    audit_playlist_country_code,
    audit_playlist_scope_code,
    verified_output_country_code,
    verified_output_language_code,
    language_acceptance_state,
)
from iptv.source_loader import (
    ATTR_RE,
    SOURCE_FLAG_RE,
    VALID_SOURCE_KINDS,
    http_get_text,
    download_m3u,
    split_extinf,
    parse_entries,
    normalize_source_kind,
    source_spec,
)
from iptv.playlist_writer import playlist_header
from iptv.playlist_writer import write_m3u_playlist as _write_m3u_playlist
from iptv.playback_status import (
    normalize_test_status,
    is_tested_status,
)
from iptv.reports import (
    build_report_context,
    write_build_csv_exports,
    write_machine_report,
    print_build_summary,
    summarize_country_stats,
    summarize_language_stats,
    safe_csv_value,
    write_csv,
)
from iptv.channel_identity import logical_channel_key
from iptv.logo_quality import (
    LogoRegistry,
    load_logo_registry,
    apply_channel_logos,
    build_logo_quality,
    write_logo_quality_outputs,
)
from iptv.channel_identity import (
    QUALITY_SUFFIX_RE,
    TVG_VARIANT_SUFFIX_RE,
    CUSTOM_PREFIX_RE,
    INTERNAL_PROVIDER_TEST_SUFFIX_RE,
    split_display_annotations,
    deduplicate_identical_annotations,
    collapse_duplicate_quality_suffixes,
    published_display_from_canonical,
    strip_display_annotations,
    normalize_text,
    strip_internal_candidate_annotations,
    normalized_tvg_id,
    canonical_stream_url,
    apply_canonical_identity,
    channel_key,
    strip_custom_prefix,
)
from dashboard import copy_dashboard_assets, render_dashboard
from feed_quality import build_feed_quality_context, score_feed_quality
from identity_overrides import IdentityRegistry, load_identity_registry
from source_concentration import build_source_concentration
from country_language import (
    configured_country_codes,
    configured_language_codes,
    country_code_from_tvg_id,
    legacy_country_scope_from_language_token,
    normalize_country_code,
    normalize_language_code as normalize_spoken_language_code,
    normalize_language_codes as normalize_spoken_language_codes,
    source_country_code,
    source_country_mode,
    source_language_codes,
    verified_country_route,
)

ROOT = Path(__file__).resolve().parent






	
def read_local(path: str) -> str:
    p = ROOT / path
    if not p.is_file():
        raise RuntimeError(f"Required local source {path} not found")
    return p.read_text(encoding="utf-8-sig")






















	









	












def load_previous_report(url: str | None) -> dict | None:
    if not url:
        return None

    try:
        text = http_get_text(url, timeout=15)
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("channels"), list):
            return data
    except Exception as exc:
        print(f"Previous report unavailable: {exc}")

    return None







def load_audit(path: str | None) -> list[dict]:
    if not path:
        return []

    p = ROOT / path
    if not p.exists():
        print(f"Audit file not found: {path}")
        return []

    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("channels", [])

    if not isinstance(data, list):
        raise RuntimeError("audit.json must contain a list or an object with a 'channels' list.")

    return [dict(item) for item in data if isinstance(item, dict)]




















	
























	

















def select_stable_playlist_candidates(
    final_entries: list[dict],
    audit_rows: list[dict],
    cfg: dict,
):
    """Compatibility wrapper that keeps live build globals injectable."""
    return _select_stable_playlist_candidates(
        final_entries,
        audit_rows,
        cfg,
        make_test_candidates=make_test_playlist_candidates,
        route_candidates=route_candidates_to_verified_countries,
        build_quality_context=build_feed_quality_context,
        score_quality=score_feed_quality,
    )







	


def write_m3u_playlist(
    path: Path,
    cfg: dict,
    entries: list[dict],
    generated: str,
    playlist_label: str,
    name_style: str = "status",
) -> None:
    """Compatibility wrapper around the extracted playlist writer."""
    return _write_m3u_playlist(
        path,
        cfg,
        entries,
        generated,
        playlist_label,
        name_style=name_style,
        strip_custom_prefix=strip_custom_prefix,
        normalize_country_code=normalize_country_code,
        rewrite_entry_lines=rewrite_entry_lines,
    )

def make_dashboard(
    cfg: dict,
    generated: str,
    final_entries: list[dict],
    unique_channels: list[dict],
    source_stats: list[dict],
    language_stats: list[dict],
    duplicate_rows: list[dict],
    changes: dict,
    audit_rows: list[dict],
    audit_ambiguity_warnings: list[str],
    country_stats: list[dict] | None = None,
) -> str:
    """Render the dashboard through the standalone presentation layer."""
    if country_stats is None:
        country_stats = summarize_country_stats(final_entries, source_stats)
    return render_dashboard(
        cfg=cfg,
        generated=generated,
        final_entries=final_entries,
        unique_channels=unique_channels,
        source_stats=source_stats,
        country_stats=country_stats,
        language_stats=language_stats,
        duplicate_rows=duplicate_rows,
        changes=changes,
        audit_rows=audit_rows,
        audit_ambiguity_warnings=audit_ambiguity_warnings,
        is_tested_status=is_tested_status,
        format_language_codes=format_language_codes,
    )




def main(strict: bool = False) -> None:
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    audit_items = load_audit(cfg.get("audit_path", "audit.json"))
    supported_language_codes = configured_spoken_language_codes(cfg)
    supported_country_codes = configured_playlist_country_codes(cfg)

    raw_identity_path = str(
        cfg.get("identity_overrides_path")
        or ""
    ).strip()

    if raw_identity_path:
        identity_path = ROOT / raw_identity_path
        identity_registry = load_identity_registry(identity_path)
    else:
        identity_path = None
        identity_registry = IdentityRegistry({
            "schema_version": 1,
            "identities": {},
            "selectors": [],
        })

    raw_logo_path = str(cfg.get("logo_overrides_path") or "").strip()
    if raw_logo_path:
        logo_registry = load_logo_registry(ROOT / raw_logo_path)
    else:
        logo_registry = LogoRegistry()

    final_entries, language_only_entries, duplicate_rows, source_stats = collect_source_entries(
        cfg,
        identity_registry,
        supported_country_codes,
        remote_loader=download_m3u,
        local_loader=read_local,
    )

    audit_warnings, audit_ambiguity_warnings = validate_audit_items(
        audit_items,
        final_entries,
        strict=strict,
    )

    for warning in audit_warnings:
        print(
            f"WARNING: {warning}",
            file=sys.stderr,
        )

    audit_rows = prepare_audit_rows(
        audit_items,
        final_entries,
        supported_language_codes=(
            supported_language_codes
        ),
        cfg=cfg,
    )

    language_catalog_entries = build_language_catalog_entries(
        final_entries,
        language_only_entries,
    )
    language_audit_rows = prepare_audit_rows(
        audit_items,
        language_catalog_entries,
        supported_language_codes=(
            supported_language_codes
        ),
        cfg=cfg,
    )

    test_candidates = (
        route_candidates_to_verified_countries(
            make_test_playlist_candidates(
                final_entries,
                audit_rows,
            ),
            cfg,
        )
    )

    (
        stable_candidates,
        excluded_rows,
    ) = (
        select_stable_playlist_candidates(
            final_entries,
            audit_rows,
            cfg,
        )
    )

    (
        language_stable_candidates,
        _language_excluded_rows,
    ) = select_stable_playlist_candidates(
        language_catalog_entries,
        language_audit_rows,
        cfg,
    )

    test_candidates = apply_channel_logos(test_candidates, logo_registry)
    stable_candidates = apply_channel_logos(stable_candidates, logo_registry)
    language_stable_candidates = apply_channel_logos(
        language_stable_candidates, logo_registry
    )

    test_entries = (
        prepare_published_entries(
            test_candidates,
            cfg,
        )
    )

    # Keep the old variable name for the rest of the reporting/dashboard
    # code. From now on, published_entries means the stable family playlist.
    published_entries = (
        prepare_published_entries(
            stable_candidates,
            cfg,
        )
    )

    language_published_entries = prepare_published_entries(
        language_stable_candidates,
        cfg,
    )

    previous_report = load_previous_report(cfg.get("previous_report_url"))
    unique_channels, country_stats, language_stats, changes = build_report_context(
        published_entries,
        test_entries,
        audit_rows,
        source_stats,
        previous_report,
    )

    out_path = ROOT / cfg.get(
        "output",
        "public/tv.m3u",
    )

    public_dir = (
        out_path.parent
    )

    public_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    generated = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    logo_quality = build_logo_quality(
        published_entries,
        generated_at=generated,
        registry_path=raw_logo_path,
    )
    write_logo_quality_outputs(
        logo_quality,
        output_path=public_dir / "logo-quality.json",
        missing_csv_path=public_dir / "missing-logos.csv",
    )
    logo_summary = logo_quality.get("summary") or {}
    print(
        "Logo coverage: "
        f"{logo_summary.get('with_logo', 0)}/"
        f"{logo_summary.get('stable_logical_channels', 0)} available "
        f"({float(logo_summary.get('logo_availability_percent') or 0):.1f}%); "
        f"{logo_summary.get('canonical_logo', 0)} canonical, "
        f"{logo_summary.get('source_fallback', 0)} source fallback, "
        f"{logo_summary.get('missing_logo', 0)} missing."
    )

    source_concentration = build_source_concentration(
        published_entries,
        cfg,
        generated_at=generated,
    )
    (public_dir / "source-concentration.json").write_text(
        json.dumps(source_concentration, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Main stable family playlist.
    write_m3u_playlist(
        out_path,
        cfg,
        published_entries,
        generated,
        "Stable family playlist",
        name_style="country",
    )

    # Full testing/research playlist.
    test_out_path = (
        ROOT
        / str(
            cfg.get(
                "test_output"
            )
            or "public/test.m3u"
        )
    )

    write_m3u_playlist(
        test_out_path,
        cfg,
        test_entries,
        generated,
        "Testing and research playlist",
    )

    # Stable per-country playlists.
    country_outputs = (
        cfg.get(
            "country_outputs"
        )
        or {
            "HU": "public/hu.m3u",
            "SK": "public/sk.m3u",
        }
    )

    if not isinstance(
        country_outputs,
        dict,
    ):
        raise RuntimeError(
            "country_outputs must be "
            "a JSON object."
        )

    country_playlist_counts: dict[
        str,
        int,
    ] = {}

    for (
        raw_country_code,
        relative_path,
    ) in country_outputs.items():
        country_code = (
            normalize_country_code(str(raw_country_code))
            or str(raw_country_code).strip().upper()
        )

        country_entries = [
            entry
            for entry
            in published_entries
            if str(
                entry.get(
                    "country_code"
                )
                or entry.get("language_code")
                or ""
            ).upper()
            == country_code
        ]

        country_path = (
            ROOT
            / str(
                relative_path
            )
        )

        country_name = (
            country_name_for_code(
                cfg,
                country_code,
            )
        )

        write_m3u_playlist(
            country_path,
            cfg,
            country_entries,
            generated,
            (
                f"Stable {country_name} "
                "playlist"
            ),
            name_style="plain",
        )

        country_playlist_counts[
            country_code
        ] = len(
            country_entries
        )

    # Stable per-spoken-language playlists. These are independent of enabled
    # country outputs: a verified RS/hun entry can therefore live in hun.m3u
    # even when there is no public rs.m3u yet. Country prefixes remain visible
    # inside language playlists so geography is never lost.
    language_outputs = cfg.get("language_outputs") or {}
    if not isinstance(language_outputs, dict):
        raise RuntimeError("language_outputs must be a JSON object.")

    language_names = cfg.get("language_names") or {}
    if not isinstance(language_names, dict):
        raise RuntimeError("language_names must be a JSON object.")

    language_playlist_counts: dict[str, int] = {}

    for raw_language_code, relative_path in language_outputs.items():
        language_code = normalize_spoken_language_code(
            str(raw_language_code)
        )
        if not language_code:
            raise RuntimeError(
                f"Invalid language_outputs key: {raw_language_code!r}"
            )

        raw_path = str(relative_path or "").strip()
        if not raw_path:
            raise RuntimeError(
                f"language_outputs[{raw_language_code!r}] requires a path."
            )

        language_entries = entries_for_spoken_language(
            language_published_entries,
            language_code,
        )

        language_name = str(
            language_names.get(language_code)
            or language_code
        ).strip()

        write_m3u_playlist(
            ROOT / raw_path,
            cfg,
            language_entries,
            generated,
            f"Stable {language_name} spoken-language playlist",
            name_style="country",
        )

        language_playlist_counts[language_code] = len(language_entries)

    write_build_csv_exports(
        public_dir,
        published_entries,
        duplicate_rows,
        excluded_rows,
        audit_rows,
    )

    write_machine_report(
        public_dir,
        cfg=cfg,
        generated=generated,
        published_entries=published_entries,
        test_entries=test_entries,
        excluded_rows=excluded_rows,
        duplicate_rows=duplicate_rows,
        source_stats=source_stats,
        country_stats=country_stats,
        language_stats=language_stats,
        source_concentration=source_concentration,
        changes=changes,
        audit_warnings=audit_warnings,
        audit_ambiguity_warnings=audit_ambiguity_warnings,
        audit_rows=audit_rows,
        unique_channels=unique_channels,
        raw_identity_path=raw_identity_path,
        identity_registry=identity_registry,
        country_playlist_counts=country_playlist_counts,
        language_playlist_counts=language_playlist_counts,
    )

    copy_dashboard_assets(public_dir)

    (public_dir / "index.html").write_text(
        make_dashboard(
            cfg=cfg,
            generated=generated,
            final_entries=published_entries,
            unique_channels=unique_channels,
            source_stats=source_stats,
            country_stats=country_stats,
            language_stats=language_stats,
            duplicate_rows=duplicate_rows,
            changes=changes,
            audit_rows=audit_rows,
            audit_ambiguity_warnings=(
                audit_ambiguity_warnings
            ),
        ),
        encoding="utf-8",
    )

    (public_dir / ".nojekyll").write_text("", encoding="utf-8")

    print_build_summary(
        unique_channels=unique_channels,
        published_entries=published_entries,
        test_entries=test_entries,
        excluded_rows=excluded_rows,
        duplicate_rows=duplicate_rows,
        country_playlist_counts=country_playlist_counts,
        audit_rows=audit_rows,
        source_stats=source_stats,
        country_stats=country_stats,
        language_stats=language_stats,
    )

if __name__ == "__main__":
    try:
        args = sys.argv[1:]

        unknown_args = [
            arg
            for arg in args
            if arg != "--strict"
        ]

        if unknown_args:
            raise RuntimeError(
                "Unknown command-line option(s): "
                + ", ".join(unknown_args)
            )

        strict = "--strict" in args

        if strict:
            print(
                "Strict audit validation enabled."
            )

        main(strict=strict)

    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
