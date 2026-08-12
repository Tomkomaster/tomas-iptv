#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Missing anchor in {path}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "static/dashboard.js",
    "const SUPPORTED_COUNTRIES = ['HU', 'SK', 'CZ'];",
    """const SUPPORTED_COUNTRIES = Array.from(document.querySelectorAll('[data-country-tab]'))
  .map(button => String(button.dataset.countryTab || '').toUpperCase())
  .filter(code => code && code !== 'ALL');""",
)

replace_once(
    "static/dashboard.js",
    "const testedStatuses = new Set(['works', 'works_with_warning', 'loads', 'mrl_error', 'format_error', 'generic_error', 'wrong_language', 'needs_review']);",
    "const testedStatuses = new Set(['works', 'works_with_warning', 'loads', 'mrl_error', 'format_error', 'generic_error', 'wrong_language']);",
)

replace_once(
    "dashboard.py",
    """    reroute_count = 0
    for a in audit_rows:
""",
    """    url_identity_conflicts = 0
    url_identities: dict[str, list[dict]] = {}
    for a in audit_rows:
        url = str(a.get("stream_url") or "").strip()
        if url:
            url_identities.setdefault(url, []).append(a)

    for url, rows_for_url in url_identities.items():
        identities = {
            (
                str(row.get("channel") or "").strip().casefold(),
                normalized_country_code(row.get("playlist_language_code")),
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
            normalized_country_code(row.get("playlist_language_code"))
            for row in rows_for_url
            if normalized_country_code(row.get("playlist_language_code")) != "UNKNOWN"
        })
        output_scopes = sorted({
            normalized_country_code(row.get("output_language_code"))
            for row in rows_for_url
            if normalized_country_code(row.get("output_language_code")) != "UNKNOWN"
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
""",
)

replace_once(
    "dashboard.py",
    """        "IDENTITY_UNRESOLVED": str(len(audit_ambiguity_warnings)),
        "IDENTITY_REROUTED": str(reroute_count),
""",
    """        "IDENTITY_UNRESOLVED": str(len(audit_ambiguity_warnings)),
        "IDENTITY_URL_CONFLICTS": str(url_identity_conflicts),
        "IDENTITY_REROUTED": str(reroute_count),
""",
)

replace_once(
    "templates/dashboard.html",
    """    <div class="card"><div class="value">@@IDENTITY_UNRESOLVED@@</div><div class="label">Unresolved identity warnings</div></div>
    <div class="card"><div class="value">@@IDENTITY_REROUTED@@</div><div class="label">Verified cross-country routings</div></div>
""",
    """    <div class="card"><div class="value">@@IDENTITY_UNRESOLVED@@</div><div class="label">Unresolved identity warnings</div></div>
    <div class="card"><div class="value">@@IDENTITY_URL_CONFLICTS@@</div><div class="label">Same-URL identity conflicts</div></div>
    <div class="card"><div class="value">@@IDENTITY_REROUTED@@</div><div class="label">Verified cross-country routings</div></div>
""",
)

replace_once(
    "tests/test_dashboard_operational_features.py",
    """        self.assertIn("Conflicting identities", page)
        self.assertIn("Candidate streams to test", page)
""",
    """        self.assertIn("Conflicting identities", page)
        self.assertIn("Same-URL identity conflicts", page)
        self.assertIn("Candidate streams to test", page)
""",
)

print("Dashboard identity refinement applied.")
