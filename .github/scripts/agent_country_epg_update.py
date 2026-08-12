from __future__ import annotations

import json
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# 1) Country-aware EPG configuration.
path = Path("config.json")
cfg = json.loads(path.read_text(encoding="utf-8"))
cfg["epg"] = {
    "enabled": True,
    "public_url": "https://tomkomaster.github.io/tomas-iptv/guide.xml",
    "countries": {
        "HU": {
            "sites": [
                "mediaklikk.hu",
                "horizon.tv",
            ],
            "external": {
                "provider": "epgshare01.online",
                "url": "https://epgshare01.online/epgshare01/epg_ripper_HU1.xml.gz",
            },
        },
        "SK": {
            "sites": [
                "horizon.tv",
                "m.tv.sms.cz",
                "mujtvprogram.cz",
            ],
        },
        "CZ": {
            "sites": [
                "horizon.tv",
                "m.tv.sms.cz",
                "mujtvprogram.cz",
            ],
        },
    },
    "future_days": 7,
    "max_connections": 3,
}
path.write_text(
    json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)


# 2) Add only authoritative/current IPTV-org IDs to the Slovak extras.
path = Path("extras/sk.m3u")
text = path.read_text(encoding="utf-8")
replacements = {
    '#EXTINF:-1 tvg-name="Doma",Doma':
        '#EXTINF:-1 tvg-id="MarkizaDoma.sk" tvg-name="Doma",Doma',
    '#EXTINF:-1 tvg-name="Dajto",Dajto':
        '#EXTINF:-1 tvg-id="MarkizaDajto.sk" tvg-name="Dajto",Dajto',
    '#EXTINF:-1 tvg-name="Markíza Klasik",Markíza Klasik':
        '#EXTINF:-1 tvg-id="MarkizaKlasik.sk" tvg-name="Markíza Klasik",Markíza Klasik',
    '#EXTINF:-1 tvg-name="Jojko",Jojko':
        '#EXTINF:-1 tvg-id="Jojko.sk" tvg-name="Jojko",Jojko',
    '#EXTINF:-1 tvg-name="LALA TV",LALA TV':
        '#EXTINF:-1 tvg-id="LalaTV.sk" tvg-name="LALA TV",LALA TV',
}
for old, new in replacements.items():
    text = replace_once(text, old, new, f"extras id {old}")

old = '#EXTINF:-1 tvg-name="Markíza Krimi",Markíza Krimi'
count = text.count(old)
if count != 2:
    raise RuntimeError(
        f"Markíza Krimi extras: expected two candidate entries, found {count}"
    )
text = text.replace(
    old,
    '#EXTINF:-1 tvg-id="MarkizaKrimi.sk" tvg-name="Markíza Krimi",Markíza Krimi',
)
path.write_text(text, encoding="utf-8")


# 3) Make EPG policy defaults explicitly country-aware without changing
# current expected/optional/not_expected behavior.
path = Path("epg_policy.json")
policy = json.loads(path.read_text(encoding="utf-8"))
policy["schema_version"] = 2
policy["country_defaults"] = {
    "HU": "expected",
    "SK": "expected",
    "CZ": "expected",
}
path.write_text(
    json.dumps(policy, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

path = Path("epg_policy.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    'EPG_POLICY_SELECTORS = ("stream_url", "tvg_id", "channel")\n',
    'EPG_POLICY_SELECTORS = ("stream_url", "tvg_id", "channel")\n'
    'EPG_COUNTRY_DEFAULTS_KEY = "__country_defaults__"\n',
    "EPG policy country defaults constant",
)
text = replace_once(
    text,
    '''    indexes: dict[str, dict[str, dict]] = {\n        selector: {} for selector in EPG_POLICY_SELECTORS\n    }\n\n    for position, entry in enumerate(entries, start=1):''',
    '''    indexes: dict[str, dict[str, dict]] = {\n        selector: {} for selector in EPG_POLICY_SELECTORS\n    }\n\n    raw_country_defaults = payload.get("country_defaults") or {}\n    if not isinstance(raw_country_defaults, dict):\n        raise ValueError("EPG policy country_defaults must be an object.")\n\n    country_defaults: dict[str, str] = {}\n    for raw_code, raw_status in raw_country_defaults.items():\n        code = str(raw_code or "").strip().upper()\n        status = str(raw_status or "").strip().casefold()\n        if not code:\n            raise ValueError("EPG policy country default has an empty country code.")\n        if status not in EPG_POLICY_STATUSES:\n            raise ValueError(\n                f"Invalid EPG policy country default for {code}: {status!r}."\n            )\n        country_defaults[code] = status\n\n    indexes[EPG_COUNTRY_DEFAULTS_KEY] = country_defaults\n\n    for position, entry in enumerate(entries, start=1):''',
    "EPG policy compile country defaults",
)
text = replace_once(
    text,
    '''    return {\n        "status": default,\n        "reason": "",\n        "name": "",\n        "matched_by": "default",\n    }\n''',
    '''    country_code = str(\n        row.get("output_language_code")\n        or row.get("language_code")\n        or row.get("playlist_language_code")\n        or ""\n    ).strip().upper()\n    country_defaults = indexes.get(EPG_COUNTRY_DEFAULTS_KEY, {})\n    country_status = country_defaults.get(country_code) if country_code else None\n    if country_status:\n        return {\n            "status": country_status,\n            "reason": "",\n            "name": "",\n            "matched_by": "country_default",\n        }\n\n    return {\n        "status": default,\n        "reason": "",\n        "name": "",\n        "matched_by": "default",\n    }\n''',
    "EPG policy resolve country default",
)
path.write_text(text, encoding="utf-8")


# 4) Add country-level actual EPG health to epg-health.json.
path = Path("epg_health.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''    provider_by_tvg: dict[str, str] = {}\n    mapped_by_provider: Counter[str] = Counter()\n''',
    '''    provider_by_tvg: dict[str, str] = {}\n    mapped_by_provider: Counter[str] = Counter()\n    country_by_tvg = {\n        str(tvg_id): str(code).strip().upper()\n        for tvg_id, code in (coverage.get("tvg_id_countries") or {}).items()\n        if str(tvg_id).strip() and str(code).strip()\n    }\n''',
    "EPG health country id map",
)
text = replace_once(
    text,
    '''    mapped_effectiveness = (\n        populated_total / mapped_total * 100.0\n        if mapped_total\n        else 0.0\n    )\n\n    providers: dict[str, dict] = {}''',
    '''    mapped_effectiveness = (\n        populated_total / mapped_total * 100.0\n        if mapped_total\n        else 0.0\n    )\n\n    countries: dict[str, dict] = {}\n    configured_countries = coverage.get("countries") or {}\n    if isinstance(configured_countries, dict):\n        for raw_code, raw_info in configured_countries.items():\n            code = str(raw_code or "").strip().upper()\n            info = raw_info if isinstance(raw_info, dict) else {}\n            if not code:\n                continue\n            country_total = int(info.get("playlist_tvg_ids") or 0)\n            mapped_ids = {\n                tvg_id\n                for tvg_id in provider_by_tvg\n                if country_by_tvg.get(tvg_id) == code\n            }\n            populated_country = mapped_ids & populated_ids\n            mapped_country = len(mapped_ids)\n            populated_country_count = len(populated_country)\n            countries[code] = {\n                "playlist_tvg_ids": country_total,\n                "mapped_tvg_ids": mapped_country,\n                "mapping_coverage_percent": round(\n                    mapped_country / country_total * 100.0\n                    if country_total else 0.0,\n                    1,\n                ),\n                "channels_with_programmes": populated_country_count,\n                "actual_programme_coverage_percent": round(\n                    populated_country_count / country_total * 100.0\n                    if country_total else 0.0,\n                    1,\n                ),\n                "mapped_channels_effective_percent": round(\n                    populated_country_count / mapped_country * 100.0\n                    if mapped_country else 0.0,\n                    1,\n                ),\n            }\n\n    providers: dict[str, dict] = {}''',
    "EPG health country calculations",
)
text = replace_once(
    text,
    '''        "providers": providers,\n        "mapped_without_programmes_count": len(missing_programmes),''',
    '''        "providers": providers,\n        "countries": countries,\n        "mapped_without_programmes_count": len(missing_programmes),''',
    "EPG health report countries",
)
text = replace_once(
    text,
    '''    for provider, info in providers.items():\n        errors = info["http_errors"]''',
    '''    for code, info in countries.items():\n        print(\n            f"- {code} EPG: "\n            f"{info['channels_with_programmes']}/"\n            f"{info['playlist_tvg_ids']} tvg-id channels have programmes "\n            f"({info['actual_programme_coverage_percent']:.1f}%); "\n            f"{info['mapped_tvg_ids']} mapped."\n        )\n\n    for provider, info in providers.items():\n        errors = info["http_errors"]''',
    "EPG health country print",
)
path.write_text(text, encoding="utf-8")


# 5) Surface country EPG coverage on the generated dashboard. The dashboard is
# built before the EPG run, so it fetches epg-health.json at page-load time.
path = Path("build.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''  <h2>Needs attention</h2>''',
    '''  <h2>EPG coverage by country</h2>\n  <p class="muted">\n    Programme-guide coverage is shown separately for HU, SK and CZ so growth in\n    one country does not hide gaps in another. Percentages use stable channels\n    that currently have a tvg-id. Missing tvg-id values remain visible in Needs attention.\n  </p>\n  <div id="epgCountrySummary" class="audit-summary">\n    <div class="card"><div class="value">…</div><div class="label">Loading EPG coverage</div></div>\n  </div>\n\n  <h2>Needs attention</h2>''',
    "dashboard EPG country section",
)
text = replace_once(
    text,
    '''const attentionSearch = document.getElementById('attentionSearch');''',
    '''const epgCountrySummary = document.getElementById('epgCountrySummary');\n\nfunction renderEpgCountryCoverage(data) {{\n  const countries = data.countries || {{}};\n  const codes = ['HU', 'SK', 'CZ'].filter(code => countries[code]);\n  if (!codes.length) {{\n    epgCountrySummary.innerHTML = '<div class="card"><div class="value">—</div><div class="label">Country EPG data unavailable</div></div>';\n    return;\n  }}\n\n  epgCountrySummary.innerHTML = codes.map(code => {{\n    const info = countries[code] || {{}};\n    const total = Number(info.playlist_tvg_ids || 0);\n    const mapped = Number(info.mapped_tvg_ids || 0);\n    const populated = Number(info.channels_with_programmes || 0);\n    const actual = Number(info.actual_programme_coverage_percent || 0).toFixed(1);\n    const mappedPct = Number(info.mapping_coverage_percent || 0).toFixed(1);\n    return `\n      <div class="card">\n        <div class="value">${{actual}}%</div>\n        <div class="label">${{code}} programmes (${{populated}}/${{total}})</div>\n        <div class="detail">Mapped: ${{mapped}}/${{total}} (${{mappedPct}}%)</div>\n      </div>\n    `;\n  }}).join('');\n}}\n\nfetch('epg-health.json', {{ cache: 'no-store' }})\n  .then(response => {{\n    if (!response.ok) throw new Error(`HTTP ${{response.status}}`);\n    return response.json();\n  }})\n  .then(renderEpgCountryCoverage)\n  .catch(error => {{\n    epgCountrySummary.innerHTML = `<div class="card"><div class="value">—</div><div class="label">EPG coverage unavailable: ${{attentionEsc(error.message)}}</div></div>`;\n  }});\n\nconst attentionSearch = document.getElementById('attentionSearch');''',
    "dashboard EPG country JS",
)
path.write_text(text, encoding="utf-8")


# 6) Switch production EPG preparation to the country-aware orchestrator and
# move the existing HU external feed under HU configuration.
path = Path(".github/workflows/build-and-publish.yml")
text = path.read_text(encoding="utf-8")

sites_start = '''          EPG_SITES="$(\n            python3 -c '\n          import json\n          from pathlib import Path\n          cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))\n          sites = (cfg.get("epg") or {}).get("sites") or []\n          print(",".join(str(site).strip() for site in sites if str(site).strip()))\n          '\n          )"\n\n'''
if sites_start not in text:
    raise RuntimeError("workflow legacy EPG_SITES block not found")
text = text.replace(sites_start, "", 1)

legacy_external = '''          external = (cfg.get("epg") or {}).get("external") or {}'''
new_external = '''          epg = cfg.get("epg") or {}\n          external = (((epg.get("countries") or {}).get("HU") or {}).get("external") or {})'''
count = text.count(legacy_external)
if count != 2:
    raise RuntimeError(f"workflow external config: expected 2 matches, found {count}")
text = text.replace(legacy_external, new_external)

old_future = '''          external = (cfg.get("epg") or {}).get("external") or {}\n          print(int(external.get("future_days") or 7))'''
# The prior replacement intentionally did not hit this third block yet if it
# was represented separately; support either shape after the two replacements.
if old_future in text:
    text = text.replace(
        old_future,
        '''          epg = cfg.get("epg") or {}\n          print(int(epg.get("future_days") or 7))''',
        1,
    )
else:
    old_future_after = '''          epg = cfg.get("epg") or {}\n          external = (((epg.get("countries") or {}).get("HU") or {}).get("external") or {})\n          print(int(external.get("future_days") or 7))'''
    if old_future_after not in text:
        raise RuntimeError("workflow EPG_FUTURE_DAYS block not found")
    text = text.replace(
        old_future_after,
        '''          epg = cfg.get("epg") or {}\n          print(int(epg.get("future_days") or 7))''',
        1,
    )

text = replace_once(
    text,
    '''          if [ -z "$EPG_SITES" ]; then\n            echo "EPG is enabled but epg.sites is empty."\n            exit 1\n          fi\n\n''',
    "",
    "workflow legacy sites guard",
)
text = replace_once(
    text,
    '''          python3 epg_prepare.py \\\n            --playlist public/tv.m3u \\\n            --epg-root .epg-builder \\\n            --sites "$EPG_SITES" \\\n            --output .epg.channels.xml \\\n            --report .epg-iptv-coverage.json''',
    '''          python3 epg_country_prepare.py \\\n            --config config.json \\\n            --epg-root .epg-builder \\\n            --output .epg.channels.xml \\\n            --report .epg-iptv-coverage.json''',
    "workflow country EPG preparation",
)
path.write_text(text, encoding="utf-8")

print("Country-aware EPG changes applied.")
