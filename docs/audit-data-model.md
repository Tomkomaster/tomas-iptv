# Audit data ownership

`audit.json` is the Git-tracked **manual authority**. It should contain facts a
person deliberately established or wants to preserve: stream identity, VLC and
Samsung playback results, observed spoken language, manual notes/reasons,
exclusions, explicit routing overrides, source flags, and test dates.

It is intentionally **not** a telemetry database. Automated observations belong
in generated Pages output:

- `public/health.json` — scheduled stream probes and bounded health history;
- `public/same-build-health.json` — same-build failover probe evidence;
- `public/epg-health.json` — EPG mapping/programme health;
- `public/report.json` → `audit.channels` and `public/audit.csv` — the full
  runtime-enriched audit view, including derived source/protocol/routing state.

The manual file uses `schema_version: 2` and `storage: "manual_only"`. Runtime
code still accepts older rows for compatibility, but new machine fields such as
`probe_*`, `health_*`, `epg_*`, `http_*`, latency, timestamps and automatic
failure state are rejected if they are added to `audit.json`.

## Keeping the manual file compact

Run:

```bash
python tools/compact_audit.py
python tools/compact_audit.py --write
```

The compactor preserves manual facts, modernizes safe legacy aliases, removes
reconstructable build context (`protocol`, generated language/source aliases,
feed membership), and omits explicit representations of defaults such as
`decision: "auto"`, `exclude_from_playlist: false`, and `not_tested` device
statuses.

`tools/migrate_audit.py --write` also applies the same compaction contract so a
legacy migration cannot re-inflate the file.
