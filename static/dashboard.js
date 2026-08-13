const SUPPORTED_COUNTRIES = Array.from(document.querySelectorAll('[data-country-tab]'))
  .map(button => String(button.dataset.countryTab || '').toUpperCase())
  .filter(code => code && code !== 'ALL');
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
  renderEpgQuality();
  applyEpgQualityFilters();
  renderLogoQuality();
  applyLogoQualityFilters();
  renderAttentionSummary();
  applyAttentionFilters();
  renderHealthSummary();
  renderHealthCountrySummary();
  applyHealthFilters();
  renderSourceConcentration();
  renderCandidateSummary();
  applyCandidateFilters();
  applyAuditFilters();
  applyFilters();
  applyStaticCountryFilters();
}

for (const button of countryButtons) {
  button.addEventListener('click', () => setCountry(button.dataset.countryTab || 'ALL'));
}

const epgQualitySummary = document.getElementById('epgQualitySummary');
const epgCountrySummary = document.getElementById('epgCountrySummary');
const epgQualitySearch = document.getElementById('epgQualitySearch');
const epgQualityFilter = document.getElementById('epgQualityFilter');
const epgQualityVisibleCount = document.getElementById('epgQualityVisibleCount');
const epgQualityTableBody = document.querySelector('#epgQualityTable tbody');
const epgCollisionTableBody = document.querySelector('#epgCollisionTable tbody');
const epgVerifiedMissingTableBody = document.querySelector('#epgVerifiedMissingTable tbody');
let epgQualityData = null;
let epgQualityRows = [];

function epgQualityBadgeClass(category) {
  if (category === 'Exact tvg-id') return 'verified';
  if (category === 'Alias') return 'tv';
  if (category === 'Guessed' || category === 'EPG unavailable') return 'review';
  if (category === 'Missing') return 'rejected';
  return 'base';
}

function selectedEpgChannels() {
  const channels = Array.isArray(epgQualityData?.channels) ? epgQualityData.channels : [];
  return channels.filter(row => countryMatches(row.country_code));
}

function epgSummaryForRows(rows) {
  const count = category => rows.filter(row => row.quality_category === category).length;
  const expected = rows.filter(row => row.epg_policy === 'expected');
  const complete = expected.filter(row => ['Exact tvg-id', 'Alias', 'Guessed'].includes(row.quality_category));
  return {
    total: rows.length,
    exact: count('Exact tvg-id'),
    alias: count('Alias'),
    guessed: count('Guessed'),
    missing: count('Missing'),
    unavailable: count('EPG unavailable'),
    expected: expected.length,
    complete: complete.length,
    completeness: expected.length ? (100 * complete.length / expected.length) : 0,
  };
}

function renderEpgQuality() {
  if (!epgQualityData) return;
  const rows = selectedEpgChannels();
  const summary = epgSummaryForRows(rows);
  if (epgQualitySummary) {
    epgQualitySummary.innerHTML = `
      <div class="card"><div class="value">${summary.completeness.toFixed(1)}%</div><div class="label">EPG completeness (${summary.complete}/${summary.expected} expected)</div></div>
      <div class="card"><div class="value">${summary.exact}</div><div class="label">Exact tvg-id</div></div>
      <div class="card"><div class="value">${summary.alias}</div><div class="label">Alias</div></div>
      <div class="card"><div class="value">${summary.guessed}</div><div class="label">Guessed</div></div>
      <div class="card"><div class="value">${summary.missing}</div><div class="label">Missing</div></div>
      <div class="card"><div class="value">${summary.unavailable}</div><div class="label">EPG unavailable</div></div>`;
  }

  if (epgCountrySummary) {
    const countries = epgQualityData.countries || {};
    const codes = SUPPORTED_COUNTRIES.filter(code => countries[code]).filter(countryMatches);
    epgCountrySummary.innerHTML = codes.length ? codes.map(code => {
      const info = countries[code] || {};
      return `<div class="card" data-country="${esc(code)}">
        <div class="value">${Number(info.epg_completeness_percent || 0).toFixed(1)}%</div>
        <div class="label">${esc(code)} EPG completeness (${Number(info.epg_expected_with_programmes || 0)}/${Number(info.epg_expected_channels || 0)})</div>
        <div class="detail">Exact ${Number(info.exact_tvg_id || 0)} · Alias ${Number(info.alias || 0)} · Guessed ${Number(info.guessed || 0)} · Missing ${Number(info.missing || 0)} · Unavailable ${Number(info.epg_unavailable || 0)}</div>
      </div>`;
    }).join('') : '<div class="card"><div class="value">—</div><div class="label">Country EPG quality unavailable</div></div>';
  }

  if (epgCollisionTableBody) {
    const collisions = (epgQualityData.tvg_id_collisions || []).filter(item => {
      const channels = Array.isArray(item.channels) ? item.channels : [];
      return selectedCountry === 'ALL' || channels.some(channel => countryMatches(channel.country_code));
    });
    epgCollisionTableBody.innerHTML = collisions.length ? collisions.map(item => {
      const channels = Array.isArray(item.channels) ? item.channels : [];
      return `<tr>
        <td>${esc(item.tvg_id || '—')}</td>
        <td><span class="badge rejected">${Number(item.logical_channel_count || channels.length)} channels</span></td>
        <td>${esc([...new Set(channels.map(row => row.country_code).filter(Boolean))].join(', ') || '—')}</td>
        <td>${channels.map(row => `<div><strong>${esc(row.channel || 'Unnamed')}</strong><div class="detail">${esc(row.key || '')}</div></div>`).join('')}</td>
      </tr>`;
    }).join('') : '<tr><td colspan="4"><span class="badge verified">Clear</span> No unexpected tvg-id collisions.</td></tr>';
  }

  if (epgVerifiedMissingTableBody) {
    const gaps = (epgQualityData.verified_without_epg_mapping || []).filter(row => countryMatches(row.country_code));
    epgVerifiedMissingTableBody.innerHTML = gaps.length ? gaps.map(row => {
      const issue = row.issue === 'missing_tvg_id' ? 'Missing tvg-id' : 'No EPG mapping';
      const link = row.stream_url ? `<a href="${esc(row.stream_url)}" target="_blank" rel="noopener">stream</a>` : '—';
      return `<tr data-country="${esc(row.country_code || 'UNKNOWN')}">
        <td>${esc(row.country_code || 'UNKNOWN')}</td><td class="channel">${esc(row.channel || 'Unnamed')}</td>
        <td>${esc(row.tvg_id || '—')}</td><td><span class="badge rejected">${esc(issue)}</span></td>
        <td><span class="badge ${manualBadgeClass(row.decision)}">${esc(row.decision || 'Unknown')}</span></td><td>${link}</td>
      </tr>`;
    }).join('') : '<tr><td colspan="6"><span class="badge verified">Clear</span> Every verified stable channel has an EPG mapping identity.</td></tr>';
  }
}

function applyEpgQualityFilters() {
  if (!epgQualitySearch || !epgQualityFilter) return;
  const query = epgQualitySearch.value.trim().toLowerCase();
  const category = epgQualityFilter.value;
  let shown = 0;
  for (const row of epgQualityRows) {
    const matchesText = !query || row.innerText.toLowerCase().includes(query);
    const matchesCategory = !category || row.dataset.epgQuality === category;
    const show = countryMatches(row.dataset.country) && matchesText && matchesCategory;
    row.style.display = show ? '' : 'none';
    if (show) shown++;
  }
  if (epgQualityVisibleCount) {
    epgQualityVisibleCount.textContent = `Showing ${shown} of ${epgQualityRows.length} stable logical channels`;
  }
}

function renderEpgQualityTable() {
  if (!epgQualityTableBody || !epgQualityData) return;
  const channels = Array.isArray(epgQualityData.channels) ? epgQualityData.channels : [];
  epgQualityTableBody.innerHTML = channels.length ? channels.map(row => `
    <tr data-country="${esc(row.country_code || 'UNKNOWN')}" data-epg-quality="${esc(row.quality_category || '')}">
      <td>${esc(row.country_code || 'UNKNOWN')}</td><td class="channel">${esc(row.channel || 'Unnamed')}</td>
      <td>${esc(row.tvg_id || '—')}</td><td><span class="badge ${epgQualityBadgeClass(row.quality_category)}">${esc(row.quality_category || 'Unknown')}</span></td>
      <td>${esc(row.match_type || '—')}<div class="detail">${esc(row.provider_xmltv_id || '')}</div></td>
      <td>${esc(row.provider || '—')}</td><td>${esc(row.epg_policy || 'expected')}<div class="detail">${esc(row.epg_policy_reason || '')}</div></td>
      <td>${row.programme_available ? '<span class="badge verified">Available</span>' : '<span class="badge review">Unavailable</span>'}</td>
    </tr>`).join('') : '<tr><td colspan="8">No stable logical channels were reported.</td></tr>';
  epgQualityRows = Array.from(document.querySelectorAll('#epgQualityTable tbody tr[data-epg-quality]'));
  applyEpgQualityFilters();
}

fetch('epg-quality.json', { cache: 'no-store' })
  .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
  .then(data => {
    epgQualityData = data;
    renderEpgQuality();
    renderEpgQualityTable();
  })
  .catch(error => {
    if (epgQualitySummary) epgQualitySummary.innerHTML = `<div class="card"><div class="value">—</div><div class="label">EPG quality unavailable: ${esc(error.message)}</div></div>`;
    if (epgCountrySummary) epgCountrySummary.innerHTML = '<div class="card"><div class="value">—</div><div class="label">Country EPG quality unavailable</div></div>';
    if (epgQualityTableBody) epgQualityTableBody.innerHTML = `<tr><td colspan="8">epg-quality.json could not be loaded: ${esc(error.message)}</td></tr>`;
  });
if (epgQualitySearch) epgQualitySearch.addEventListener('input', applyEpgQualityFilters);
if (epgQualityFilter) epgQualityFilter.addEventListener('change', applyEpgQualityFilters);

const logoQualitySummary = document.getElementById('logoQualitySummary');
const logoCountrySummary = document.getElementById('logoCountrySummary');
const logoQualitySearch = document.getElementById('logoQualitySearch');
const logoQualityFilter = document.getElementById('logoQualityFilter');
const logoQualityVisibleCount = document.getElementById('logoQualityVisibleCount');
const logoQualityTableBody = document.querySelector('#logoQualityTable tbody');
let logoQualityData = null;
let logoQualityRows = [];

function logoBadgeClass(category) {
  if (category === 'Canonical') return 'verified';
  if (category === 'Source fallback') return 'tv';
  if (category === 'Missing') return 'rejected';
  return 'base';
}

function logoSummaryForRows(rows) {
  const canonical = rows.filter(row => row.quality_category === 'Canonical').length;
  const source = rows.filter(row => row.quality_category === 'Source fallback').length;
  const missing = rows.filter(row => row.quality_category === 'Missing').length;
  const total = rows.length;
  return {
    total,
    canonical,
    source,
    missing,
    available: canonical + source,
    availability: total ? 100 * (canonical + source) / total : 0,
    canonicalCoverage: total ? 100 * canonical / total : 0,
  };
}

function renderLogoQuality() {
  if (!logoQualityData) return;
  const channels = Array.isArray(logoQualityData.channels) ? logoQualityData.channels : [];
  const rows = channels.filter(row => countryMatches(row.country_code));
  const summary = logoSummaryForRows(rows);
  if (logoQualitySummary) {
    logoQualitySummary.innerHTML = `
      <div class="card"><div class="value">${summary.availability.toFixed(1)}%</div><div class="label">Logo availability (${summary.available}/${summary.total})</div></div>
      <div class="card"><div class="value">${summary.canonicalCoverage.toFixed(1)}%</div><div class="label">Canonical logo coverage (${summary.canonical}/${summary.total})</div></div>
      <div class="card"><div class="value">${summary.canonical}</div><div class="label">Canonical</div></div>
      <div class="card"><div class="value">${summary.source}</div><div class="label">Source fallback</div></div>
      <div class="card"><div class="value">${summary.missing}</div><div class="label">Missing logos</div></div>`;
  }
  if (logoCountrySummary) {
    const countries = logoQualityData.countries || {};
    const codes = SUPPORTED_COUNTRIES.filter(code => countries[code]).filter(countryMatches);
    logoCountrySummary.innerHTML = codes.length ? codes.map(code => {
      const info = countries[code] || {};
      return `<div class="card" data-country="${esc(code)}">
        <div class="value">${Number(info.logo_availability_percent || 0).toFixed(1)}%</div>
        <div class="label">${esc(code)} logo availability (${Number(info.with_logo || 0)}/${Number(info.stable_logical_channels || 0)})</div>
        <div class="detail">Canonical ${Number(info.canonical_logo || 0)} · Source fallback ${Number(info.source_fallback || 0)} · Missing ${Number(info.missing_logo || 0)} · Canonical coverage ${Number(info.canonical_logo_coverage_percent || 0).toFixed(1)}%</div>
      </div>`;
    }).join('') : '<div class="card"><div class="value">—</div><div class="label">Country logo coverage unavailable</div></div>';
  }
}

function renderLogoQualityTable() {
  if (!logoQualityTableBody || !logoQualityData) return;
  const channels = Array.isArray(logoQualityData.channels) ? logoQualityData.channels : [];
  logoQualityTableBody.innerHTML = channels.length ? channels.map(row => {
    const logo = String(row.logo || '').trim();
    const preview = logo.startsWith('https://')
      ? `<img src="${esc(logo)}" alt="" loading="lazy" style="max-width:80px;max-height:38px;object-fit:contain;vertical-align:middle">`
      : '';
    const link = logo ? `<div><a href="${esc(logo)}" target="_blank" rel="noopener">logo URL</a></div>` : '—';
    return `<tr data-country="${esc(row.country_code || 'UNKNOWN')}" data-logo-quality="${esc(row.quality_category || '')}">
      <td>${esc(row.country_code || 'UNKNOWN')}</td><td class="channel">${esc(row.channel || 'Unnamed')}</td>
      <td><span class="badge ${logoBadgeClass(row.quality_category)}">${esc(row.quality_category || 'Unknown')}</span></td>
      <td>${preview}${link}</td><td>${esc(row.match_type || '—')}<div class="detail">${esc(row.tvg_id || row.canonical_id || '')}</div></td>
      <td>${esc(row.provenance || '—')}<div class="detail">${esc(row.note || '')}</div></td>
    </tr>`;
  }).join('') : '<tr><td colspan="6">No stable logical channels were reported.</td></tr>';
  logoQualityRows = Array.from(document.querySelectorAll('#logoQualityTable tbody tr[data-logo-quality]'));
  applyLogoQualityFilters();
}

function applyLogoQualityFilters() {
  if (!logoQualitySearch || !logoQualityFilter) return;
  const query = logoQualitySearch.value.trim().toLowerCase();
  const category = logoQualityFilter.value;
  let shown = 0;
  for (const row of logoQualityRows) {
    const matchesText = !query || row.innerText.toLowerCase().includes(query);
    const matchesCategory = !category || row.dataset.logoQuality === category;
    const show = countryMatches(row.dataset.country) && matchesText && matchesCategory;
    row.style.display = show ? '' : 'none';
    if (show) shown++;
  }
  if (logoQualityVisibleCount) {
    logoQualityVisibleCount.textContent = `Showing ${shown} of ${logoQualityRows.length} stable logical channels`;
  }
}

fetch('logo-quality.json', { cache: 'no-store' })
  .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
  .then(data => {
    logoQualityData = data;
    renderLogoQuality();
    renderLogoQualityTable();
  })
  .catch(error => {
    if (logoQualitySummary) logoQualitySummary.innerHTML = `<div class="card"><div class="value">—</div><div class="label">Logo quality unavailable: ${esc(error.message)}</div></div>`;
    if (logoCountrySummary) logoCountrySummary.innerHTML = '<div class="card"><div class="value">—</div><div class="label">Country logo coverage unavailable</div></div>';
    if (logoQualityTableBody) logoQualityTableBody.innerHTML = `<tr><td colspan="6">logo-quality.json could not be loaded: ${esc(error.message)}</td></tr>`;
  });
if (logoQualitySearch) logoQualitySearch.addEventListener('input', applyLogoQualityFilters);
if (logoQualityFilter) logoQualityFilter.addEventListener('change', applyLogoQualityFilters);

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

// Source concentration -----------------------------------------------------
const sourceConcentrationSummary = document.getElementById('sourceConcentrationSummary');
const sourceConcentrationCountrySummary = document.getElementById('sourceConcentrationCountrySummary');
const sourceConcentrationVisibleCount = document.getElementById('sourceConcentrationVisibleCount');
const sourceConcentrationTableBody = document.querySelector('#sourceConcentrationTable tbody');
let sourceConcentrationData = null;

function concentrationBadgeClass(risk) {
  if (risk === 'critical' || risk === 'high') return 'rejected';
  if (risk === 'warning') return 'review';
  return 'base';
}

function sourceTypeShortLabel(sourceType) {
  if (sourceType === 'Official broadcaster') return 'Official';
  if (sourceType === 'Broadcaster CDN') return 'Broadcaster CDN';
  if (sourceType === 'Third-party relay') return 'Relay';
  return 'Unclassified';
}

function renderSourceConcentration() {
  if (!sourceConcentrationData) return;
  const data = sourceConcentrationData;
  const countries = data.countries || {};
  const summary = data.summary || {};
  const selectedCodes = SUPPORTED_COUNTRIES
    .filter(code => countries[code])
    .filter(countryMatches);

  const visibleCountries = selectedCountry === 'ALL'
    ? selectedCodes
    : selectedCodes.filter(code => code === selectedCountry);
  const visibleTotal = visibleCountries.reduce((sum, code) => sum + Number(countries[code]?.stable_channels || 0), 0);
  const typeCounts = {
    'Official broadcaster': 0,
    'Broadcaster CDN': 0,
    'Third-party relay': 0,
    'Unclassified': 0,
  };
  for (const code of visibleCountries) {
    for (const row of countries[code]?.source_types || []) {
      typeCounts[row.source_type] = (typeCounts[row.source_type] || 0) + Number(row.channels || 0);
    }
  }
  const visibleFlags = (data.flags || []).filter(flag => countryMatches(flag.country_code));
  const pct = value => visibleTotal ? (100 * Number(value || 0) / visibleTotal).toFixed(1) : '0.0';

  if (sourceConcentrationSummary) {
    sourceConcentrationSummary.innerHTML = `
      <div class="card"><div class="value">${visibleTotal}</div><div class="label">Stable channels measured</div></div>
      <div class="card"><div class="value">${typeCounts['Official broadcaster']}</div><div class="label">Official broadcaster (${pct(typeCounts['Official broadcaster'])}%)</div></div>
      <div class="card"><div class="value">${typeCounts['Broadcaster CDN']}</div><div class="label">Broadcaster CDN (${pct(typeCounts['Broadcaster CDN'])}%)</div></div>
      <div class="card"><div class="value">${typeCounts['Third-party relay']}</div><div class="label">Third-party relay (${pct(typeCounts['Third-party relay'])}%)</div></div>
      <div class="card"><div class="value">${typeCounts.Unclassified}</div><div class="label">Unclassified (${pct(typeCounts.Unclassified)}%)</div></div>
      <div class="card"><div class="value">${visibleFlags.length}</div><div class="label">Relay concentration flags</div></div>`;
  }

  if (sourceConcentrationCountrySummary) {
    sourceConcentrationCountrySummary.innerHTML = visibleCountries.map(code => {
      const info = countries[code] || {};
      const counts = Object.fromEntries((info.source_types || []).map(row => [row.source_type, row]));
      const relay = counts['Third-party relay'] || { channels: 0, percent: 0 };
      const cdn = counts['Broadcaster CDN'] || { channels: 0, percent: 0 };
      const official = counts['Official broadcaster'] || { channels: 0, percent: 0 };
      const unknown = counts.Unclassified || { channels: 0, percent: 0 };
      return `<div class="card" data-country="${esc(code)}">
        <div class="value">${Number(relay.percent || 0).toFixed(1)}%</div>
        <div class="label">${code} third-party relay (${Number(relay.channels || 0)}/${Number(info.stable_channels || 0)})</div>
        <div class="detail">Official ${official.channels || 0} · CDN ${cdn.channels || 0} · Unclassified ${unknown.channels || 0}</div>
      </div>`;
    }).join('');
  }

  const hostRows = [];
  for (const code of visibleCountries) {
    for (const host of countries[code]?.hostnames || []) {
      hostRows.push({ ...host, country_code: code });
    }
  }
  if (sourceConcentrationTableBody) {
    sourceConcentrationTableBody.innerHTML = hostRows.map(host => {
      const typeDetail = Object.entries(host.source_types || {})
        .map(([type, count]) => `${sourceTypeShortLabel(type)} ${count}`)
        .join(' · ');
      const channelNames = Array.isArray(host.channel_names) ? host.channel_names : [];
      const shown = channelNames.slice(0, 8).join(', ');
      const extra = channelNames.length > 8 ? ` +${channelNames.length - 8} more` : '';
      const risk = String(host.risk || 'none');
      return `<tr data-country="${esc(host.country_code)}">
        <td><strong>${esc(host.country_code)}</strong></td>
        <td>${esc(host.hostname)}</td>
        <td>${esc(host.source_type || 'Unclassified')}<div class="detail">${esc(typeDetail)}</div></td>
        <td>${Number(host.channels || 0)}</td>
        <td>${Number(host.country_percent || 0).toFixed(1)}%</td>
        <td>${Number(host.third_party_relay_channels || 0)} (${Number(host.third_party_relay_percent || 0).toFixed(1)}%)</td>
        <td><span class="badge ${concentrationBadgeClass(risk)}">${esc(risk === 'none' ? 'OK' : risk.toUpperCase())}</span></td>
        <td class="detail">${esc(shown + extra)}</td>
      </tr>`;
    }).join('') || '<tr><td colspan="8" class="muted">No source concentration data for this country.</td></tr>';
  }
  if (sourceConcentrationVisibleCount) {
    sourceConcentrationVisibleCount.textContent = `Showing ${hostRows.length} hostname dependencies · ${visibleFlags.length} relay concentration flags`;
  }
}

fetch('source-concentration.json', { cache: 'no-store' })
  .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
  .then(data => { sourceConcentrationData = data; renderSourceConcentration(); })
  .catch(error => {
    if (sourceConcentrationSummary) sourceConcentrationSummary.innerHTML = '<div class="card"><div class="value">—</div><div class="label">Source concentration unavailable</div></div>';
    if (sourceConcentrationTableBody) sourceConcentrationTableBody.innerHTML = `<tr><td colspan="8">source-concentration.json could not be loaded: ${esc(error.message)}</td></tr>`;
    if (sourceConcentrationVisibleCount) sourceConcentrationVisibleCount.textContent = 'source-concentration.json is not available yet.';
  });

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
    if (healthTableBody) healthTableBody.innerHTML = `<tr><td colspan="8">Automated stream health data could not be loaded: ${esc(error.message)}</td></tr>`;
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

const testedStatuses = new Set(['works', 'works_with_warning', 'loads', 'mrl_error', 'format_error', 'generic_error', 'wrong_language']);
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

// Top-level next-work panel ------------------------------------------------
const nextWorkSummary = document.getElementById('nextWorkSummary');
const nextWorkList = document.getElementById('nextWorkList');
const nextWorkNote = document.getElementById('nextWorkNote');

function shortMissingAction(row) {
  const workType = String(row.work_type || '').trim();
  if (workType === 'Finish compatibility') return 'finish compatibility';
  if (workType === 'Test candidates') return 'test candidate';
  if (workType === 'Find first candidate') return 'find first candidate';
  if (workType === 'Hunt new source') return 'find replacement feed';
  return String(row.next_action || 'review').trim();
}

function shortAttentionAction(signal) {
  const category = String(signal?.category || '');
  return ({
    stream_manual_retest: 'manual VLC + Samsung retest',
    stream_failure: 'check stream failure',
    upstream_missing: 'find replacement feed',
    epg_missing_id: 'add tvg-id',
    epg_unmapped: 'add EPG mapping',
    epg_mapped_empty: 'fix empty EPG mapping',
    manual_stale: 'repeat manual playback test',
    manual_date_missing: 'record a fresh manual test',
  })[category] || String(signal?.action || 'review').trim();
}

function nextWorkStatusWeight(status) {
  return ({ PARTIAL: 40, 'CANDIDATES TO TEST': 30, 'NO WORKING FEED': 20, 'NOT RESEARCHED': 10 })[status] || 0;
}

function renderNextWorkPanel() {
  if (!nextWorkSummary || !nextWorkList) return;

  Promise.all([
    fetch('attention.json', { cache: 'no-store' }).then(r => { if (!r.ok) throw new Error(`attention.json HTTP ${r.status}`); return r.json(); }),
    fetch('health.json', { cache: 'no-store' }).then(r => { if (!r.ok) throw new Error(`health.json HTTP ${r.status}`); return r.json(); }),
    fetch('missing.csv', { cache: 'no-store' }).then(r => { if (!r.ok) throw new Error(`missing.csv HTTP ${r.status}`); return r.text(); }),
  ]).then(([attention, health, missingText]) => {
    const missing = parseCsv(missingText);
    const attentionItems = Array.isArray(attention.items) ? attention.items : [];
    const healthStreams = Array.isArray(health.streams) ? health.streams : [];

    const streamFailures = healthStreams.filter(item => item.actionable_failure === true).length;
    const p1Missing = missing.filter(row => row.priority === 'P1').length;
    const p2Candidates = missing.filter(row =>
      row.priority === 'P2'
      && Number(row.current_candidates || 0) > 0
      && ['PARTIAL', 'CANDIDATES TO TEST'].includes(String(row.status || ''))
    ).length;
    const expectedEpgGaps = attentionItems.filter(item =>
      (item.signals || []).some(signal => String(signal.category || '').startsWith('epg_'))
    ).length;

    nextWorkSummary.innerHTML = `
      <div class="card"><div class="value">${streamFailures}</div><div class="label">🔴 Stream failures</div></div>
      <div class="card"><div class="value">${p1Missing}</div><div class="label">🟠 P1 channels missing</div></div>
      <div class="card"><div class="value">${p2Candidates}</div><div class="label">🟡 P2 candidates</div></div>
      <div class="card"><div class="value">${expectedEpgGaps}</div><div class="label">🟡 Expected EPG gaps</div></div>`;

    const recommendations = [];
    for (const item of attentionItems) {
      const signals = Array.isArray(item.signals) ? item.signals : [];
      const urgent = signals.find(signal => ['stream_manual_retest', 'upstream_missing'].includes(signal.category))
        || signals.find(signal => signal.category === 'stream_failure');
      if (!urgent) continue;
      recommendations.push({
        key: `${normalizedCountry(item.country)}\u0000${String(item.channel || '').trim().toLowerCase()}`,
        score: 500 + Number(item.priority_score || 0),
        country: normalizedCountry(item.country),
        channel: item.channel || 'Unnamed channel',
        action: shortAttentionAction(urgent),
      });
    }

    for (const row of missing) {
      const priority = String(row.priority || 'P3');
      if (priority !== 'P1' && priority !== 'P2') continue;
      recommendations.push({
        key: candidateKey(row),
        score: (priority === 'P1' ? 400 : 300) + nextWorkStatusWeight(row.status),
        country: normalizedCountry(row.country),
        channel: row.channel || 'Unnamed channel',
        action: shortMissingAction(row),
      });
    }

    for (const item of attentionItems) {
      const epgSignal = (item.signals || []).find(signal => String(signal.category || '').startsWith('epg_'));
      if (!epgSignal) continue;
      recommendations.push({
        key: `${normalizedCountry(item.country)}\u0000${String(item.channel || '').trim().toLowerCase()}`,
        score: 200 + Number(item.priority_score || 0),
        country: normalizedCountry(item.country),
        channel: item.channel || 'Unnamed channel',
        action: shortAttentionAction(epgSignal),
      });
    }

    recommendations.sort((a, b) => b.score - a.score
      || String(a.country).localeCompare(String(b.country))
      || String(a.channel).localeCompare(String(b.channel)));

    const seen = new Set();
    const top = [];
    for (const item of recommendations) {
      if (seen.has(item.key)) continue;
      seen.add(item.key);
      top.push(item);
      if (top.length === 8) break;
    }

    nextWorkList.innerHTML = top.length
      ? top.map(item => `<li><strong>${esc(item.country)} ${esc(item.channel)}</strong> — ${esc(item.action)}</li>`).join('')
      : '<li><span class="badge verified">Clear</span> No high-value next actions are currently queued.</li>';
    if (nextWorkNote) nextWorkNote.textContent = 'Recommendations rank urgent stream problems first, then P1/P2 research work, then expected EPG gaps.';
  }).catch(error => {
    nextWorkSummary.innerHTML = '<div class="card"><div class="value">—</div><div class="label">Priority summary unavailable</div></div>';
    nextWorkList.innerHTML = `<li class="muted">Could not load the generated priority data: ${esc(error.message)}</li>`;
    if (nextWorkNote) nextWorkNote.textContent = 'The detailed dashboard sections below remain available independently.';
  });
}

renderNextWorkPanel();