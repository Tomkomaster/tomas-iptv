#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Could not find expected block in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_once(path: str, marker: str, addition: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if addition.strip() in text:
        return
    if marker not in text:
        raise RuntimeError(f"Could not find append marker in {path}")
    p.write_text(text.replace(marker, marker + addition, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# healthcheck.py: preserve country from the stable [HU]/[SK]/[CZ] prefix.
# ---------------------------------------------------------------------------
replace_once(
    "healthcheck.py",
    '''STATUS_PREFIX_RE = re.compile(\n    r"^\\[(?P<country>[A-Z]{2,3})\\s+(?P<status>OK|TV|PC|\\?|X)\\]\\s*",\n    re.IGNORECASE,\n)''',
    '''STATUS_PREFIX_RE = re.compile(\n    r"^\\[(?P<country>[A-Z]{2,3})(?:\\s+(?P<status>OK|TV|PC|\\?|X))?\\]\\s*",\n    re.IGNORECASE,\n)''',
)
replace_once(
    "healthcheck.py",
    '        token = match.group("status").upper()\n',
    '        token = (match.group("status") or "").upper()\n',
)
replace_once(
    "healthcheck.py",
    '''            channel, manual_status = manual_status_from_name(\n                display_name or attrs.get("tvg-name", "")\n            )\n            pending = {\n                "channel": channel,\n                "playlist_name": display_name,\n                "manual_status": manual_status,''',
    '''            visible_name = display_name or attrs.get("tvg-name", "")\n            prefix_match = STATUS_PREFIX_RE.match(visible_name)\n            language_code = (\n                prefix_match.group("country").upper()\n                if prefix_match\n                else ""\n            )\n            channel, manual_status = manual_status_from_name(visible_name)\n            pending = {\n                "channel": channel,\n                "playlist_name": display_name,\n                "language_code": language_code,\n                "manual_status": manual_status,''',
)
replace_once(
    "healthcheck.py",
    '''        "playlist_name": entry.get("playlist_name", ""),\n        "tvg_id": entry.get("tvg_id", ""),''',
    '''        "playlist_name": entry.get("playlist_name", ""),\n        "language_code": entry.get("language_code", ""),\n        "tvg_id": entry.get("tvg_id", ""),''',
)

# ---------------------------------------------------------------------------
# attention.py: keep final published country on each attention item.
# ---------------------------------------------------------------------------
replace_once(
    "attention.py",
    '''def make_base_item(row: dict | None = None, *, channel: str = "", tvg_id: str = "", stream_url: str = "") -> dict:\n''',
    '''def row_country(row: dict) -> str:\n    for key in ("output_language_code", "playlist_language_code"):\n        value = str(row.get(key) or "").strip().upper()\n        if 2 <= len(value) <= 3 and value.isalpha():\n            return value\n\n    expected = row.get("expected_language_codes")\n    if isinstance(expected, (list, tuple)) and expected:\n        value = str(expected[0] or "").strip().upper()\n        if 2 <= len(value) <= 3 and value.isalpha():\n            return value\n    elif expected:\n        value = str(expected).split(",", 1)[0].strip().upper()\n        if 2 <= len(value) <= 3 and value.isalpha():\n            return value\n\n    return "UNKNOWN"\n\n\ndef make_base_item(row: dict | None = None, *, channel: str = "", tvg_id: str = "", stream_url: str = "") -> dict:\n''',
)
replace_once(
    "attention.py",
    '''        "channel": str(row.get("channel") or channel or "Unnamed channel").strip(),\n        "tvg_id": str(row.get("tvg_id") or tvg_id or "").strip(),''',
    '''        "country": row_country(row),\n        "channel": str(row.get("channel") or channel or "Unnamed channel").strip(),\n        "tvg_id": str(row.get("tvg_id") or tvg_id or "").strip(),''',
)
replace_once(
    "attention.py",
    '''            for field in (\n                "channel",\n                "tvg_id",''',
    '''            for field in (\n                "country",\n                "channel",\n                "tvg_id",''',
)

# ---------------------------------------------------------------------------
# dashboard.py: country metadata, identity conflicts, source yield and tabs.
# ---------------------------------------------------------------------------
replace_once(
    "dashboard.py",
    '''    def esc(v) -> str:\n        return html.escape(str(v or ""))\n\n    audit_warning_html = ""\n''',
    '''    def esc(v) -> str:\n        return html.escape(str(v or ""))\n\n    def normalized_country_code(value) -> str:\n        code = str(value or "").strip().upper()\n        return code if 2 <= len(code) <= 3 and code.isalpha() else "UNKNOWN"\n\n    def audit_country_code(row: dict) -> str:\n        output = normalized_country_code(row.get("output_language_code"))\n        if output != "UNKNOWN":\n            return output\n        scope = normalized_country_code(row.get("playlist_language_code"))\n        if scope != "UNKNOWN":\n            return scope\n        expected = row.get("expected_language_codes") or []\n        if isinstance(expected, str):\n            expected = [part.strip() for part in expected.split(",") if part.strip()]\n        if expected:\n            return normalized_country_code(expected[0])\n        return "UNKNOWN"\n\n    country_outputs = cfg.get("country_outputs") or {}\n    if isinstance(country_outputs, dict) and country_outputs:\n        country_codes = [normalized_country_code(code) for code in country_outputs]\n        country_codes = [code for code in country_codes if code != "UNKNOWN"]\n    else:\n        country_codes = ["HU", "SK", "CZ"]\n\n    country_tabs = [\n        '<button type="button" class="country-tab active" data-country-tab="ALL" aria-pressed="true">All</button>'\n    ]\n    country_tabs.extend(\n        f'<button type="button" class="country-tab" data-country-tab="{esc(code)}" aria-pressed="false">{esc(code)}</button>'\n        for code in country_codes\n    )\n    country_tabs_html = "".join(country_tabs)\n\n    audit_warning_html = ""\n''',
)
replace_once(
    "dashboard.py",
    '''        <tr>\n          <td><strong>{esc(s["language_code"])}</strong></td>''',
    '''        <tr data-country="{esc(normalized_country_code(s["language_code"]))}">\n          <td><strong>{esc(s["language_code"])}</strong></td>''',
)
replace_once(
    "dashboard.py",
    '''    source_rows = "\\n".join(\n        f"""\n        <tr>\n          <td>{esc(s["name"])}</td>\n          <td>{esc(s["language_code"])}</td>\n          <td>{esc(s["kind"])}</td>\n          <td>{s["raw_entries"]}</td>\n          <td>{s["unique_channels_in_source"]}</td>\n          <td>{s["kept_stream_urls"]}</td>\n          <td>{s["base_channels_contributed"]}</td>\n          <td>{s["added_channels_contributed"]}</td>\n          <td>{s["alternative_streams"]}</td>\n          <td>{s["duplicate_urls_ignored"]}</td>\n        </tr>\n        """\n        for s in source_stats\n    )\n''',
    '''    source_row_parts = []\n    for s in source_stats:\n        raw_entries = int(s.get("raw_entries") or 0)\n        kept_stream_urls = int(s.get("kept_stream_urls") or 0)\n        yield_percent = (\n            (100.0 * kept_stream_urls / raw_entries)\n            if raw_entries\n            else 0.0\n        )\n        source_row_parts.append(\n            f"""\n        <tr data-country="{esc(normalized_country_code(s.get("language_code")))}">\n          <td>{esc(s["name"])}</td>\n          <td>{esc(s["language_code"])}</td>\n          <td>{esc(s["kind"])}</td>\n          <td>{raw_entries}</td>\n          <td>{s["unique_channels_in_source"]}</td>\n          <td>{kept_stream_urls}</td>\n          <td><strong>{yield_percent:.1f}%</strong><div class="detail">{kept_stream_urls}/{raw_entries} raw entries kept</div></td>\n          <td>{s["base_channels_contributed"]}</td>\n          <td>{s["added_channels_contributed"]}</td>\n          <td>{s["alternative_streams"]}</td>\n          <td>{s["duplicate_urls_ignored"]}</td>\n        </tr>\n        """\n        )\n    source_rows = "\\n".join(source_row_parts)\n''',
)
replace_once(
    "dashboard.py",
    '''    channel_rows = []\n    for e in final_entries:\n        classification = e["classification"]''',
    '''    channel_rows = []\n    for e in final_entries:\n        entry_country = normalized_country_code(e.get("language_code"))\n        classification = e["classification"]''',
)
replace_once(
    "dashboard.py",
    '''            <tr data-source="{esc(e["source"])}" data-status="{esc(classification)}">''',
    '''            <tr data-country="{esc(entry_country)}" data-source="{esc(e["source"])}" data-status="{esc(classification)}">''',
)
replace_once(
    "dashboard.py",
    '''    audit_table_rows = []\n    for a in audit_rows:\n        decision_css = {''',
    '''    audit_table_rows = []\n    for a in audit_rows:\n        audit_country = audit_country_code(a)\n        decision_css = {''',
)
replace_once(
    "dashboard.py",
    '''            <tr data-audit-decision="{esc(a["decision"])}" data-audit-vlc="{esc(a["vlc"])}" data-audit-samsung="{esc(a["samsung"])}">''',
    '''            <tr data-country="{esc(audit_country)}" data-audit-decision="{esc(a["decision"])}" data-audit-vlc="{esc(a["vlc"])}" data-audit-samsung="{esc(a["samsung"])}">''',
)
replace_once(
    "dashboard.py",
    '''    previous = changes.get("previous_generated_at")\n''',
    '''    identity_rows = []\n    for message in audit_ambiguity_warnings:\n        identity_rows.append(\n            f"""\n            <tr data-country="ALL">\n              <td><span class="badge rejected">Unresolved</span></td>\n              <td class="channel">Audit identity warning</td>\n              <td>—</td>\n              <td>—</td>\n              <td>—</td>\n              <td><div class="detail">{esc(message)}</div></td>\n            </tr>\n            """\n        )\n\n    reroute_count = 0\n    for a in audit_rows:\n        source_scope = normalized_country_code(a.get("playlist_language_code"))\n        output_scope = normalized_country_code(a.get("output_language_code"))\n        if (\n            not a.get("in_playlist")\n            or source_scope == "UNKNOWN"\n            or output_scope == "UNKNOWN"\n            or source_scope == output_scope\n        ):\n            continue\n        reroute_count += 1\n        identity_rows.append(\n            f"""\n            <tr data-country="{esc(output_scope)}">\n              <td><span class="badge tv">Resolved routing</span></td>\n              <td class="channel">{esc(a.get("channel") or "Unnamed channel")}</td>\n              <td>{esc(source_scope)}</td>\n              <td>{esc(output_scope)}</td>\n              <td>{esc(format_language_codes(a.get("observed_language_codes")))}</td>\n              <td><div class="detail">Verified spoken language routes this stream to {esc(output_scope)} while the saved audit/source identity remains {esc(source_scope)}.</div></td>\n            </tr>\n            """\n        )\n\n    previous = changes.get("previous_generated_at")\n''',
)
replace_once(
    "dashboard.py",
    '''        "AUDIT_WARNINGS": str(audit_warning_html),\n        "AUDIT_CURRENT_COUNT": str(len(audit_current)),''',
    '''        "AUDIT_WARNINGS": str(audit_warning_html),\n        "COUNTRY_TABS": str(country_tabs_html),\n        "IDENTITY_UNRESOLVED": str(len(audit_ambiguity_warnings)),\n        "IDENTITY_REROUTED": str(reroute_count),\n        "IDENTITY_ROWS": str("".join(identity_rows)),\n        "AUDIT_CURRENT_COUNT": str(len(audit_current)),''',
)

# ---------------------------------------------------------------------------
# Dashboard template additions.
# ---------------------------------------------------------------------------
replace_once(
    "templates/dashboard.html",
    '''    <a href="sk.m3u">Stable Slovakia (sk.m3u)</a>\n    @@EPG_LINKS@@''',
    '''    <a href="sk.m3u">Stable Slovakia (sk.m3u)</a>\n    <a href="cz.m3u">Stable Czechia (cz.m3u)</a>\n    @@EPG_LINKS@@''',
)
replace_once(
    "templates/dashboard.html",
    '''  </div>\n\n  @@AUDIT_WARNINGS@@\n\n  <h2>EPG coverage by country</h2>''',
    '''  </div>\n\n  <nav id="countryTabs" class="country-tabs" aria-label="Dashboard country filter">\n    @@COUNTRY_TABS@@\n  </nav>\n  <p id="countryFilterLabel" class="muted country-filter-label">Showing all countries. Country tabs filter country-aware cards and tables below.</p>\n\n  @@AUDIT_WARNINGS@@\n\n  <h2>Conflicting identities</h2>\n  <p class="muted">\n    Identity safety is kept separate from playback status. Unresolved rows are audit\n    identities that could not be safely attached to one current feed. Resolved-routing\n    rows are verified streams whose spoken language publishes them under a different\n    country from the source/audit scope; these are informational, not duplicate channels.\n  </p>\n  <div class="audit-summary">\n    <div class="card"><div class="value">@@IDENTITY_UNRESOLVED@@</div><div class="label">Unresolved identity warnings</div></div>\n    <div class="card"><div class="value">@@IDENTITY_REROUTED@@</div><div class="label">Verified cross-country routings</div></div>\n  </div>\n  <p id="identityVisibleCount" class="muted"></p>\n  <div class="table-wrap">\n    <table id="identityTable">\n      <thead><tr><th>Status</th><th>Channel / warning</th><th>Audit/source scope</th><th>Published under</th><th>Observed language</th><th>Detail</th></tr></thead>\n      <tbody>@@IDENTITY_ROWS@@</tbody>\n    </table>\n  </div>\n\n  <h2>EPG coverage by country</h2>''',
)
replace_once(
    "templates/dashboard.html",
    '''  <h2>Needs attention</h2>\n''',
    '''  <h2>Candidate streams to test</h2>\n  <p class="muted">\n    This queue is built from the generated research ledger. It shows current, non-stable\n    feed URLs that still need VLC/Samsung testing or review, ordered by the P1/P2/P3\n    research priority. Test these before hunting for additional sources.\n  </p>\n  <div id="candidateSummary" class="audit-summary">\n    <div class="card"><div class="value">…</div><div class="label">Loading candidate queue</div></div>\n  </div>\n  <div class="controls">\n    <input id="candidateSearch" type="search" placeholder="Search candidate streams...">\n    <select id="candidatePriorityFilter">\n      <option value="">All research priorities</option>\n      <option value="P1">P1</option>\n      <option value="P2">P2</option>\n      <option value="P3">P3</option>\n    </select>\n  </div>\n  <p id="candidateVisibleCount" class="muted">Loading research.csv and missing.csv…</p>\n  <div class="table-wrap">\n    <table id="candidateTable">\n      <thead>\n        <tr><th>Priority</th><th>Country</th><th>Channel</th><th>Feed</th><th>Source</th><th>VLC</th><th>Samsung</th><th>Last tested</th><th>URL</th></tr>\n      </thead>\n      <tbody><tr><td colspan="9" class="muted">Loading candidate streams…</td></tr></tbody>\n    </table>\n  </div>\n\n  <h2>Needs attention</h2>\n''',
)
replace_once(
    "templates/dashboard.html",
    '''  <div id="healthSummary" class="audit-summary">\n    <div class="card"><div class="value">…</div><div class="label">Loading stream health</div></div>\n  </div>\n\n  <div class="controls">''',
    '''  <div id="healthSummary" class="audit-summary">\n    <div class="card"><div class="value">…</div><div class="label">Loading stream health</div></div>\n  </div>\n  <h3>Health by country</h3>\n  <div id="healthCountrySummary" class="audit-summary">\n    <div class="card"><div class="value">…</div><div class="label">Loading country health</div></div>\n  </div>\n\n  <div class="controls">''',
)
replace_once(
    "templates/dashboard.html",
    '''    <table>\n      <thead>\n        <tr>\n          <th>Language</th>''',
    '''    <table id="languageTable">\n      <thead>\n        <tr>\n          <th>Language</th>''',
)
replace_once(
    "templates/dashboard.html",
    '''  <h2>Source contribution</h2>\n  <div class="table-wrap">\n    <table>''',
    '''  <h2>Source contribution and yield</h2>\n  <p class="muted">Yield is the percentage of raw source entries whose unique stream URLs survive source-level URL deduplication into the combined candidate inventory.</p>\n  <div class="table-wrap">\n    <table id="sourceTable">''',
)
replace_once(
    "templates/dashboard.html",
    '''          <th>Stream URLs kept</th>\n          <th>Base channels</th>''',
    '''          <th>Stream URLs kept</th>\n          <th>Source yield</th>\n          <th>Base channels</th>''',
)

# ---------------------------------------------------------------------------
# Replace dashboard.js with a country-aware version preserving old features.
# ---------------------------------------------------------------------------
Path("static/dashboard.js").write_text(r'''const SUPPORTED_COUNTRIES = ['HU', 'SK', 'CZ'];
let selectedCountry = 'ALL';

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function normalizedCountry(value) {
  const code = String(value ?? '').trim().toUpperCase();
  return /^[A-Z]{2,3}$/.test(code) ? code : 'UNKNOWN';
}

function countryMatches(value) {
  const code = normalizedCountry(value);
  return selectedCountry === 'ALL' || code === 'ALL' || code === selectedCountry;
}

const countryButtons = Array.from(document.querySelectorAll('[data-country-tab]'));
const countryFilterLabel = document.getElementById('countryFilterLabel');

function setCountry(country) {
  selectedCountry = country === 'ALL' ? 'ALL' : normalizedCountry(country);
  for (const button of countryButtons) {
    const active = button.dataset.countryTab === selectedCountry;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  }
  if (countryFilterLabel) {
    countryFilterLabel.textContent = selectedCountry === 'ALL'
      ? 'Showing all countries. Country tabs filter country-aware cards and tables below.'
      : `Showing ${selectedCountry} only. Unresolved identity warnings with no safe country remain visible.`;
  }
  renderEpgCountryCoverage(epgData);
  renderAttentionSummary();
  applyAttentionFilters();
  renderHealthSummary();
  renderHealthCountrySummary();
  applyHealthFilters();
  renderCandidateSummary();
  applyCandidateFilters();
  applyAuditFilters();
  applyFilters();
  applyStaticCountryFilters();
}

for (const button of countryButtons) {
  button.addEventListener('click', () => setCountry(button.dataset.countryTab || 'ALL'));
}

const epgCountrySummary = document.getElementById('epgCountrySummary');
let epgData = null;

function renderEpgCountryCoverage(data) {
  if (!epgCountrySummary) return;
  const countries = data?.countries || {};
  const codes = SUPPORTED_COUNTRIES
    .filter(code => countries[code])
    .filter(countryMatches);
  if (!codes.length) {
    epgCountrySummary.innerHTML = '<div class="card"><div class="value">—</div><div class="label">Country EPG data unavailable</div></div>';
    return;
  }
  epgCountrySummary.innerHTML = codes.map(code => {
    const info = countries[code] || {};
    const total = Number(info.playlist_tvg_ids || 0);
    const mapped = Number(info.mapped_tvg_ids || 0);
    const populated = Number(info.channels_with_programmes || 0);
    const actual = Number(info.actual_programme_coverage_percent || 0).toFixed(1);
    const mappedPct = Number(info.mapping_coverage_percent || 0).toFixed(1);
    return `
      <div class="card" data-country="${esc(code)}">
        <div class="value">${actual}%</div>
        <div class="label">${code} programmes (${populated}/${total})</div>
        <div class="detail">Mapped: ${mapped}/${total} (${mappedPct}%)</div>
      </div>`;
  }).join('');
}

fetch('epg-health.json', { cache: 'no-store' })
  .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
  .then(data => { epgData = data; renderEpgCountryCoverage(data); })
  .catch(error => {
    if (epgCountrySummary) epgCountrySummary.innerHTML = `<div class="card"><div class="value">—</div><div class="label">EPG coverage unavailable: ${esc(error.message)}</div></div>`;
  });

function manualBadgeClass(status) {
  if (status === 'Verified' || status === 'Samsung + VLC') return 'verified';
  if (status === 'TV verified' || status === 'Samsung') return 'tv';
  if (status === 'PC only' || status === 'VLC only') return 'pc';
  if (status === 'Rejected') return 'rejected';
  if (status === 'Needs review') return 'review';
  return 'base';
}

function autoBadgeClass(status) {
  if (status === 'Online') return 'verified';
  if (status === 'Redirected' || status === 'TLS certificate warning') return 'tv';
  if (status === 'Slow startup') return 'review';
  if (status === 'Event inactive' || status === 'Unknown') return 'base';
  return 'rejected';
}

function epgBadgeClass(status) {
  if (status === 'Programme data') return 'verified';
  if (status === 'Unknown' || status === 'Not expected') return 'base';
  return 'review';
}

// Needs-attention queue ------------------------------------------------------
const attentionSearch = document.getElementById('attentionSearch');
const attentionSeverityFilter = document.getElementById('attentionSeverityFilter');
const attentionCategoryFilter = document.getElementById('attentionCategoryFilter');
const attentionVisibleCount = document.getElementById('attentionVisibleCount');
const attentionSummary = document.getElementById('attentionSummary');
const attentionTableBody = document.querySelector('#attentionTable tbody');
let attentionRows = [];
let attentionData = null;

function attentionBadgeClass(severity) {
  if (severity === 'critical' || severity === 'high') return 'rejected';
  if (severity === 'medium') return 'review';
  return 'base';
}

function renderAttentionSummary() {
  if (!attentionSummary || !attentionData) return;
  const items = (attentionData.items || []).filter(item => countryMatches(item.country));
  const counts = { critical: 0, high: 0, medium: 0, low: 0 };
  for (const item of items) counts[item.severity] = (counts[item.severity] || 0) + 1;
  const staleDays = attentionData.settings?.manual_stale_days ?? 30;
  attentionSummary.innerHTML = `
    <div class="card"><div class="value">${items.length}</div><div class="label">Channels needing attention</div></div>
    <div class="card"><div class="value">${counts.critical || 0}</div><div class="label">Critical</div></div>
    <div class="card"><div class="value">${counts.high || 0}</div><div class="label">High</div></div>
    <div class="card"><div class="value">${counts.medium || 0}</div><div class="label">Medium</div></div>
    <div class="card"><div class="value">${counts.low || 0}</div><div class="label">Low</div></div>
    <div class="card"><div class="value">${staleDays} d</div><div class="label">Manual-test age threshold</div></div>`;
}

function applyAttentionFilters() {
  if (!attentionSearch || !attentionSeverityFilter || !attentionCategoryFilter) return;
  const q = attentionSearch.value.trim().toLowerCase();
  const severity = attentionSeverityFilter.value;
  const category = attentionCategoryFilter.value;
  let shown = 0;
  for (const row of attentionRows) {
    const categories = (row.dataset.attentionCategories || '').split(',').filter(Boolean);
    const matchesText = !q || row.innerText.toLowerCase().includes(q);
    const matchesSeverity = !severity || row.dataset.attentionSeverity === severity;
    const matchesCategory = !category
      || (category === 'stream' && categories.some(value => value.startsWith('stream_')))
      || (category === 'manual' && categories.some(value => value.startsWith('manual_')))
      || (category === 'epg' && categories.some(value => value.startsWith('epg_')))
      || categories.includes(category);
    const show = countryMatches(row.dataset.country) && matchesText && matchesSeverity && matchesCategory;
    row.style.display = show ? '' : 'none';
    if (show) shown++;
  }
  if (attentionVisibleCount) attentionVisibleCount.textContent = `Showing ${shown} of ${attentionRows.length} attention items`;
}

function renderAttention(data) {
  attentionData = data;
  const items = Array.isArray(data.items) ? data.items : [];
  renderAttentionSummary();
  if (!items.length) {
    attentionTableBody.innerHTML = '<tr><td colspan="9"><span class="badge verified">Clear</span> No current attention items.</td></tr>';
    attentionRows = [];
    if (attentionVisibleCount) attentionVisibleCount.textContent = 'No channels currently need attention.';
    return;
  }
  attentionTableBody.innerHTML = items.map(item => {
    const signals = Array.isArray(item.signals) ? item.signals : [];
    const categories = signals.map(signal => signal.category || '').filter(Boolean);
    const reasons = signals.map(signal => `<div><span class="badge ${attentionBadgeClass(signal.severity)}">${esc(signal.label || signal.category || 'Attention')}</span><div class="detail">${esc(signal.detail || '')}</div></div>`).join('');
    const actions = [...new Set(signals.map(signal => signal.action).filter(Boolean))];
    const streamLink = item.stream_url ? `<a href="${esc(item.stream_url)}" target="_blank" rel="noopener">stream</a>` : '—';
    const autoSuffix = Number(item.consecutive_failures || 0) > 0 ? ` ×${Number(item.consecutive_failures)}` : '';
    return `
      <tr data-country="${esc(item.country || 'UNKNOWN')}" data-attention-severity="${esc(item.severity)}" data-attention-categories="${esc(categories.join(','))}">
        <td><span class="badge ${attentionBadgeClass(item.severity)}">${esc(String(item.severity || 'low').toUpperCase())}</span><div class="detail">Score ${Number(item.priority_score || 0)}</div></td>
        <td class="channel">${esc(item.channel)}</td>
        <td>${reasons || '—'}</td>
        <td>${actions.map(action => `<div class="detail">${esc(action)}</div>`).join('') || '—'}</td>
        <td><span class="badge ${manualBadgeClass(item.manual_status)}">${esc(item.manual_status || 'Unknown')}</span></td>
        <td><span class="badge ${autoBadgeClass(item.auto_status)}">${esc(item.auto_status || 'Unknown')}${autoSuffix}</span></td>
        <td><span class="badge ${epgBadgeClass(item.epg_status)}">${esc(item.epg_status || 'Unknown')}</span></td>
        <td>${esc(item.tested_on || '—')}</td><td class="url">${streamLink}</td>
      </tr>`;
  }).join('');
  attentionRows = Array.from(document.querySelectorAll('#attentionTable tbody tr'));
  applyAttentionFilters();
}

fetch('attention.json', { cache: 'no-store' })
  .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
  .then(renderAttention)
  .catch(error => {
    if (attentionSummary) attentionSummary.innerHTML = '<div class="card"><div class="value">—</div><div class="label">Attention data unavailable</div></div>';
    if (attentionTableBody) attentionTableBody.innerHTML = `<tr><td colspan="9">attention.json could not be loaded: ${esc(error.message)}</td></tr>`;
    if (attentionVisibleCount) attentionVisibleCount.textContent = 'attention.json is not available yet.';
  });
if (attentionSearch) attentionSearch.addEventListener('input', applyAttentionFilters);
if (attentionSeverityFilter) attentionSeverityFilter.addEventListener('change', applyAttentionFilters);
if (attentionCategoryFilter) attentionCategoryFilter.addEventListener('change', applyAttentionFilters);

// Automated health ---------------------------------------------------------
const healthSearch = document.getElementById('healthSearch');
const healthStatusFilter = document.getElementById('healthStatusFilter');
const healthVisibleCount = document.getElementById('healthVisibleCount');
const healthSummary = document.getElementById('healthSummary');
const healthCountrySummary = document.getElementById('healthCountrySummary');
const healthTableBody = document.querySelector('#healthTable tbody');
let healthRows = [];
let healthData = null;

function filteredHealthStreams() {
  return (healthData?.streams || []).filter(item => countryMatches(item.language_code));
}

function healthStats(streams) {
  const statusCounts = {};
  for (const item of streams) statusCounts[item.status] = (statusCounts[item.status] || 0) + 1;
  return {
    total: streams.length,
    playable: streams.filter(item => item.success).length,
    failed: streams.filter(item => item.actionable_failure).length,
    inactive: streams.filter(item => !item.success && item.actionable_failure === false).length,
    retest: streams.filter(item => item.manual_retest_recommended).length,
    statusCounts,
  };
}

function renderHealthSummary() {
  if (!healthSummary || !healthData) return;
  const stats = healthStats(filteredHealthStreams());
  healthSummary.innerHTML = `
    <div class="card"><div class="value">${stats.playable}</div><div class="label">Playable now</div></div>
    <div class="card"><div class="value">${stats.statusCounts['Online'] || 0}</div><div class="label">Online</div></div>
    <div class="card"><div class="value">${stats.statusCounts['Redirected'] || 0}</div><div class="label">Redirected</div></div>
    <div class="card"><div class="value">${stats.statusCounts['Slow startup'] || 0}</div><div class="label">Slow startup</div></div>
    <div class="card"><div class="value">${stats.failed}</div><div class="label">Actionable failures</div></div>
    <div class="card"><div class="value">${stats.inactive}</div><div class="label">Event-based inactive</div></div>
    <div class="card"><div class="value">${stats.retest}</div><div class="label">Needs manual retest</div></div>
    <div class="card"><div class="value">${esc(healthData.generated_at || '—')}</div><div class="label">Last automated check</div></div>`;
}

function renderHealthCountrySummary() {
  if (!healthCountrySummary || !healthData) return;
  const allStreams = healthData.streams || [];
  const codes = SUPPORTED_COUNTRIES.filter(countryMatches);
  healthCountrySummary.innerHTML = codes.map(code => {
    const streams = allStreams.filter(item => normalizedCountry(item.language_code) === code);
    const stats = healthStats(streams);
    const pct = stats.total ? (100 * stats.playable / stats.total).toFixed(1) : '0.0';
    return `<div class="card" data-country="${code}"><div class="value">${pct}%</div><div class="label">${code} playable (${stats.playable}/${stats.total})</div><div class="detail">Failures: ${stats.failed} · Retest: ${stats.retest} · Event inactive: ${stats.inactive}</div></div>`;
  }).join('');
}

function applyHealthFilters() {
  if (!healthSearch || !healthStatusFilter) return;
  const q = healthSearch.value.trim().toLowerCase();
  const status = healthStatusFilter.value;
  let shown = 0;
  for (const row of healthRows) {
    const matchesText = !q || row.innerText.toLowerCase().includes(q);
    const matchesStatus = !status
      || (status === 'playable' && row.dataset.healthSuccess === 'yes')
      || (status === 'failed' && row.dataset.healthActionable === 'yes')
      || (status === 'needs_manual_retest' && row.dataset.healthAttention === 'needs_manual_retest')
      || row.dataset.healthStatus === status;
    const show = countryMatches(row.dataset.country) && matchesText && matchesStatus;
    row.style.display = show ? '' : 'none';
    if (show) shown++;
  }
  if (healthVisibleCount) healthVisibleCount.textContent = `Showing ${shown} of ${healthRows.length} stable streams`;
}

function renderHealth(data) {
  healthData = data;
  const streams = Array.isArray(data.streams) ? data.streams : [];
  renderHealthSummary();
  renderHealthCountrySummary();
  healthTableBody.innerHTML = streams.map(item => {
    const autoClass = item.manual_retest_recommended ? 'rejected' : (item.attention === 'informational' ? 'base' : autoBadgeClass(item.status));
    const failureSuffix = item.actionable_failure ? ` ×${item.consecutive_failures || 1}` : '';
    const startup = Number.isFinite(Number(item.startup_seconds)) ? `${Number(item.startup_seconds).toFixed(2)} s` : '—';
    const detail = item.manual_retest_recommended ? `${item.detail || ''} Manual VLC + Samsung retest recommended.` : (item.detail || '—');
    return `
      <tr data-country="${esc(item.language_code || 'UNKNOWN')}" data-health-status="${esc(item.status)}" data-health-success="${item.success ? 'yes' : 'no'}" data-health-actionable="${item.actionable_failure ? 'yes' : 'no'}" data-health-attention="${esc(item.attention)}">
        <td class="channel">${esc(item.channel)}</td>
        <td><span class="badge ${manualBadgeClass(item.manual_status)}">${esc(item.manual_status || 'Unknown')}</span></td>
        <td><span class="badge ${autoClass}">${esc(item.status)}${failureSuffix}</span></td>
        <td>${item.consecutive_failures || 0}</td><td>${esc(startup)}</td>
        <td>${esc(item.checked_at || data.generated_at || '—')}</td><td><div class="detail">${esc(detail)}</div></td>
        <td class="url"><a href="${esc(item.stream_url)}" target="_blank" rel="noopener">stream</a></td>
      </tr>`;
  }).join('');
  healthRows = Array.from(document.querySelectorAll('#healthTable tbody tr'));
  applyHealthFilters();
}

fetch('health.json', { cache: 'no-store' })
  .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
  .then(renderHealth)
  .catch(error => {
    if (healthSummary) healthSummary.innerHTML = '<div class="card"><div class="value">—</div><div class="label">Health data unavailable</div></div>';
    if (healthCountrySummary) healthCountrySummary.innerHTML = '<div class="card"><div class="value">—</div><div class="label">Country health unavailable</div></div>';
    if (healthTableBody) healthTableBody.innerHTML = `<tr><td colspan="8">Automated health data could not be loaded: ${esc(error.message)}</td></tr>`;
    if (healthVisibleCount) healthVisibleCount.textContent = 'health.json is not available yet.';
  });
if (healthSearch) healthSearch.addEventListener('input', applyHealthFilters);
if (healthStatusFilter) healthStatusFilter.addEventListener('change', applyHealthFilters);

// Candidate streams --------------------------------------------------------
const candidateSearch = document.getElementById('candidateSearch');
const candidatePriorityFilter = document.getElementById('candidatePriorityFilter');
const candidateVisibleCount = document.getElementById('candidateVisibleCount');
const candidateSummary = document.getElementById('candidateSummary');
const candidateTableBody = document.querySelector('#candidateTable tbody');
let candidateItems = [];
let candidateRows = [];

function parseCsv(text) {
  const matrix = [];
  let row = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (ch === '"') quoted = false;
      else field += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ',') { row.push(field); field = ''; }
    else if (ch === '\n') { row.push(field.replace(/\r$/, '')); matrix.push(row); row = []; field = ''; }
    else field += ch;
  }
  if (field || row.length) { row.push(field.replace(/\r$/, '')); matrix.push(row); }
  if (!matrix.length) return [];
  const headers = matrix.shift().map((value, index) => (index === 0 ? value.replace(/^\uFEFF/, '') : value));
  return matrix.filter(values => values.some(value => value !== '')).map(values => Object.fromEntries(headers.map((key, index) => [key, values[index] ?? ''])));
}

function csvTruthy(value) {
  return ['1', 'true', 'yes', 'y', 'on'].includes(String(value || '').trim().toLowerCase());
}

const testedStatuses = new Set(['works', 'works_with_warning', 'loads', 'mrl_error', 'format_error', 'generic_error', 'wrong_language', 'needs_review']);
function normalizedTestStatus(value) { return String(value || '').trim().toLowerCase().replaceAll(' ', '_').replaceAll('-', '_'); }
function candidateNeedsTest(row) {
  if (!csvTruthy(row.current_candidate) || csvTruthy(row.stable_feed)) return false;
  const vlcTested = testedStatuses.has(normalizedTestStatus(row.vlc));
  const samsungTested = testedStatuses.has(normalizedTestStatus(row.samsung));
  return row.feed_status === 'Needs review' || !vlcTested || !samsungTested;
}
function candidateKey(row) { return `${normalizedCountry(row.country)}\u0000${String(row.channel || '').trim().toLowerCase()}`; }
function priorityRank(value) { return ({ P1: 1, P2: 2, P3: 3 })[value] || 9; }
function priorityBadgeClass(value) { return value === 'P1' ? 'rejected' : (value === 'P2' ? 'review' : 'base'); }
function testBadgeClass(value) {
  const status = normalizedTestStatus(value);
  if (status === 'works' || status === 'works_with_warning') return 'verified';
  if (status === 'not_tested' || !status) return 'review';
  if (status === 'loads' || status === 'needs_review') return 'review';
  return 'rejected';
}

function renderCandidateSummary() {
  if (!candidateSummary) return;
  const items = candidateItems.filter(item => countryMatches(item.country));
  const channels = new Set(items.map(candidateKey));
  const counts = { P1: 0, P2: 0, P3: 0 };
  for (const item of items) if (counts[item.priority] !== undefined) counts[item.priority]++;
  candidateSummary.innerHTML = `
    <div class="card"><div class="value">${items.length}</div><div class="label">Candidate feed URLs to test</div></div>
    <div class="card"><div class="value">${channels.size}</div><div class="label">Channels represented</div></div>
    <div class="card"><div class="value">${counts.P1}</div><div class="label">P1 feeds</div></div>
    <div class="card"><div class="value">${counts.P2}</div><div class="label">P2 feeds</div></div>
    <div class="card"><div class="value">${counts.P3}</div><div class="label">P3 feeds</div></div>`;
}

function applyCandidateFilters() {
  if (!candidateSearch || !candidatePriorityFilter) return;
  const q = candidateSearch.value.trim().toLowerCase();
  const priority = candidatePriorityFilter.value;
  let shown = 0;
  for (const row of candidateRows) {
    const show = countryMatches(row.dataset.country)
      && (!priority || row.dataset.priority === priority)
      && (!q || row.innerText.toLowerCase().includes(q));
    row.style.display = show ? '' : 'none';
    if (show) shown++;
  }
  if (candidateVisibleCount) candidateVisibleCount.textContent = `Showing ${shown} of ${candidateRows.length} candidate feed URLs that still need testing`;
}

function renderCandidates() {
  renderCandidateSummary();
  if (!candidateItems.length) {
    candidateTableBody.innerHTML = '<tr><td colspan="9"><span class="badge verified">Clear</span> No current candidate feeds require testing.</td></tr>';
    candidateRows = [];
    if (candidateVisibleCount) candidateVisibleCount.textContent = 'No current candidate streams require testing.';
    return;
  }
  candidateTableBody.innerHTML = candidateItems.map(item => `
    <tr data-country="${esc(item.country)}" data-priority="${esc(item.priority)}">
      <td><span class="badge ${priorityBadgeClass(item.priority)}">${esc(item.priority || 'P3')}</span><div class="detail">${esc(item.priority_label || '')}</div></td>
      <td><strong>${esc(item.country)}</strong></td><td class="channel">${esc(item.channel)}</td><td>${esc(item.feed_label || 'Single')}</td><td>${esc(item.source || '—')}</td>
      <td><span class="badge ${testBadgeClass(item.vlc)}">${esc(item.vlc || 'not_tested')}</span></td>
      <td><span class="badge ${testBadgeClass(item.samsung)}">${esc(item.samsung || 'not_tested')}</span></td>
      <td>${esc(item.tested_on || '—')}</td><td class="url"><a href="${esc(item.stream_url)}" target="_blank" rel="noopener">stream</a></td>
    </tr>`).join('');
  candidateRows = Array.from(document.querySelectorAll('#candidateTable tbody tr'));
  applyCandidateFilters();
}

Promise.all([
  fetch('research.csv', { cache: 'no-store' }).then(r => { if (!r.ok) throw new Error(`research.csv HTTP ${r.status}`); return r.text(); }),
  fetch('missing.csv', { cache: 'no-store' }).then(r => { if (!r.ok) throw new Error(`missing.csv HTTP ${r.status}`); return r.text(); }),
]).then(([researchText, missingText]) => {
  const research = parseCsv(researchText);
  const missing = parseCsv(missingText);
  const priorityByChannel = new Map(missing.map(row => [candidateKey(row), row]));
  candidateItems = research.filter(candidateNeedsTest).map(row => {
    const priority = priorityByChannel.get(candidateKey(row)) || {};
    return { ...row, priority: priority.priority || 'P3', priority_label: priority.priority_label || '', priority_reason: priority.priority_reason || '' };
  }).sort((a, b) => priorityRank(a.priority) - priorityRank(b.priority)
    || normalizedCountry(a.country).localeCompare(normalizedCountry(b.country))
    || String(a.channel).localeCompare(String(b.channel))
    || String(a.feed_label).localeCompare(String(b.feed_label)));
  renderCandidates();
}).catch(error => {
  if (candidateSummary) candidateSummary.innerHTML = '<div class="card"><div class="value">—</div><div class="label">Candidate queue unavailable</div></div>';
  if (candidateTableBody) candidateTableBody.innerHTML = `<tr><td colspan="9">Candidate research exports could not be loaded: ${esc(error.message)}</td></tr>`;
  if (candidateVisibleCount) candidateVisibleCount.textContent = 'Candidate queue is not available yet.';
});
if (candidateSearch) candidateSearch.addEventListener('input', applyCandidateFilters);
if (candidatePriorityFilter) candidatePriorityFilter.addEventListener('change', applyCandidateFilters);

// Static generated tables --------------------------------------------------
const search = document.getElementById('search');
const sourceFilter = document.getElementById('sourceFilter');
const statusFilter = document.getElementById('statusFilter');
const rows = Array.from(document.querySelectorAll('#channels tbody tr'));
const visibleCount = document.getElementById('visibleCount');

function applyFilters() {
  if (!search || !sourceFilter || !statusFilter) return;
  const q = search.value.trim().toLowerCase();
  const source = sourceFilter.value;
  const status = statusFilter.value;
  let shown = 0;
  for (const row of rows) {
    const show = countryMatches(row.dataset.country)
      && (!q || row.innerText.toLowerCase().includes(q))
      && (!source || row.dataset.source === source)
      && (!status || row.dataset.status === status);
    row.style.display = show ? '' : 'none';
    if (show) shown++;
  }
  if (visibleCount) visibleCount.textContent = `Showing ${shown} of ${rows.length} stream entries`;
}

const auditSearch = document.getElementById('auditSearch');
const auditDecisionFilter = document.getElementById('auditDecisionFilter');
const auditVlcFilter = document.getElementById('auditVlcFilter');
const auditSamsungFilter = document.getElementById('auditSamsungFilter');
const auditRows = Array.from(document.querySelectorAll('#auditTable tbody tr'));
const auditVisibleCount = document.getElementById('auditVisibleCount');

function applyAuditFilters() {
  if (!auditSearch || !auditDecisionFilter || !auditVlcFilter || !auditSamsungFilter) return;
  const q = auditSearch.value.trim().toLowerCase();
  const decision = auditDecisionFilter.value;
  const vlc = auditVlcFilter.value;
  const samsung = auditSamsungFilter.value;
  let shown = 0;
  for (const row of auditRows) {
    const show = countryMatches(row.dataset.country)
      && (!q || row.innerText.toLowerCase().includes(q))
      && (!decision || row.dataset.auditDecision === decision)
      && (!vlc || row.dataset.auditVlc === vlc)
      && (!samsung || row.dataset.auditSamsung === samsung);
    row.style.display = show ? '' : 'none';
    if (show) shown++;
  }
  if (auditVisibleCount) auditVisibleCount.textContent = `Showing ${shown} of ${auditRows.length} manually reviewed/candidate channels`;
}

const staticCountryRows = Array.from(document.querySelectorAll('#languageTable tbody tr, #sourceTable tbody tr, #identityTable tbody tr'));
const identityVisibleCount = document.getElementById('identityVisibleCount');
function applyStaticCountryFilters() {
  let visibleIdentity = 0;
  const identityRows = Array.from(document.querySelectorAll('#identityTable tbody tr'));
  for (const row of staticCountryRows) row.style.display = countryMatches(row.dataset.country) ? '' : 'none';
  for (const row of identityRows) if (row.style.display !== 'none') visibleIdentity++;
  if (identityVisibleCount) identityVisibleCount.textContent = `Showing ${visibleIdentity} identity rows for the current country filter`;
}

if (auditSearch) auditSearch.addEventListener('input', applyAuditFilters);
if (auditDecisionFilter) auditDecisionFilter.addEventListener('change', applyAuditFilters);
if (auditVlcFilter) auditVlcFilter.addEventListener('change', applyAuditFilters);
if (auditSamsungFilter) auditSamsungFilter.addEventListener('change', applyAuditFilters);
if (search) search.addEventListener('input', applyFilters);
if (sourceFilter) sourceFilter.addEventListener('change', applyFilters);
if (statusFilter) statusFilter.addEventListener('change', applyFilters);

applyAuditFilters();
applyFilters();
applyStaticCountryFilters();
''', encoding="utf-8")

# ---------------------------------------------------------------------------
# CSS additions.
# ---------------------------------------------------------------------------
append_once(
    "static/dashboard.css",
    '''.count { font-size: .9rem; }\n''',
    '''.country-tabs {\n  display: flex;\n  gap: 8px;\n  flex-wrap: wrap;\n  margin: 22px 0 8px;\n  padding: 6px;\n  border: 1px solid var(--border);\n  border-radius: 12px;\n  width: fit-content;\n  background: var(--card);\n}\n.country-tab {\n  width: auto;\n  min-width: 58px;\n  padding: 8px 14px;\n  border: 1px solid transparent;\n  border-radius: 8px;\n  background: transparent;\n  color: var(--text);\n  font-weight: 700;\n  cursor: pointer;\n}\n.country-tab:hover { border-color: var(--border); }\n.country-tab.active {\n  border-color: var(--accent);\n  color: var(--accent);\n}\n.country-filter-label { margin-top: 0; }\n''',
)
replace_once(
    "static/dashboard.css",
    '''input, select {\n''',
    '''button, input, select {\n''',
)

# ---------------------------------------------------------------------------
# New regression tests.
# ---------------------------------------------------------------------------
Path("tests/test_dashboard_operational_features.py").write_text('''import tempfile\nimport unittest\nfrom pathlib import Path\n\nfrom attention import make_base_item\nfrom build import make_dashboard\nfrom healthcheck import read_playlist\n\n\nclass DashboardOperationalFeatureTests(unittest.TestCase):\n    def dashboard(self):\n        return make_dashboard(\n            cfg={\n                "site_title": "Test IPTV",\n                "country_outputs": {"HU": "public/hu.m3u", "SK": "public/sk.m3u", "CZ": "public/cz.m3u"},\n                "epg": {"enabled": False},\n            },\n            generated="2026-08-12 09:00:00 UTC",\n            final_entries=[{\n                "classification": "Base channel",\n                "source": "HU source",\n                "channel_name": "Demo TV",\n                "tvg_id": "Demo.hu",\n                "group_title": "Hungary | General",\n                "url": "https://example.test/demo.m3u8",\n                "language_code": "HU",\n            }],\n            unique_channels=[{"channel_name": "Demo TV"}],\n            source_stats=[{\n                "name": "HU source",\n                "language_code": "HU",\n                "kind": "base",\n                "raw_entries": 4,\n                "unique_channels_in_source": 3,\n                "kept_stream_urls": 2,\n                "base_channels_contributed": 2,\n                "added_channels_contributed": 0,\n                "alternative_streams": 0,\n                "duplicate_urls_ignored": 2,\n            }],\n            language_stats=[{\n                "language_code": "HU",\n                "source_count": 1,\n                "base_source_count": 1,\n                "unique_channels": 1,\n                "stream_urls": 1,\n                "base_channels": 1,\n                "added_channels": 0,\n                "alternative_streams": 0,\n            }],\n            duplicate_rows=[],\n            changes={"previous_generated_at": None, "added_channels": [], "removed_channels": []},\n            audit_rows=[{\n                "channel": "Demo TV",\n                "feed_label": "Single",\n                "tvg_id": "Demo.hu",\n                "source": "HU source",\n                "discovery": "base",\n                "protocol": "HLS",\n                "playlist_language_code": "HU",\n                "output_language_code": "HU",\n                "expected_language_codes": ["HU"],\n                "observed_language_codes": [],\n                "language_acceptance": "unknown",\n                "provenance": "Upstream",\n                "source_flags": [],\n                "vlc": "not_tested",\n                "vlc_note": "",\n                "samsung": "not_tested",\n                "samsung_note": "",\n                "decision": "Needs review",\n                "in_playlist": True,\n                "in_stable_playlist": False,\n                "reason": "",\n                "notes": "",\n                "stream_url": "https://example.test/demo.m3u8",\n            }],\n            audit_ambiguity_warnings=["Demo TV became ambiguous after 2 feeds."],\n        )\n\n    def test_dashboard_has_country_operations_sections(self):\n        page = self.dashboard()\n        self.assertIn('data-country-tab="ALL"', page)\n        self.assertIn('data-country-tab="HU"', page)\n        self.assertIn('data-country="HU"', page)\n        self.assertIn("Conflicting identities", page)\n        self.assertIn("Candidate streams to test", page)\n        self.assertIn("Health by country", page)\n        self.assertIn("Source contribution and yield", page)\n        self.assertIn("50.0%", page)\n        self.assertIn("Demo TV became ambiguous after 2 feeds", page)\n\n    def test_dashboard_js_uses_generated_country_and_research_data(self):\n        script = Path("static/dashboard.js").read_text(encoding="utf-8")\n        self.assertIn("selectedCountry", script)\n        self.assertIn("fetch('research.csv'", script)\n        self.assertIn("fetch('missing.csv'", script)\n        self.assertIn("healthCountrySummary", script)\n        self.assertIn("candidateNeedsTest", script)\n\n    def test_stable_playlist_prefix_preserves_health_country(self):\n        with tempfile.TemporaryDirectory() as tmp:\n            path = Path(tmp) / "stable.m3u"\n            path.write_text(\n                '#EXTM3U\\n#EXTINF:-1 tvg-id="Prima.cz",[CZ] Prima\\nhttps://example.test/prima.m3u8\\n',\n                encoding="utf-8",\n            )\n            rows = read_playlist(path)\n        self.assertEqual(rows[0]["channel"], "Prima")\n        self.assertEqual(rows[0]["language_code"], "CZ")\n\n    def test_attention_base_item_preserves_published_country(self):\n        item = make_base_item({\n            "channel": "Cross-language TV",\n            "playlist_language_code": "SK",\n            "output_language_code": "CZ",\n        })\n        self.assertEqual(item["country"], "CZ")\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding="utf-8")

print("Dashboard country operations feature patch applied.")
