#!/usr/bin/env python3
from __future__ import annotations

import html
import shutil
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parent
DASHBOARD_TEMPLATE = MODULE_ROOT / "templates" / "dashboard.html"
DASHBOARD_STATIC = MODULE_ROOT / "static"
DASHBOARD_ASSETS = ("dashboard.css", "dashboard.js")


def _render_dashboard_template(context: dict[str, str]) -> str:
    rendered = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
    for key, value in context.items():
        rendered = rendered.replace(f"@@{key}@@", value)
    if any(f"@@{key}@@" in rendered for key in context):
        raise RuntimeError("Dashboard template still contains an unresolved value token.")
    return rendered


def copy_dashboard_assets(public_dir: Path) -> None:
    target = public_dir / "static"
    target.mkdir(parents=True, exist_ok=True)
    for name in DASHBOARD_ASSETS:
        shutil.copyfile(DASHBOARD_STATIC / name, target / name)


def render_dashboard(
    cfg: dict,
    generated: str,
    final_entries: list[dict],
    unique_channels: list[dict],
    source_stats: list[dict],
    country_stats: list[dict],
    language_stats: list[dict],
    duplicate_rows: list[dict],
    changes: dict,
    audit_rows: list[dict],
    audit_ambiguity_warnings: list[str],
    *,
    is_tested_status,
    format_language_codes,
) -> str:
    title = str(cfg.get("site_title") or "Tomas IPTV")
    epg_cfg = cfg.get("epg") or {}

    epg_link_html = ""

    if (
        isinstance(epg_cfg, dict)
        and epg_cfg.get("enabled")
        and str(
            epg_cfg.get("public_url") or ""
        ).strip()
    ):
        epg_link_html = (
            '<a href="guide.xml">'
            'EPG programme guide (guide.xml)'
            '</a>'
            ' · '
            '<a href="epg-coverage.json">'
            'EPG coverage report'
            '</a>'
        )
		
    total_streams = len(final_entries)
    total_channels = len(unique_channels)
    total_duplicates = len(duplicate_rows)
    total_alternatives = sum(1 for e in final_entries if e["classification"] == "Alternative stream")
    added_from_nonbase = sum(1 for e in final_entries if e["classification"] == "Added channel")
    audit_verified = sum(1 for e in audit_rows if e["decision"] == "Verified")
    audit_tv_verified = sum(1 for e in audit_rows if e["decision"] == "TV verified")
    audit_pc_only = sum(1 for e in audit_rows if e["decision"] == "PC only")
    audit_review = sum(1 for e in audit_rows if e["decision"] == "Needs review")
    audit_rejected = sum(1 for e in audit_rows if e["decision"] == "Rejected")
    audit_cross_language = sum(
        1
        for e in audit_rows
        if e.get(
            "language_acceptance"
        )
        == "supported_cross_language"
    )
    audit_current = [e for e in audit_rows if e["in_playlist"]]
    audit_both_tested = sum(
        1 for e in audit_current
        if is_tested_status(e["vlc"]) and is_tested_status(e["samsung"])
    )
    audit_vlc_pending = sum(
        1 for e in audit_current
        if not is_tested_status(e["vlc"])
    )
    audit_samsung_pending = sum(
        1 for e in audit_current
        if not is_tested_status(e["samsung"])
    )

    def esc(v) -> str:
        return html.escape(str(v or ""))

    def normalized_country_code(value) -> str:
        code = str(value or "").strip().upper()
        return code if 2 <= len(code) <= 3 and code.isalpha() else "UNKNOWN"

    def audit_country_code(row: dict) -> str:
        output = normalized_country_code(
            row.get("output_country_code") or row.get("output_country_code") or row.get("output_language_code")
        )
        if output != "UNKNOWN":
            return output
        scope = normalized_country_code(
            row.get("playlist_country_code") or row.get("playlist_country_code") or row.get("playlist_language_code")
        )
        if scope != "UNKNOWN":
            return scope
        expected = row.get("expected_language_codes") or []
        if isinstance(expected, str):
            expected = [part.strip() for part in expected.split(",") if part.strip()]
        if expected:
            return normalized_country_code(expected[0])
        return "UNKNOWN"

    country_outputs = cfg.get("country_outputs") or {}
    if isinstance(country_outputs, dict) and country_outputs:
        country_codes = [normalized_country_code(code) for code in country_outputs]
        country_codes = [code for code in country_codes if code != "UNKNOWN"]
    else:
        country_codes = ["HU", "SK", "CZ"]

    country_tabs = [
        '<button type="button" class="country-tab active" data-country-tab="ALL" aria-pressed="true">All</button>'
    ]
    country_tabs.extend(
        f'<button type="button" class="country-tab" data-country-tab="{esc(code)}" aria-pressed="false">{esc(code)}</button>'
        for code in country_codes
    )
    country_tabs_html = "".join(country_tabs)

    audit_warning_html = ""

    if audit_ambiguity_warnings:
        warning_items = "".join(
            f"<li>{esc(message)}</li>"
            for message in audit_ambiguity_warnings
        )

        audit_warning_html = f"""
        <div class="panel warning-panel">
          <strong>
            ⚠ Audit warnings ({len(audit_ambiguity_warnings)})
          </strong>
          <p>
            One or more old channel-level verification results became
            ambiguous because multiple current feeds now exist. The old
            results were not applied to any current stream.
          </p>
          <ul>
            {warning_items}
          </ul>
        </div>
        """
		
    source_options = "\n".join(
        f'<option value="{esc(s["name"])}">{esc(s["name"])}</option>'
        for s in source_stats
    )

    country_rows = "\n".join(
        f"""
        <tr data-country="{esc(normalized_country_code(s["country_code"]))}">
          <td><strong>{esc(s["country_code"])}</strong></td>
          <td>{s["source_count"]}</td>
          <td>{s["base_source_count"]}</td>
          <td>{s["unique_channels"]}</td>
          <td>{s["stream_urls"]}</td>
          <td>{s["base_channels"]}</td>
          <td>{s["added_channels"]}</td>
          <td>{s["alternative_streams"]}</td>
        </tr>
        """
        for s in country_stats
    )

    language_rows = "\n".join(
        f"""
        <tr>
          <td><strong>{esc(s["language_code"])}</strong></td>
          <td>{s["source_count"]}</td>
          <td>{s["base_source_count"]}</td>
          <td>{s["unique_channels"]}</td>
          <td>{s["stream_urls"]}</td>
          <td>{s["base_channels"]}</td>
          <td>{s["added_channels"]}</td>
          <td>{s["alternative_streams"]}</td>
        </tr>
        """
        for s in language_stats
    )
	
    source_row_parts = []
    for s in source_stats:
        raw_entries = int(s.get("raw_entries") or 0)
        kept_stream_urls = int(s.get("kept_stream_urls") or 0)
        yield_percent = (
            (100.0 * kept_stream_urls / raw_entries)
            if raw_entries
            else 0.0
        )
        source_row_parts.append(
            f"""
        <tr data-country="{esc(normalized_country_code(s.get("country_code") or s.get("language_code")))}">
          <td>{esc(s["name"])}</td>
          <td>{esc(s.get("country_code") or s.get("language_code"))}</td>
          <td>{esc(", ".join(s.get("language_codes") or []) or "—")}</td>
          <td>{esc(s["kind"])}</td>
          <td>{raw_entries}</td>
          <td>{s["unique_channels_in_source"]}</td>
          <td>{kept_stream_urls}</td>
          <td><strong>{yield_percent:.1f}%</strong><div class="detail">{kept_stream_urls}/{raw_entries} raw entries kept</div></td>
          <td>{s["base_channels_contributed"]}</td>
          <td>{s["added_channels_contributed"]}</td>
          <td>{s["alternative_streams"]}</td>
          <td>{s["duplicate_urls_ignored"]}</td>
        </tr>
        """
        )
    source_rows = "\n".join(source_row_parts)

    channel_rows = []
    for e in final_entries:
        entry_country = normalized_country_code(e.get("country_code") or e.get("language_code"))
        classification = e["classification"]
        badge_class = {
            "Base channel": "base",
            "Added channel": "added",
            "Alternative stream": "alt",
        }.get(classification, "base")

        channel_rows.append(
            f"""
            <tr data-country="{esc(entry_country)}" data-source="{esc(e["source"])}" data-status="{esc(classification)}">
              <td class="channel">{esc(e["channel_name"])}</td>
              <td>{esc(e.get("tvg_id", ""))}</td>
              <td>{esc(e.get("group_title", ""))}</td>
              <td>{esc(e["source"])}</td>
              <td><span class="badge {badge_class}">{esc(classification)}</span></td>
              <td class="url"><a href="{esc(e["url"])}" target="_blank" rel="noopener">stream</a></td>
            </tr>
            """
        )

    def test_badge(value: str) -> str:
        labels = {
            "works": ("✓ Works", "verified"),
            "works_with_warning": ("✓ Works*", "pc"),
            "loads": ("… Loads", "review"),
            "mrl_error": ("MRL error", "rejected"),
            "format_error": ("Format error", "rejected"),
            "generic_error": ("Player error", "rejected"),
            "wrong_language": ("Wrong language", "rejected"),
            "not_tested": ("? Not tested", "review"),
            "needs_review": ("? Review", "review"),
            "n/a": ("N/A", "base"),
        }
        label, css = labels.get(value, (value or "?", "review"))
        return f'<span class="badge {css}">{esc(label)}</span>'

    def language_match_badge(value: str) -> str:
        labels = {
            "yes": (
                "✓ Match",
                "verified",
            ),
            "multilingual": (
                "✓ Multilingual",
                "tv",
            ),
            "no": (
                "Wrong language",
                "rejected",
            ),
            "unknown": (
                "? Unknown",
                "review",
            ),
            "match": (
                "✓ Match",
                "verified",
            ),
            "supported_cross_language": (
                "✓ Supported cross-language",
                "tv",
            ),
            "unsupported": (
                "Unsupported language",
                "rejected",
            ),
        }

        label, css = labels.get(
            value,
            (
                value or "? Unknown",
                "review",
            ),
        )

        return (
            f'<span class="badge {css}">'
            f'{esc(label)}</span>'
        )
		
    audit_table_rows = []
    for a in audit_rows:
        audit_country = audit_country_code(a)
        decision_css = {
            "Verified": "verified",
            "TV verified": "tv",
            "PC only": "pc",
            "Needs review": "review",
            "Rejected": "rejected",
        }.get(a["decision"], "review")

        in_test_playlist = (
            '<span class="badge verified">Yes</span>'
            if a.get(
                "in_playlist"
            )
            else (
                '<span class="badge base">'
                'No</span>'
            )
        )

        in_stable_playlist = (
            '<span class="badge verified">Yes</span>'
            if a.get(
                "in_stable_playlist"
            )
            else (
                '<span class="badge base">'
                'No</span>'
            )
        )

        reason_notes = " — ".join(
            part for part in [a.get("reason", ""), a.get("notes", "")] if part
        )

        stream_link = (
            f'<a href="{esc(a["stream_url"])}" target="_blank" rel="noopener">stream</a>'
            if a.get("stream_url")
            else "—"
        )

        audit_table_rows.append(
            f"""
            <tr data-country="{esc(audit_country)}" data-audit-decision="{esc(a["decision"])}" data-audit-vlc="{esc(a["vlc"])}" data-audit-samsung="{esc(a["samsung"])}">
              <td class="channel">{esc(a["channel"])}</td>
              <td>{esc(a.get("feed_label", "Single"))}</td>
              <td>{esc(a.get("tvg_id", "") or "—")}</td>
              <td>{esc(a.get("source", "") or "—")}</td>
              <td>{esc(a["discovery"])}</td>
              <td>{esc(a["protocol"] or "—")}</td>
              <td>{esc(a.get("playlist_country_code") or a.get("playlist_language_code", "") or "—")}</td>
              <td>{esc(a.get("output_country_code") or a.get("output_language_code", "") or "—")}</td>
              <td>{esc(format_language_codes(a.get("expected_language_codes")))}</td>
              <td>{esc(format_language_codes(a.get("observed_language_codes")))}</td>
              <td>{language_match_badge(a.get("language_acceptance") or a.get("language_match", "unknown"))}</td>
              <td>{esc(a["provenance"])}</td>
              <td>{esc(", ".join(a.get("source_flags") or []) or "—")}</td>
              <td>{test_badge(a["vlc"])}<div class="detail">{esc(a.get("vlc_note", ""))}</div></td>
              <td>{test_badge(a["samsung"])}<div class="detail">{esc(a.get("samsung_note", ""))}</div></td>
              <td><span class="badge {decision_css}">{esc(a["decision"])}</span></td>
              <td>{in_test_playlist}</td>
              <td>{in_stable_playlist}</td>
              <td>{esc(reason_notes or "—")}</td>
              <td class="url">{stream_link}</td>
            </tr>
            """
        )

    identity_rows = []
    for message in audit_ambiguity_warnings:
        identity_rows.append(
            f"""
            <tr data-country="ALL">
              <td><span class="badge rejected">Unresolved</span></td>
              <td class="channel">Audit identity warning</td>
              <td>—</td>
              <td>—</td>
              <td>—</td>
              <td><div class="detail">{esc(message)}</div></td>
            </tr>
            """
        )

    url_identity_conflicts = 0
    url_identities: dict[str, list[dict]] = {}
    for a in audit_rows:
        url = str(a.get("stream_url") or "").strip()
        if url:
            url_identities.setdefault(url, []).append(a)

    for url, rows_for_url in url_identities.items():
        identities = {
            (
                str(row.get("channel") or "").strip().casefold(),
                normalized_country_code(row.get("playlist_country_code") or row.get("playlist_language_code")),
            )
            for row in rows_for_url
        }
        if len(identities) <= 1:
            continue

        url_identity_conflicts += 1
        channels = sorted({
            str(row.get("channel") or "Unnamed channel").strip()
            for row in rows_for_url
        }, key=str.casefold)
        source_scopes = sorted({
            normalized_country_code(row.get("playlist_country_code") or row.get("playlist_language_code"))
            for row in rows_for_url
            if normalized_country_code(row.get("playlist_country_code") or row.get("playlist_language_code")) != "UNKNOWN"
        })
        output_scopes = sorted({
            normalized_country_code(row.get("output_country_code") or row.get("output_language_code"))
            for row in rows_for_url
            if normalized_country_code(row.get("output_country_code") or row.get("output_language_code")) != "UNKNOWN"
        })
        identity_rows.append(
            f"""
            <tr data-country="ALL">
              <td><span class="badge rejected">URL conflict</span></td>
              <td class="channel">{esc(" / ".join(channels))}</td>
              <td>{esc(", ".join(source_scopes) or "—")}</td>
              <td>{esc(", ".join(output_scopes) or "—")}</td>
              <td>—</td>
              <td><div class="detail">The same saved stream URL appears under multiple channel/source-scope identities. Verification is not transferred automatically. <a href="{esc(url)}" target="_blank" rel="noopener">stream</a></div></td>
            </tr>
            """
        )

    reroute_count = 0
    for a in audit_rows:
        source_scope = normalized_country_code(a.get("playlist_country_code") or a.get("playlist_language_code"))
        output_scope = normalized_country_code(a.get("output_country_code") or a.get("output_language_code"))
        if (
            not a.get("in_playlist")
            or source_scope == "UNKNOWN"
            or output_scope == "UNKNOWN"
            or source_scope == output_scope
        ):
            continue
        reroute_count += 1
        identity_rows.append(
            f"""
            <tr data-country="{esc(output_scope)}">
              <td><span class="badge tv">Resolved routing</span></td>
              <td class="channel">{esc(a.get("channel") or "Unnamed channel")}</td>
              <td>{esc(source_scope)}</td>
              <td>{esc(output_scope)}</td>
              <td>{esc(format_language_codes(a.get("observed_language_codes")))}</td>
              <td><div class="detail">An explicit verified country-routing rule publishes this stream under {esc(output_scope)} while the saved audit/source identity remains {esc(source_scope)}.</div></td>
            </tr>
            """
        )

    previous = changes.get("previous_generated_at")
    if previous:
        added_names = changes.get("added_channels", [])
        removed_names = changes.get("removed_channels", [])

        def list_items(values: list[str], empty_text: str) -> str:
            if not values:
                return f"<li>{esc(empty_text)}</li>"
            return "".join(f"<li>{esc(v)}</li>" for v in values)

        change_html = f"""
        <div class="change-grid">
          <div class="panel">
            <h3>Added since previous build <span class="count positive">+{len(added_names)}</span></h3>
            <details {'open' if added_names else ''}>
              <summary>Show channels</summary>
              <ul>{list_items(added_names, "No channels added.")}</ul>
            </details>
          </div>
          <div class="panel">
            <h3>Removed since previous build <span class="count negative">-{len(removed_names)}</span></h3>
            <details {'open' if removed_names else ''}>
              <summary>Show channels</summary>
              <ul>{list_items(removed_names, "No channels removed.")}</ul>
            </details>
          </div>
        </div>
        <p class="muted">Compared with report generated {esc(previous)}.</p>
        """
    else:
        change_html = """
        <div class="panel">
          <strong>No previous report was available for comparison.</strong>
          <p class="muted">After the next successful build, this section will show channels added and removed since the previous deployment.</p>
        </div>
        """

    context = {
        "TITLE": str(esc(title)),
        "GENERATED": str(esc(generated)),
        "EPG_LINKS": str(epg_link_html),
        "TOTAL_CHANNELS": str(total_channels),
        "TOTAL_STREAMS": str(total_streams),
        "ADDED_FROM_NONBASE": str(added_from_nonbase),
        "TOTAL_ALTERNATIVES": str(total_alternatives),
        "TOTAL_DUPLICATES": str(total_duplicates),
        "AUDIT_WARNINGS": str(audit_warning_html),
        "COUNTRY_TABS": str(country_tabs_html),
        "IDENTITY_UNRESOLVED": str(len(audit_ambiguity_warnings)),
        "IDENTITY_URL_CONFLICTS": str(url_identity_conflicts),
        "IDENTITY_REROUTED": str(reroute_count),
        "IDENTITY_ROWS": str("".join(identity_rows)),
        "AUDIT_CURRENT_COUNT": str(len(audit_current)),
        "AUDIT_BOTH_TESTED": str(audit_both_tested),
        "AUDIT_VLC_PENDING": str(audit_vlc_pending),
        "AUDIT_SAMSUNG_PENDING": str(audit_samsung_pending),
        "AUDIT_VERIFIED": str(audit_verified),
        "AUDIT_TV_VERIFIED": str(audit_tv_verified),
        "AUDIT_PC_ONLY": str(audit_pc_only),
        "AUDIT_REVIEW": str(audit_review),
        "AUDIT_CROSS_LANGUAGE": str(audit_cross_language),
        "AUDIT_REJECTED": str(audit_rejected),
        "AUDIT_TABLE_ROWS": str(''.join(audit_table_rows)),
        "COUNTRY_ROWS": str(country_rows),
        "LANGUAGE_ROWS": str(language_rows),
        "SOURCE_ROWS": str(source_rows),
        "CHANGE_HTML": str(change_html),
        "SOURCE_OPTIONS": str(source_options),
        "CHANNEL_ROWS": str(''.join(channel_rows)),
    }
    return _render_dashboard_template(context)
