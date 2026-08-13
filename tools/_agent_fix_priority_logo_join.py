#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding='utf-8')
    if old not in text:
        raise RuntimeError(f'Patch marker missing in {path}')
    p.write_text(text.replace(old, new, 1), encoding='utf-8')


replace_once(
    'tools/priority_coverage.py',
    'import json\nfrom pathlib import Path\n',
    'import json\nimport re\nfrom pathlib import Path\n',
)

replace_once(
    'tools/priority_coverage.py',
    '''def _logo_row_for_target(target: dict, logo_rows: list[dict]) -> dict | None:\n    country = str(target.get("country") or "").strip().upper()\n    candidates = [\n        row for row in logo_rows\n        if str(row.get("country_code") or "").strip().upper() == country\n    ]\n    target_id = normalize_tvg_id(target.get("tvg_id", ""))\n    if target_id:\n        for row in candidates:\n            if normalize_tvg_id(row.get("tvg_id", "")) == target_id:\n                return row\n    target_name = normalize_name(target.get("channel", ""))\n    if target_name:\n        for row in candidates:\n            if normalize_name(row.get("channel", "")) == target_name:\n                return row\n    return None\n''',
    '''def _logo_match_name(value: object) -> str:\n    name = normalize_name(value)\n    # Research labels can retain a harmless provider/feed discriminator even when\n    # publication has already collapsed it to the logical channel identity.\n    name = re.sub(r"\\bfeed\\s+\\d+\\b", " ", name, flags=re.I)\n    return " ".join(name.split())\n\n\ndef _best_logo_row(rows: list[dict]) -> dict | None:\n    if not rows:\n        return None\n    quality_rank = {"Canonical": 2, "Source fallback": 1, "Missing": 0}\n    return max(rows, key=lambda row: quality_rank.get(str(row.get("quality_category") or ""), -1))\n\n\ndef _logo_row_for_target(target: dict, logo_rows: list[dict]) -> dict | None:\n    country = str(target.get("country") or "").strip().upper()\n    same_country = [\n        row for row in logo_rows\n        if str(row.get("country_code") or "").strip().upper() == country\n    ]\n    target_id = normalize_tvg_id(target.get("tvg_id", ""))\n    if target_id:\n        exact_same_country = [\n            row for row in same_country\n            if normalize_tvg_id(row.get("tvg_id", "")) == target_id\n        ]\n        if exact_same_country:\n            return _best_logo_row(exact_same_country)\n\n        # Priority coverage follows the research/audit geography, while logo quality\n        # follows the final published geography. An explicit routing can therefore\n        # move the same logical service between country buckets. Exact tvg-id remains\n        # strong enough identity evidence to bridge that reporting boundary.\n        exact_any_country = [\n            row for row in logo_rows\n            if normalize_tvg_id(row.get("tvg_id", "")) == target_id\n        ]\n        if exact_any_country:\n            return _best_logo_row(exact_any_country)\n\n    target_name = _logo_match_name(target.get("channel", ""))\n    if target_name:\n        same_name_country = [\n            row for row in same_country\n            if _logo_match_name(row.get("channel", "")) == target_name\n        ]\n        if same_name_country:\n            return _best_logo_row(same_name_country)\n    return None\n''',
)

replace_once(
    'tests/test_priority_coverage.py',
    '''    def test_injects_prominent_scorecard_before_next_work(self):\n''',
    '''    def test_logo_score_bridges_published_country_for_exact_tvg_identity(self):\n        rows = [\n            audit_row("AMC Europe Czech Republic", "AMCEurope.uk@CzechRepublic", "SK", stable=True),\n            audit_row("Disney Channel Feed 1", "DisneyChannel.cz@SD", "HU", stable=True),\n        ]\n        config = {\n            "country_names": {"HU": "Hungary", "SK": "Slovakia"},\n            "country_outputs": {"HU": "public/hu.m3u", "SK": "public/sk.m3u"},\n        }\n        policy = {\n            "schema_version": 1,\n            "default_priority": "P3",\n            "entries": [\n                {"country": "SK", "channel": "AMC Europe Czech Republic", "priority": "P2"},\n                {"country": "HU", "channel": "Disney Channel Feed 1", "priority": "P2"},\n            ],\n        }\n        logos = {\n            "channels": [\n                {\n                    "country_code": "CZ",\n                    "channel": "AMC Europe Czech Republic",\n                    "tvg_id": "AMCEurope.uk@CzechRepublic",\n                    "quality_category": "Canonical",\n                },\n                {\n                    "country_code": "HU",\n                    "channel": "Disney Channel",\n                    "tvg_id": "DisneyChannel.hu@SD",\n                    "quality_category": "Source fallback",\n                },\n            ]\n        }\n\n        coverage = build_priority_coverage(\n            rows,\n            config=config,\n            priority_policy=policy,\n            wanted_channels=[],\n            logo_quality=logos,\n        )\n\n        summary = coverage["logo_summary"]\n        self.assertEqual(summary["stable_targets"], 2)\n        self.assertEqual(summary["with_logo"], 2)\n        self.assertEqual(summary["canonical_logo"], 1)\n        self.assertEqual(summary["source_fallback"], 1)\n        self.assertEqual(summary["missing_logo"], 0)\n        self.assertEqual(summary["logo_availability_percent"], 100.0)\n\n    def test_injects_prominent_scorecard_before_next_work(self):\n''',
)
