from pathlib import Path


path = Path("build.py")
text = path.read_text(encoding="utf-8")

link_old = '''    <a href="audit.csv">Manual verification (CSV)</a>
    <a href="health.json">Automated stream health (JSON)</a>'''
link_new = '''    <a href="audit.csv">Manual verification (CSV)</a>
    <a href="attention.json">Needs attention (JSON)</a>
    <a href="health.json">Automated stream health (JSON)</a>'''
if link_old not in text:
    raise SystemExit("attention dashboard link anchor not found")
text = text.replace(link_old, link_new, 1)

section_old = '''  {audit_warning_html}

  <h2>Automated stream health</h2>'''
section_new = '''  {audit_warning_html}

  <h2>Needs attention</h2>
  <p class="muted">
    One prioritized advisory queue combining automated stream failures, old manual
    VLC + Samsung tests, EPG gaps, and previously TV-safe streams that disappeared
    from all current source inputs. A channel appears once even when several reasons
    apply. Automated results remain advisory and never change audit.json or stable
    playlist membership by themselves.
  </p>

  <div id="attentionSummary" class="audit-summary">
    <div class="card"><div class="value">…</div><div class="label">Loading attention queue</div></div>
  </div>

  <div class="controls">
    <input id="attentionSearch" type="search" placeholder="Search needs attention...">
    <select id="attentionSeverityFilter">
      <option value="">All priorities</option>
      <option value="critical">Critical</option>
      <option value="high">High</option>
      <option value="medium">Medium</option>
      <option value="low">Low</option>
    </select>
    <select id="attentionCategoryFilter">
      <option value="">All reasons</option>
      <option value="stream">Stream health</option>
      <option value="manual">Manual testing</option>
      <option value="epg">EPG</option>
      <option value="upstream_missing">Upstream disappeared</option>
    </select>
  </div>
  <p id="attentionVisibleCount" class="muted">Loading attention.json…</p>

  <div class="table-wrap">
    <table id="attentionTable">
      <thead>
        <tr>
          <th>Priority</th>
          <th>Channel</th>
          <th>Why</th>
          <th>Recommended action</th>
          <th>Manual</th>
          <th>Auto health</th>
          <th>EPG</th>
          <th>Last manual</th>
          <th>URL</th>
        </tr>
      </thead>
      <tbody>
        <tr><td colspan="9" class="muted">Loading prioritized attention queue…</td></tr>
      </tbody>
    </table>
  </div>

  <h2>Automated stream health</h2>'''
if section_old not in text:
    raise SystemExit("attention dashboard section anchor not found")
text = text.replace(section_old, section_new, 1)

script_old = '''<script>
const healthSearch = document.getElementById('healthSearch');'''
script_new = '''<script>
const attentionSearch = document.getElementById('attentionSearch');
const attentionSeverityFilter = document.getElementById('attentionSeverityFilter');
const attentionCategoryFilter = document.getElementById('attentionCategoryFilter');
const attentionVisibleCount = document.getElementById('attentionVisibleCount');
const attentionSummary = document.getElementById('attentionSummary');
const attentionTableBody = document.querySelector('#attentionTable tbody');
let attentionRows = [];

function attentionEsc(value) {{
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}}

function applyAttentionFilters() {{
  const q = attentionSearch.value.trim().toLowerCase();
  const severity = attentionSeverityFilter.value;
  const category = attentionCategoryFilter.value;
  let shown = 0;

  for (const row of attentionRows) {{
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
  }}

  attentionVisibleCount.textContent = `Showing ${{shown}} of ${{attentionRows.length}} channels needing attention`;
}}

function attentionBadgeClass(severity) {{
  if (severity === 'critical' || severity === 'high') return 'rejected';
  if (severity === 'medium') return 'review';
  return 'base';
}}

function manualBadgeClass(status) {{
  if (status === 'Verified') return 'verified';
  if (status === 'TV verified') return 'tv';
  if (status === 'PC only') return 'pc';
  if (status === 'Rejected') return 'rejected';
  if (status === 'Needs review') return 'review';
  return 'base';
}}

function autoBadgeClass(status) {{
  if (status === 'Online') return 'verified';
  if (status === 'Redirected') return 'tv';
  if (status === 'Slow startup') return 'review';
  if (status === 'Unknown') return 'base';
  return 'rejected';
}}

function epgBadgeClass(status) {{
  if (status === 'Programme data') return 'verified';
  if (status === 'Unknown') return 'base';
  return 'review';
}}

function renderAttention(data) {{
  const summary = data.summary || {{}};
  const items = Array.isArray(data.items) ? data.items : [];
  const staleDays = data.settings?.manual_stale_days ?? 30;

  attentionSummary.innerHTML = `
    <div class="card"><div class="value">${{summary.items ?? 0}}</div><div class="label">Channels needing attention</div></div>
    <div class="card"><div class="value">${{summary.critical ?? 0}}</div><div class="label">Critical</div></div>
    <div class="card"><div class="value">${{summary.high ?? 0}}</div><div class="label">High</div></div>
    <div class="card"><div class="value">${{summary.medium ?? 0}}</div><div class="label">Medium</div></div>
    <div class="card"><div class="value">${{summary.low ?? 0}}</div><div class="label">Low</div></div>
    <div class="card"><div class="value">${{staleDays}} d</div><div class="label">Manual-test age threshold</div></div>
    <div class="card"><div class="value">${{attentionEsc(data.generated_at || '—')}}</div><div class="label">Queue generated</div></div>
  `;

  if (!items.length) {{
    attentionTableBody.innerHTML = '<tr><td colspan="9"><span class="badge verified">Clear</span> No current attention items.</td></tr>';
    attentionRows = [];
    attentionVisibleCount.textContent = 'No channels currently need attention.';
    return;
  }}

  attentionTableBody.innerHTML = items.map(item => {{
    const signals = Array.isArray(item.signals) ? item.signals : [];
    const categories = signals.map(signal => signal.category || '').filter(Boolean);
    const reasons = signals.map(signal => `
      <div>
        <span class="badge ${{attentionBadgeClass(signal.severity)}}">${{attentionEsc(signal.label || signal.category || 'Attention')}}</span>
        <div class="detail">${{attentionEsc(signal.detail || '')}}</div>
      </div>
    `).join('');
    const actions = [...new Set(signals.map(signal => signal.action).filter(Boolean))];
    const actionHtml = actions.map(action => `<div class="detail">${{attentionEsc(action)}}</div>`).join('');
    const streamLink = item.stream_url
      ? `<a href="${{attentionEsc(item.stream_url)}}" target="_blank" rel="noopener">stream</a>`
      : '—';
    const autoSuffix = Number(item.consecutive_failures || 0) > 0
      ? ` ×${{Number(item.consecutive_failures)}}`
      : '';

    return `
      <tr data-attention-severity="${{attentionEsc(item.severity)}}" data-attention-categories="${{attentionEsc(categories.join(','))}}">
        <td><span class="badge ${{attentionBadgeClass(item.severity)}}">${{attentionEsc(String(item.severity || 'low').toUpperCase())}}</span><div class="detail">Score ${{Number(item.priority_score || 0)}}</div></td>
        <td class="channel">${{attentionEsc(item.channel)}}</td>
        <td>${{reasons || '—'}}</td>
        <td>${{actionHtml || '—'}}</td>
        <td><span class="badge ${{manualBadgeClass(item.manual_status)}}">${{attentionEsc(item.manual_status || 'Unknown')}}</span></td>
        <td><span class="badge ${{autoBadgeClass(item.auto_status)}}">${{attentionEsc(item.auto_status || 'Unknown')}}${{autoSuffix}}</span></td>
        <td><span class="badge ${{epgBadgeClass(item.epg_status)}}">${{attentionEsc(item.epg_status || 'Unknown')}}</span></td>
        <td>${{attentionEsc(item.tested_on || '—')}}</td>
        <td class="url">${{streamLink}}</td>
      </tr>
    `;
  }}).join('');

  attentionRows = Array.from(document.querySelectorAll('#attentionTable tbody tr'));
  applyAttentionFilters();
}}

fetch('attention.json', {{ cache: 'no-store' }})
  .then(response => {{
    if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
    return response.json();
  }})
  .then(renderAttention)
  .catch(error => {{
    attentionSummary.innerHTML = '<div class="card"><div class="value">—</div><div class="label">Attention data unavailable</div></div>';
    attentionTableBody.innerHTML = `<tr><td colspan="9">attention.json could not be loaded: ${{attentionEsc(error.message)}}</td></tr>`;
    attentionRows = [];
    attentionVisibleCount.textContent = 'attention.json is not available yet.';
  }});

attentionSearch.addEventListener('input', applyAttentionFilters);
attentionSeverityFilter.addEventListener('change', applyAttentionFilters);
attentionCategoryFilter.addEventListener('change', applyAttentionFilters);

const healthSearch = document.getElementById('healthSearch');'''
if script_old not in text:
    raise SystemExit("attention dashboard script anchor not found")
text = text.replace(script_old, script_new, 1)

path.write_text(text, encoding="utf-8")
