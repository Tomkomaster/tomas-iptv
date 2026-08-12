const epgCountrySummary = document.getElementById('epgCountrySummary');

function renderEpgCountryCoverage(data) {
  const countries = data.countries || {};
  const codes = ['HU', 'SK', 'CZ'].filter(code => countries[code]);
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
      <div class="card">
        <div class="value">${actual}%</div>
        <div class="label">${code} programmes (${populated}/${total})</div>
        <div class="detail">Mapped: ${mapped}/${total} (${mappedPct}%)</div>
      </div>
    `;
  }).join('');
}

fetch('epg-health.json', { cache: 'no-store' })
  .then(response => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then(renderEpgCountryCoverage)
  .catch(error => {
    epgCountrySummary.innerHTML = `<div class="card"><div class="value">—</div><div class="label">EPG coverage unavailable: ${attentionEsc(error.message)}</div></div>`;
  });

const attentionSearch = document.getElementById('attentionSearch');
const attentionSeverityFilter = document.getElementById('attentionSeverityFilter');
const attentionCategoryFilter = document.getElementById('attentionCategoryFilter');
const attentionVisibleCount = document.getElementById('attentionVisibleCount');
const attentionSummary = document.getElementById('attentionSummary');
const attentionTableBody = document.querySelector('#attentionTable tbody');
let attentionRows = [];

function attentionEsc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function applyAttentionFilters() {
  const q = attentionSearch.value.trim().toLowerCase();
  const severity = attentionSeverityFilter.value;
  const category = attentionCategoryFilter.value;
  let shown = 0;

  for (const row of attentionRows) {
    const categories = (row.dataset.attentionCategories || '')
      .split(',')
      .filter(Boolean);
    const matchesText = !q || row.innerText.toLowerCase().includes(q);
    const matchesSeverity = !severity || row.dataset.attentionSeverity === severity;
    const matchesCategory = !category
      || (category === 'stream' && categories.some(value => value.startsWith('stream_')))
      || (category === 'manual' && categories.some(value => value.startsWith('manual_')))
      || (category === 'epg' && categories.some(value => value.startsWith('epg_')))
      || categories.includes(category);
    const show = matchesText && matchesSeverity && matchesCategory;
    row.style.display = show ? '' : 'none';
    if (show) shown++;
  }

  attentionVisibleCount.textContent = `Showing ${shown} of ${attentionRows.length} channels needing attention`;
}

function attentionBadgeClass(severity) {
  if (severity === 'critical' || severity === 'high') return 'rejected';
  if (severity === 'medium') return 'review';
  return 'base';
}

function manualBadgeClass(status) {
  if (status === 'Verified') return 'verified';
  if (status === 'TV verified') return 'tv';
  if (status === 'PC only') return 'pc';
  if (status === 'Rejected') return 'rejected';
  if (status === 'Needs review') return 'review';
  return 'base';
}

function autoBadgeClass(status) {
  if (status === 'Online') return 'verified';
  if (status === 'Redirected') return 'tv';
  if (status === 'Slow startup') return 'review';
  if (status === 'Unknown') return 'base';
  return 'rejected';
}

function epgBadgeClass(status) {
  if (status === 'Programme data') return 'verified';
  if (status === 'Unknown') return 'base';
  return 'review';
}

function renderAttention(data) {
  const summary = data.summary || {};
  const items = Array.isArray(data.items) ? data.items : [];
  const staleDays = data.settings?.manual_stale_days ?? 30;

  attentionSummary.innerHTML = `
    <div class="card"><div class="value">${summary.items ?? 0}</div><div class="label">Channels needing attention</div></div>
    <div class="card"><div class="value">${summary.critical ?? 0}</div><div class="label">Critical</div></div>
    <div class="card"><div class="value">${summary.high ?? 0}</div><div class="label">High</div></div>
    <div class="card"><div class="value">${summary.medium ?? 0}</div><div class="label">Medium</div></div>
    <div class="card"><div class="value">${summary.low ?? 0}</div><div class="label">Low</div></div>
    <div class="card"><div class="value">${staleDays} d</div><div class="label">Manual-test age threshold</div></div>
    <div class="card"><div class="value">${attentionEsc(data.generated_at || '—')}</div><div class="label">Queue generated</div></div>
  `;

  if (!items.length) {
    attentionTableBody.innerHTML = '<tr><td colspan="9"><span class="badge verified">Clear</span> No current attention items.</td></tr>';
    attentionRows = [];
    attentionVisibleCount.textContent = 'No channels currently need attention.';
    return;
  }

  attentionTableBody.innerHTML = items.map(item => {
    const signals = Array.isArray(item.signals) ? item.signals : [];
    const categories = signals.map(signal => signal.category || '').filter(Boolean);
    const reasons = signals.map(signal => `
      <div>
        <span class="badge ${attentionBadgeClass(signal.severity)}">${attentionEsc(signal.label || signal.category || 'Attention')}</span>
        <div class="detail">${attentionEsc(signal.detail || '')}</div>
      </div>
    `).join('');
    const actions = [...new Set(signals.map(signal => signal.action).filter(Boolean))];
    const actionHtml = actions.map(action => `<div class="detail">${attentionEsc(action)}</div>`).join('');
    const streamLink = item.stream_url
      ? `<a href="${attentionEsc(item.stream_url)}" target="_blank" rel="noopener">stream</a>`
      : '—';
    const autoSuffix = Number(item.consecutive_failures || 0) > 0
      ? ` ×${Number(item.consecutive_failures)}`
      : '';

    return `
      <tr data-attention-severity="${attentionEsc(item.severity)}" data-attention-categories="${attentionEsc(categories.join(','))}">
        <td><span class="badge ${attentionBadgeClass(item.severity)}">${attentionEsc(String(item.severity || 'low').toUpperCase())}</span><div class="detail">Score ${Number(item.priority_score || 0)}</div></td>
        <td class="channel">${attentionEsc(item.channel)}</td>
        <td>${reasons || '—'}</td>
        <td>${actionHtml || '—'}</td>
        <td><span class="badge ${manualBadgeClass(item.manual_status)}">${attentionEsc(item.manual_status || 'Unknown')}</span></td>
        <td><span class="badge ${autoBadgeClass(item.auto_status)}">${attentionEsc(item.auto_status || 'Unknown')}${autoSuffix}</span></td>
        <td><span class="badge ${epgBadgeClass(item.epg_status)}">${attentionEsc(item.epg_status || 'Unknown')}</span></td>
        <td>${attentionEsc(item.tested_on || '—')}</td>
        <td class="url">${streamLink}</td>
      </tr>
    `;
  }).join('');

  attentionRows = Array.from(document.querySelectorAll('#attentionTable tbody tr'));
  applyAttentionFilters();
}

fetch('attention.json', { cache: 'no-store' })
  .then(response => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then(renderAttention)
  .catch(error => {
    attentionSummary.innerHTML = '<div class="card"><div class="value">—</div><div class="label">Attention data unavailable</div></div>';
    attentionTableBody.innerHTML = `<tr><td colspan="9">attention.json could not be loaded: ${attentionEsc(error.message)}</td></tr>`;
    attentionRows = [];
    attentionVisibleCount.textContent = 'attention.json is not available yet.';
  });

attentionSearch.addEventListener('input', applyAttentionFilters);
attentionSeverityFilter.addEventListener('change', applyAttentionFilters);
attentionCategoryFilter.addEventListener('change', applyAttentionFilters);

const healthSearch = document.getElementById('healthSearch');
const healthStatusFilter = document.getElementById('healthStatusFilter');
const healthVisibleCount = document.getElementById('healthVisibleCount');
const healthSummary = document.getElementById('healthSummary');
const healthTableBody = document.querySelector('#healthTable tbody');
let healthRows = [];

function healthEsc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function applyHealthFilters() {
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
    const show = matchesText && matchesStatus;
    row.style.display = show ? '' : 'none';
    if (show) shown++;
  }

  healthVisibleCount.textContent = `Showing ${shown} of ${healthRows.length} stable streams`;
}

function renderHealth(data) {
  const summary = data.summary || {};
  const statusCounts = summary.status_counts || {};
  const streams = Array.isArray(data.streams) ? data.streams : [];

  healthSummary.innerHTML = `
    <div class="card"><div class="value">${summary.playable ?? 0}</div><div class="label">Playable now</div></div>
    <div class="card"><div class="value">${statusCounts['Online'] ?? 0}</div><div class="label">Online</div></div>
    <div class="card"><div class="value">${statusCounts['Redirected'] ?? 0}</div><div class="label">Redirected</div></div>
    <div class="card"><div class="value">${statusCounts['Slow startup'] ?? 0}</div><div class="label">Slow startup</div></div>
    <div class="card"><div class="value">${summary.failed ?? 0}</div><div class="label">Actionable failures</div></div>
    <div class="card"><div class="value">${summary.informational_unavailable ?? 0}</div><div class="label">Event-based inactive</div></div>
    <div class="card"><div class="value">${summary.needs_manual_retest ?? 0}</div><div class="label">Needs manual retest</div></div>
    <div class="card"><div class="value">${healthEsc(data.generated_at || '—')}</div><div class="label">Last automated check</div></div>
  `;

  healthTableBody.innerHTML = streams.map(item => {
    const manualClass = item.manual_status === 'Samsung + VLC'
      ? 'verified'
      : (item.manual_status === 'Samsung' ? 'tv' : 'base');
    const autoClass = item.manual_retest_recommended
      ? 'rejected'
      : (item.attention === 'informational'
          ? 'base'
          : (item.status === 'Online'
              ? 'verified'
              : (item.status === 'Redirected' ? 'tv' : 'review')));
    const failureSuffix = item.actionable_failure
      ? ` ×${item.consecutive_failures || 1}`
      : '';
    const startup = Number.isFinite(Number(item.startup_seconds))
      ? `${Number(item.startup_seconds).toFixed(2)} s`
      : '—';
    const detail = item.manual_retest_recommended
      ? `${item.detail || ''} Manual VLC + Samsung retest recommended.`
      : (item.detail || '—');

    return `
      <tr data-health-status="${healthEsc(item.status)}" data-health-success="${item.success ? 'yes' : 'no'}" data-health-actionable="${item.actionable_failure ? 'yes' : 'no'}" data-health-attention="${healthEsc(item.attention)}">
        <td class="channel">${healthEsc(item.channel)}</td>
        <td><span class="badge ${manualClass}">${healthEsc(item.manual_status || 'Unknown')}</span></td>
        <td><span class="badge ${autoClass}">${healthEsc(item.status)}${failureSuffix}</span></td>
        <td>${item.consecutive_failures || 0}</td>
        <td>${healthEsc(startup)}</td>
        <td>${healthEsc(item.checked_at || data.generated_at || '—')}</td>
        <td><div class="detail">${healthEsc(detail)}</div></td>
        <td class="url"><a href="${healthEsc(item.stream_url)}" target="_blank" rel="noopener">stream</a></td>
      </tr>
    `;
  }).join('');

  healthRows = Array.from(document.querySelectorAll('#healthTable tbody tr'));
  applyHealthFilters();
}

fetch('health.json', { cache: 'no-store' })
  .then(response => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then(renderHealth)
  .catch(error => {
    healthSummary.innerHTML = '<div class="card"><div class="value">—</div><div class="label">Health data unavailable</div></div>';
    healthTableBody.innerHTML = `<tr><td colspan="8">Automated health data could not be loaded: ${healthEsc(error.message)}</td></tr>`;
    healthRows = [];
    healthVisibleCount.textContent = 'health.json is not available yet.';
  });

healthSearch.addEventListener('input', applyHealthFilters);
healthStatusFilter.addEventListener('change', applyHealthFilters);

const search = document.getElementById('search');
const sourceFilter = document.getElementById('sourceFilter');
const statusFilter = document.getElementById('statusFilter');
const rows = Array.from(document.querySelectorAll('#channels tbody tr'));
const visibleCount = document.getElementById('visibleCount');

function applyFilters() {
  const q = search.value.trim().toLowerCase();
  const source = sourceFilter.value;
  const status = statusFilter.value;
  let shown = 0;

  for (const row of rows) {
    const matchesText = !q || row.innerText.toLowerCase().includes(q);
    const matchesSource = !source || row.dataset.source === source;
    const matchesStatus = !status || row.dataset.status === status;
    const show = matchesText && matchesSource && matchesStatus;
    row.style.display = show ? '' : 'none';
    if (show) shown++;
  }

  visibleCount.textContent = `Showing ${shown} of ${rows.length} stream entries`;
}

const auditSearch = document.getElementById('auditSearch');
const auditDecisionFilter = document.getElementById('auditDecisionFilter');
const auditVlcFilter = document.getElementById('auditVlcFilter');
const auditSamsungFilter = document.getElementById('auditSamsungFilter');
const auditRows = Array.from(document.querySelectorAll('#auditTable tbody tr'));
const auditVisibleCount = document.getElementById('auditVisibleCount');

function applyAuditFilters() {
  const q = auditSearch.value.trim().toLowerCase();
  const decision = auditDecisionFilter.value;
  const vlc = auditVlcFilter.value;
  const samsung = auditSamsungFilter.value;
  let shown = 0;

  for (const row of auditRows) {
    const matchesText = !q || row.innerText.toLowerCase().includes(q);
    const matchesDecision = !decision || row.dataset.auditDecision === decision;
    const matchesVlc = !vlc || row.dataset.auditVlc === vlc;
    const matchesSamsung = !samsung || row.dataset.auditSamsung === samsung;
    const show = matchesText && matchesDecision && matchesVlc && matchesSamsung;
    row.style.display = show ? '' : 'none';
    if (show) shown++;
  }

  auditVisibleCount.textContent = `Showing ${shown} of ${auditRows.length} manually reviewed/candidate channels`;
}

auditSearch.addEventListener('input', applyAuditFilters);
auditDecisionFilter.addEventListener('change', applyAuditFilters);
auditVlcFilter.addEventListener('change', applyAuditFilters);
auditSamsungFilter.addEventListener('change', applyAuditFilters);
applyAuditFilters();

search.addEventListener('input', applyFilters);
sourceFilter.addEventListener('change', applyFilters);
statusFilter.addEventListener('change', applyFilters);
applyFilters();
