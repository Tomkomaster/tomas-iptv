from pathlib import Path


build = Path("build.py")
text = build.read_text(encoding="utf-8")

old_link = '''    <a href="audit.csv">Manual verification (CSV)</a>
    <a href="report.json">Machine report (JSON)</a>'''
new_link = '''    <a href="audit.csv">Manual verification (CSV)</a>
    <a href="health.json">Automated stream health (JSON)</a>
    <a href="report.json">Machine report (JSON)</a>'''
if old_link not in text:
    raise SystemExit("Dashboard link anchor not found.")
text = text.replace(old_link, new_link, 1)

old_section = '''  {audit_warning_html}

  <h2>Manual verification</h2>'''
new_section = '''  {audit_warning_html}

  <h2>Automated stream health</h2>
  <p class="muted">
    Advisory network checks for the stable family playlist. For HLS streams the checker
    loads the manifest, resolves a media playlist, and requests bytes from a real media
    segment. This never changes manual VLC + Samsung verification, audit.json, or stable
    playlist membership automatically. Three consecutive automated failures only recommend
    a manual retest.
  </p>

  <div id="healthSummary" class="audit-summary">
    <div class="card"><div class="value">…</div><div class="label">Loading stream health</div></div>
  </div>

  <div class="controls">
    <input id="healthSearch" type="search" placeholder="Search automated health...">
    <select id="healthStatusFilter">
      <option value="">All automated statuses</option>
      <option value="playable">Playable</option>
      <option value="failed">Failed</option>
      <option value="needs_manual_retest">Needs manual retest</option>
      <option value="Online">Online</option>
      <option value="Redirected">Redirected</option>
      <option value="Slow startup">Slow startup</option>
      <option value="HTTP error">HTTP error</option>
      <option value="Manifest unavailable">Manifest unavailable</option>
      <option value="No playable segments">No playable segments</option>
      <option value="Timeout">Timeout</option>
    </select>
  </div>
  <p id="healthVisibleCount" class="muted">Loading health.json…</p>

  <div class="table-wrap">
    <table id="healthTable">
      <thead>
        <tr>
          <th>Channel</th>
          <th>Manual</th>
          <th>Auto health</th>
          <th>Failure streak</th>
          <th>Startup</th>
          <th>Last checked</th>
          <th>Detail</th>
          <th>URL</th>
        </tr>
      </thead>
      <tbody>
        <tr><td colspan="8" class="muted">Loading automated stream health…</td></tr>
      </tbody>
    </table>
  </div>

  <h2>Manual verification</h2>'''
if old_section not in text:
    raise SystemExit("Dashboard section anchor not found.")
text = text.replace(old_section, new_section, 1)

script_anchor = '''<script>
const search = document.getElementById('search');'''
health_script = '''<script>
const healthSearch = document.getElementById('healthSearch');
const healthStatusFilter = document.getElementById('healthStatusFilter');
const healthVisibleCount = document.getElementById('healthVisibleCount');
const healthSummary = document.getElementById('healthSummary');
const healthTableBody = document.querySelector('#healthTable tbody');
let healthRows = [];

function healthEsc(value) {{
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}}

function applyHealthFilters() {{
  const q = healthSearch.value.trim().toLowerCase();
  const status = healthStatusFilter.value;
  let shown = 0;

  for (const row of healthRows) {{
    const matchesText = !q || row.innerText.toLowerCase().includes(q);
    const matchesStatus = !status
      || (status === 'playable' && row.dataset.healthSuccess === 'yes')
      || (status === 'failed' && row.dataset.healthSuccess === 'no')
      || (status === 'needs_manual_retest' && row.dataset.healthAttention === 'needs_manual_retest')
      || row.dataset.healthStatus === status;
    const show = matchesText && matchesStatus;
    row.style.display = show ? '' : 'none';
    if (show) shown++;
  }}

  healthVisibleCount.textContent = `Showing ${{shown}} of ${{healthRows.length}} stable streams`;
}}

function renderHealth(data) {{
  const summary = data.summary || {{}};
  const statusCounts = summary.status_counts || {{}};
  const streams = Array.isArray(data.streams) ? data.streams : [];

  healthSummary.innerHTML = `
    <div class="card"><div class="value">${{summary.playable ?? 0}}</div><div class="label">Playable now</div></div>
    <div class="card"><div class="value">${{statusCounts['Online'] ?? 0}}</div><div class="label">Online</div></div>
    <div class="card"><div class="value">${{statusCounts['Redirected'] ?? 0}}</div><div class="label">Redirected</div></div>
    <div class="card"><div class="value">${{statusCounts['Slow startup'] ?? 0}}</div><div class="label">Slow startup</div></div>
    <div class="card"><div class="value">${{summary.failed ?? 0}}</div><div class="label">Failed this check</div></div>
    <div class="card"><div class="value">${{summary.needs_manual_retest ?? 0}}</div><div class="label">Needs manual retest</div></div>
    <div class="card"><div class="value">${{healthEsc(data.generated_at || '—')}}</div><div class="label">Last automated check</div></div>
  `;

  healthTableBody.innerHTML = streams.map(item => {{
    const manualClass = item.manual_status === 'Samsung + VLC'
      ? 'verified'
      : (item.manual_status === 'Samsung' ? 'tv' : 'base');
    const autoClass = item.manual_retest_recommended
      ? 'rejected'
      : (item.status === 'Online'
          ? 'verified'
          : (item.status === 'Redirected' ? 'tv' : 'review'));
    const failureSuffix = item.success
      ? ''
      : ` ×${{item.consecutive_failures || 1}}`;
    const startup = Number.isFinite(Number(item.startup_seconds))
      ? `${{Number(item.startup_seconds).toFixed(2)}} s`
      : '—';
    const detail = item.manual_retest_recommended
      ? `${{item.detail || ''}} Manual VLC + Samsung retest recommended.`
      : (item.detail || '—');

    return `
      <tr data-health-status="${{healthEsc(item.status)}}" data-health-success="${{item.success ? 'yes' : 'no'}}" data-health-attention="${{healthEsc(item.attention)}}">
        <td class="channel">${{healthEsc(item.channel)}}</td>
        <td><span class="badge ${{manualClass}}">${{healthEsc(item.manual_status || 'Unknown')}}</span></td>
        <td><span class="badge ${{autoClass}}">${{healthEsc(item.status)}}${{failureSuffix}}</span></td>
        <td>${{item.consecutive_failures || 0}}</td>
        <td>${{healthEsc(startup)}}</td>
        <td>${{healthEsc(item.checked_at || data.generated_at || '—')}}</td>
        <td><div class="detail">${{healthEsc(detail)}}</div></td>
        <td class="url"><a href="${{healthEsc(item.stream_url)}}" target="_blank" rel="noopener">stream</a></td>
      </tr>
    `;
  }}).join('');

  healthRows = Array.from(document.querySelectorAll('#healthTable tbody tr'));
  applyHealthFilters();
}}

fetch('health.json', {{ cache: 'no-store' }})
  .then(response => {{
    if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
    return response.json();
  }})
  .then(renderHealth)
  .catch(error => {{
    healthSummary.innerHTML = '<div class="card"><div class="value">—</div><div class="label">Health data unavailable</div></div>';
    healthTableBody.innerHTML = `<tr><td colspan="8">Automated health data could not be loaded: ${{healthEsc(error.message)}}</td></tr>`;
    healthRows = [];
    healthVisibleCount.textContent = 'health.json is not available yet.';
  }});

healthSearch.addEventListener('input', applyHealthFilters);
healthStatusFilter.addEventListener('change', applyHealthFilters);

const search = document.getElementById('search');'''
if script_anchor not in text:
    raise SystemExit("Dashboard script anchor not found.")
text = text.replace(script_anchor, health_script, 1)
build.write_text(text, encoding="utf-8")

workflow = Path(".github/workflows/build-and-publish.yml")
wf = workflow.read_text(encoding="utf-8")
path_anchor = '''      - "epg_health.py"
      - "migrate_audit.py"'''
path_replacement = '''      - "epg_health.py"
      - "healthcheck.py"
      - "migrate_audit.py"'''
if path_anchor not in wf:
    raise SystemExit("Workflow path anchor not found.")
wf = wf.replace(path_anchor, path_replacement, 1)

build_anchor = '''      - name: Build IPTV playlist
        run: python3 build.py

      - name: Set up Node.js for EPG'''
build_replacement = '''      - name: Build IPTV playlist
        run: python3 build.py

      - name: Check stable stream health
        shell: bash
        run: |
          set -euo pipefail

          HEALTH_ENABLED="$(
            python3 -c '
          import json
          from pathlib import Path
          cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
          print("true" if (cfg.get("health") or {}).get("enabled", True) else "false")
          '
          )"

          if [ "$HEALTH_ENABLED" != "true" ]; then
            echo "Automated stream health disabled in config.json; skipping."
            exit 0
          fi

          python3 healthcheck.py

      - name: Set up Node.js for EPG'''
if build_anchor not in wf:
    raise SystemExit("Workflow build anchor not found.")
wf = wf.replace(build_anchor, build_replacement, 1)
workflow.write_text(wf, encoding="utf-8")
