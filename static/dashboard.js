const SUPPORTED_COUNTRIES = ['HU', 'SK', 'CZ'];
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
