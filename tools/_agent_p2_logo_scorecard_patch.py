#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected patch marker not found in {path}: {old[:100]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_logo_overrides() -> None:
    path = Path("data/logo_overrides.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    additions = [
        {
            "match": {"country_code": "CZ", "tvg_id": "TVBarrandov.cz@SD"},
            "logo": "https://upload.wikimedia.org/wikipedia/commons/e/ef/TV_Barrandov_logo_2025.png",
            "source": "TV Barrandov official logo-download pack; current 2025 TV Barrandov-authored PNG mirror",
            "note": "P2; reviewed against the broadcaster's current downloadable branding; manually reviewed 2026-08-13",
        },
        {
            "match": {"country_code": "CZ", "tvg_id": "KinoBarrandov.cz@SD"},
            "logo": "https://upload.wikimedia.org/wikipedia/commons/c/ce/Kino_Barrandov_logo_2025.png",
            "source": "TV Barrandov official logo-download pack; current 2025 TV Barrandov-authored PNG mirror",
            "note": "P2; reviewed against the broadcaster's current downloadable branding; manually reviewed 2026-08-13",
        },
        {
            "match": {"country_code": "CZ", "tvg_id": "BarrandovKrimi.cz@SD"},
            "logo": "https://upload.wikimedia.org/wikipedia/commons/a/aa/Krimi_Barrandov_logo_2025.png",
            "source": "TV Barrandov official logo-download pack; current 2025 TV Barrandov-authored PNG mirror",
            "note": "P2; reviewed against the broadcaster's current downloadable branding; manually reviewed 2026-08-13",
        },
        {
            "match": {"country_code": "CZ", "tvg_id": "TelevizeSeznam.cz@SD"},
            "logo": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/dd/Logo_Televize_Seznam.png/1280px-Logo_Televize_Seznam.png",
            "source": "Televize Seznam official identity; Wikimedia Commons file source metadata identifies Seznam TV",
            "note": "P2; replaces an unreviewed source fallback with reviewed channel artwork; manually reviewed 2026-08-13",
        },
        {
            "match": {"country_code": "CZ", "tvg_id": "History.cz@SD"},
            "logo": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/01/History_%282021%29.svg/500px-History_%282021%29.svg.png",
            "source": "History/A&E Networks official identity; Wikimedia Commons file references history.com and credits A&E Networks",
            "note": "P2; current History identity; manually reviewed 2026-08-13",
        },
        {
            "match": {"country_code": "CZ", "tvg_id": "AMCEurope.uk@CzechRepublic"},
            "logo": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/34/AMC_logo_2019.svg/960px-AMC_logo_2019.svg.png",
            "source": "AMC official network identity; Wikimedia Commons file references amc.com and credits AMC",
            "note": "P2; reviewed AMC identity for the Czech-market feed; manually reviewed 2026-08-13",
        },
        {
            "match": {"country_code": "CZ", "tvg_id": "PrimaCool.cz@SD"},
            "logo": "https://upload.wikimedia.org/wikipedia/commons/thumb/5/50/Prima_Cool_logo_zelen%C3%A9.png/960px-Prima_Cool_logo_zelen%C3%A9.png",
            "source": "FTV Prima official Prima COOL identity pages; clean PNG mirror reviewed against broadcaster branding",
            "note": "P2; manually reviewed 2026-08-13",
        },
        {
            "match": {"country_code": "CZ", "tvg_id": "PrimaLove.cz@SD"},
            "logo": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/Prima_Love_logo_2018.png/960px-Prima_Love_logo_2018.png",
            "source": "FTV Prima official Prima LOVE branding history confirms the 2018 pink identity; clean PNG mirror",
            "note": "P2; manually reviewed 2026-08-13",
        },
        {
            "match": {"country_code": "CZ", "tvg_id": "PrimaShow.cz@SD"},
            "logo": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/1a/Prima_Show.svg/1280px-Prima_Show.svg.png",
            "source": "FTV Prima; Wikimedia Commons file lists FTV Prima as both source and author",
            "note": "P2; PNG rendering selected for TV-client compatibility; manually reviewed 2026-08-13",
        },
        {
            "match": {"country_code": "CZ", "tvg_id": "PrimaStar.cz@SD"},
            "logo": "https://upload.wikimedia.org/wikipedia/commons/5/5f/Prima_Star.png",
            "source": "FTV Prima official Prima Star social asset; Wikimedia Commons credits FTV Prima as author",
            "note": "P2; manually reviewed 2026-08-13",
        },
        {
            "match": {"country_code": "CZ", "tvg_id": "PrimaZoom.cz@SD"},
            "logo": "https://upload.wikimedia.org/wikipedia/commons/thumb/9/98/Prima_ZOOM_logo.svg/960px-Prima_ZOOM_logo.svg.png",
            "source": "FTV Prima official Prima ZOOM logo gallery; clean PNG rendering reviewed against broadcaster artwork",
            "note": "P2; manually reviewed 2026-08-13",
        },
        {
            "match": {"country_code": "CZ", "tvg_id": "CTDecko.cz@SD"},
            "logo": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/%C4%8CT-D_logo.svg/960px-%C4%8CT-D_logo.svg.png",
            "source": "Česká televize official logo-download page; clean PNG rendering of the ČT :D identity",
            "note": "P2; shared ČT :D/ČT art service row; manually reviewed 2026-08-13",
        },
    ]
    entries = payload.setdefault("entries", [])
    existing = {json.dumps(item.get("match", {}), sort_keys=True, ensure_ascii=False) for item in entries}
    for item in additions:
        key = json.dumps(item["match"], sort_keys=True, ensure_ascii=False)
        if key not in existing:
            entries.append(item)
            existing.add(key)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch_priority_coverage() -> None:
    path = "tools/priority_coverage.py"
    replace_once(
        path,
        "\ndef _add_target(targets: list[dict], candidate: dict) -> None:\n",
        '''\ndef _logo_row_for_target(target: dict, logo_rows: list[dict]) -> dict | None:\n    country = str(target.get("country") or "").strip().upper()\n    candidates = [\n        row for row in logo_rows\n        if str(row.get("country_code") or "").strip().upper() == country\n    ]\n    target_id = normalize_tvg_id(target.get("tvg_id", ""))\n    if target_id:\n        for row in candidates:\n            if normalize_tvg_id(row.get("tvg_id", "")) == target_id:\n                return row\n    target_name = normalize_name(target.get("channel", ""))\n    if target_name:\n        for row in candidates:\n            if normalize_name(row.get("channel", "")) == target_name:\n                return row\n    return None\n\n\ndef _priority_logo_summary(targets: list[dict], logo_quality: dict | None) -> dict:\n    stable = [target for target in targets if target.get("status") == "WORKING"]\n    logo_rows = list((logo_quality or {}).get("channels") or [])\n    canonical = 0\n    source = 0\n    missing = 0\n    for target in stable:\n        row = _logo_row_for_target(target, logo_rows)\n        quality = str((row or {}).get("quality_category") or "Missing")\n        if quality == "Canonical":\n            canonical += 1\n        elif quality == "Source fallback":\n            source += 1\n        else:\n            missing += 1\n    total = len(stable)\n    available = canonical + source\n    return {\n        "stable_targets": total,\n        "with_logo": available,\n        "canonical_logo": canonical,\n        "source_fallback": source,\n        "missing_logo": missing,\n        "logo_availability_percent": round(100.0 * available / total if total else 0.0, 1),\n        "canonical_logo_coverage_percent": round(100.0 * canonical / total if total else 0.0, 1),\n    }\n\n\ndef _add_target(targets: list[dict], candidate: dict) -> None:\n''',
    )
    replace_once(
        path,
        '''    wanted_channels: list[dict[str, str]],\n) -> dict:\n''',
        '''    wanted_channels: list[dict[str, str]],\n    logo_quality: dict | None = None,\n) -> dict:\n''',
    )
    replace_once(
        path,
        '''            priorities[priority] = {\n                "found": len(items) - len(missing),\n                "total": len(items),\n                "missing": [\n''',
        '''            priorities[priority] = {\n                "found": len(items) - len(missing),\n                "total": len(items),\n                "logo_coverage": _priority_logo_summary(items, logo_quality),\n                "missing": [\n''',
    )
    replace_once(
        path,
        '''    return {\n        "schema_version": 1,\n        "definition": "found means at least one stable family feed (WORKING)",\n        "priorities": list(TRACKED_PRIORITIES),\n        "countries": countries,\n    }\n''',
        '''    return {\n        "schema_version": 1,\n        "definition": "found means at least one stable family feed (WORKING)",\n        "logo_metric": {\n            "definition": (\n                "Among stable tracked P1/P2 targets only, logo availability counts Canonical plus "\n                "Source fallback; canonical coverage counts reviewed logo overrides only."\n            ),\n            "denominator": "stable tracked P1/P2 targets",\n        },\n        "logo_summary": _priority_logo_summary(targets, logo_quality),\n        "priorities": list(TRACKED_PRIORITIES),\n        "countries": countries,\n    }\n''',
    )
    replace_once(
        path,
        '''    wanted_channels_path: Path = Path("data/wanted_channels.json"),\n) -> dict:\n    coverage = build_priority_coverage(\n''',
        '''    wanted_channels_path: Path = Path("data/wanted_channels.json"),\n    logo_quality_path: Path = Path("public/logo-quality.json"),\n) -> dict:\n    logo_quality = _load_json(logo_quality_path) if logo_quality_path.is_file() else {}\n    coverage = build_priority_coverage(\n''',
    )
    replace_once(
        path,
        '''        priority_policy=_load_json(priority_policy_path),\n        wanted_channels=load_wanted_channels(wanted_channels_path),\n    )\n''',
        '''        priority_policy=_load_json(priority_policy_path),\n        wanted_channels=load_wanted_channels(wanted_channels_path),\n        logo_quality=logo_quality,\n    )\n''',
    )


def patch_dashboard_template() -> None:
    replace_once(
        "templates/dashboard.html",
        '''  <div id="logoQualitySummary" class="audit-summary">\n    <div class="card"><div class="value">…</div><div class="label">Loading logo coverage</div></div>\n  </div>\n  <h3>Logo coverage by country</h3>\n''',
        '''  <div id="logoQualitySummary" class="audit-summary">\n    <div class="card"><div class="value">…</div><div class="label">Loading logo coverage</div></div>\n  </div>\n  <h3>P1 / P2 logo completeness</h3>\n  <p class="muted">\n    This score uses only P1/P2 channels that already have a stable family feed. A missing\n    stream remains a stream-coverage problem and does not dilute the logo denominator.\n    Availability includes reviewed Canonical logos plus Source fallbacks; Canonical coverage\n    is the stricter reviewed-artwork score.\n  </p>\n  <div id="priorityLogoSummary" class="audit-summary">\n    <div class="card"><div class="value">…</div><div class="label">Loading P1/P2 logo completeness</div></div>\n  </div>\n  <h3>Logo coverage by country</h3>\n''',
    )


def patch_dashboard_js() -> None:
    path = "static/dashboard.js"
    replace_once(
        path,
        '''  renderLogoQuality();\n  applyLogoQualityFilters();\n''',
        '''  renderLogoQuality();\n  renderPriorityLogoSummary();\n  applyLogoQualityFilters();\n''',
    )
    replace_once(
        path,
        '''const logoQualitySummary = document.getElementById('logoQualitySummary');\nconst logoCountrySummary = document.getElementById('logoCountrySummary');\n''',
        '''const logoQualitySummary = document.getElementById('logoQualitySummary');\nconst priorityLogoSummary = document.getElementById('priorityLogoSummary');\nconst logoCountrySummary = document.getElementById('logoCountrySummary');\n''',
    )
    replace_once(
        path,
        '''let logoQualityData = null;\nlet logoQualityRows = [];\n''',
        '''let logoQualityData = null;\nlet priorityCoverageData = null;\nlet logoQualityRows = [];\n''',
    )
    replace_once(
        path,
        '''function renderLogoQuality() {\n''',
        '''function mergePriorityLogoCoverage(parts) {\n  const summary = { stableTargets: 0, withLogo: 0, canonical: 0, source: 0, missing: 0 };\n  for (const part of parts.filter(Boolean)) {\n    summary.stableTargets += Number(part.stable_targets || 0);\n    summary.withLogo += Number(part.with_logo || 0);\n    summary.canonical += Number(part.canonical_logo || 0);\n    summary.source += Number(part.source_fallback || 0);\n    summary.missing += Number(part.missing_logo || 0);\n  }\n  summary.availability = summary.stableTargets ? 100 * summary.withLogo / summary.stableTargets : 0;\n  summary.canonicalCoverage = summary.stableTargets ? 100 * summary.canonical / summary.stableTargets : 0;\n  return summary;\n}\n\nfunction priorityLogoCoverage(priority) {\n  if (!priorityCoverageData) return mergePriorityLogoCoverage([]);\n  const countries = priorityCoverageData.countries || {};\n  const parts = Object.entries(countries)\n    .filter(([code]) => countryMatches(code))\n    .map(([, country]) => country?.priorities?.[priority]?.logo_coverage);\n  return mergePriorityLogoCoverage(parts);\n}\n\nfunction renderPriorityLogoSummary() {\n  if (!priorityLogoSummary || !priorityCoverageData) return;\n  const p1 = priorityLogoCoverage('P1');\n  const p2 = priorityLogoCoverage('P2');\n  const total = mergePriorityLogoCoverage([\n    {\n      stable_targets: p1.stableTargets, with_logo: p1.withLogo, canonical_logo: p1.canonical,\n      source_fallback: p1.source, missing_logo: p1.missing,\n    },\n    {\n      stable_targets: p2.stableTargets, with_logo: p2.withLogo, canonical_logo: p2.canonical,\n      source_fallback: p2.source, missing_logo: p2.missing,\n    },\n  ]);\n  priorityLogoSummary.innerHTML = `\n    <div class="card"><div class="value">${total.availability.toFixed(1)}%</div><div class="label">P1/P2 logo availability (${total.withLogo}/${total.stableTargets} stable)</div></div>\n    <div class="card"><div class="value">${total.canonicalCoverage.toFixed(1)}%</div><div class="label">P1/P2 canonical coverage (${total.canonical}/${total.stableTargets})</div></div>\n    <div class="card"><div class="value">${p1.canonical}/${p1.stableTargets}</div><div class="label">P1 canonical</div><div class="detail">${p1.canonicalCoverage.toFixed(1)}% reviewed</div></div>\n    <div class="card"><div class="value">${p2.canonical}/${p2.stableTargets}</div><div class="label">P2 canonical</div><div class="detail">${p2.canonicalCoverage.toFixed(1)}% reviewed</div></div>\n    <div class="card"><div class="value">${total.source}</div><div class="label">P1/P2 source fallbacks remaining</div></div>\n    <div class="card"><div class="value">${total.missing}</div><div class="label">P1/P2 stable channels missing logos</div></div>`;\n}\n\nfunction renderLogoQuality() {\n''',
    )
    replace_once(
        path,
        '''if (logoQualitySearch) logoQualitySearch.addEventListener('input', applyLogoQualityFilters);\nif (logoQualityFilter) logoQualityFilter.addEventListener('change', applyLogoQualityFilters);\n''',
        '''fetch('priority-coverage.json', { cache: 'no-store' })\n  .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })\n  .then(data => {\n    priorityCoverageData = data;\n    renderPriorityLogoSummary();\n  })\n  .catch(error => {\n    if (priorityLogoSummary) priorityLogoSummary.innerHTML = `<div class="card"><div class="value">—</div><div class="label">P1/P2 logo completeness unavailable: ${esc(error.message)}</div></div>`;\n  });\nif (logoQualitySearch) logoQualitySearch.addEventListener('input', applyLogoQualityFilters);\nif (logoQualityFilter) logoQualityFilter.addEventListener('change', applyLogoQualityFilters);\n''',
    )


def patch_tests() -> None:
    replace_once(
        "tests/test_priority_coverage.py",
        '''    def test_injects_prominent_scorecard_before_next_work(self):\n''',
        '''    def test_logo_score_uses_only_stable_priority_targets(self):\n        rows = [\n            audit_row("Alpha", "Alpha.hu", "HU", stable=True),\n            audit_row("Beta", "Beta.hu", "HU"),\n            audit_row("Movie One", "MovieOne.hu", "HU", stable=True),\n        ]\n        config = {\n            "country_names": {"HU": "Hungary"},\n            "country_outputs": {"HU": "public/hu.m3u"},\n        }\n        policy = {\n            "schema_version": 1,\n            "default_priority": "P3",\n            "entries": [{"country": "HU", "channel": "Movie One", "priority": "P2"}],\n        }\n        wanted = [\n            {"country_code": "HU", "channel": "Alpha", "tvg_id": "Alpha.hu", "priority": "P1"},\n            {"country_code": "HU", "channel": "Beta", "tvg_id": "Beta.hu", "priority": "P1"},\n        ]\n        logos = {\n            "channels": [\n                {"country_code": "HU", "channel": "Alpha", "tvg_id": "Alpha.hu", "quality_category": "Canonical"},\n                {"country_code": "HU", "channel": "Movie One", "tvg_id": "MovieOne.hu", "quality_category": "Source fallback"},\n            ]\n        }\n\n        coverage = build_priority_coverage(\n            rows,\n            config=config,\n            priority_policy=policy,\n            wanted_channels=wanted,\n            logo_quality=logos,\n        )\n\n        hu = coverage["countries"]["HU"]["priorities"]\n        self.assertEqual(hu["P1"]["logo_coverage"]["stable_targets"], 1)\n        self.assertEqual(hu["P1"]["logo_coverage"]["canonical_logo"], 1)\n        self.assertEqual(hu["P2"]["logo_coverage"]["stable_targets"], 1)\n        self.assertEqual(hu["P2"]["logo_coverage"]["source_fallback"], 1)\n        self.assertEqual(coverage["logo_summary"]["stable_targets"], 2)\n        self.assertEqual(coverage["logo_summary"]["with_logo"], 2)\n        self.assertEqual(coverage["logo_summary"]["canonical_logo"], 1)\n        self.assertEqual(coverage["logo_summary"]["missing_logo"], 0)\n        self.assertEqual(coverage["logo_summary"]["canonical_logo_coverage_percent"], 50.0)\n\n    def test_injects_prominent_scorecard_before_next_work(self):\n''',
    )
    replace_once(
        "tests/test_logo_quality.py",
        '''        self.assertIn("logo-quality.json", script)\n        self.assertIn("missing-logos.csv", template)\n''',
        '''        self.assertIn("logo-quality.json", script)\n        self.assertIn("priority-coverage.json", script)\n        self.assertIn("P1 / P2 logo completeness", template)\n        self.assertIn('id="priorityLogoSummary"', template)\n        self.assertIn("P1/P2 canonical coverage", script)\n        self.assertIn("missing-logos.csv", template)\n''',
    )


def main() -> None:
    append_logo_overrides()
    patch_priority_coverage()
    patch_dashboard_template()
    patch_dashboard_js()
    patch_tests()


if __name__ == "__main__":
    main()
