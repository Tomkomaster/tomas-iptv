#!/usr/bin/env python3
from pathlib import Path


def replace_exact(path: str, old: str, new: str, expected: int = 1) -> None:
    target = Path(path)
    text = target.read_text(encoding='utf-8')
    count = text.count(old)
    if count != expected:
        raise SystemExit(f'{path}: expected {expected} marker(s), found {count}')
    target.write_text(text.replace(old, new), encoding='utf-8')


replace_exact(
    'tools/attention.py',
    'from healthcheck import canonical_stream_url\nfrom epg_policy import compile_epg_policy, resolve_epg_policy\n',
    'from healthcheck import canonical_stream_url\nfrom epg_policy import compile_epg_policy, resolve_epg_policy\nfrom epg.epg_quality import build_epg_quality, write_epg_quality_outputs\n',
)

marker = '''def main() -> None:\n'''
helper = '''def write_epg_quality_side_reports(\n    *,\n    report: dict,\n    epg_coverage: dict,\n    epg_health: dict,\n    epg_policy: dict,\n    config: dict,\n    output_dir: Path,\n) -> dict | None:\n    \"\"\"Write EPG identity-quality reports beside attention.json when EPG is enabled.\"\"\"\n    if not bool((config.get(\"epg\") or {}).get(\"enabled\")):\n        return None\n    if not epg_coverage:\n        return None\n\n    quality = build_epg_quality(\n        report,\n        epg_coverage,\n        health=epg_health,\n        policy_payload=epg_policy,\n    )\n    write_epg_quality_outputs(\n        quality,\n        output_path=output_dir / \"epg-quality.json\",\n        collisions_csv_path=output_dir / \"tvg-id-collisions.csv\",\n        verified_missing_csv_path=output_dir / \"verified-without-epg.csv\",\n    )\n    return quality\n\n\n'''
replace_exact('tools/attention.py', marker, helper + marker)

old = '''    if not args.report.is_file():\n        raise SystemExit(f\"Attention report requires {args.report}.\")\n\n    result = build_attention(\n        load_json(args.report),\n        health=load_json(args.health),\n        epg_coverage=load_json(args.epg_coverage),\n        epg_health=load_json(args.epg_health),\n        epg_policy=load_json(args.epg_policy),\n        source_concentration=load_json(args.source_concentration),\n        config=load_json(args.config),\n    )\n'''
new = '''    if not args.report.is_file():\n        raise SystemExit(f\"Attention report requires {args.report}.\")\n\n    report = load_json(args.report)\n    health = load_json(args.health)\n    epg_coverage = load_json(args.epg_coverage)\n    epg_health = load_json(args.epg_health)\n    epg_policy = load_json(args.epg_policy)\n    source_concentration = load_json(args.source_concentration)\n    config = load_json(args.config)\n\n    quality = write_epg_quality_side_reports(\n        report=report,\n        epg_coverage=epg_coverage,\n        epg_health=epg_health,\n        epg_policy=epg_policy,\n        config=config,\n        output_dir=args.output.parent,\n    )\n    if quality is not None:\n        summary = quality.get(\"summary\") or {}\n        print(\n            \"EPG quality: \"\n            f\"{summary.get('epg_expected_with_programmes', 0)}/\"\n            f\"{summary.get('epg_expected_channels', 0)} expected logical channels complete \"\n            f\"({float(summary.get('epg_completeness_percent') or 0):.1f}%).\"\n        )\n        print(\n            \"tvg-id quality: \"\n            f\"{summary.get('exact_tvg_id', 0)} exact, \"\n            f\"{summary.get('alias', 0)} alias, \"\n            f\"{summary.get('guessed', 0)} guessed, \"\n            f\"{summary.get('missing', 0)} missing, \"\n            f\"{summary.get('epg_unavailable', 0)} EPG unavailable; \"\n            f\"{summary.get('tvg_id_collision_count', 0)} collisions, \"\n            f\"{summary.get('verified_without_epg_mapping_count', 0)} verified without mapping.\"\n        )\n\n    result = build_attention(\n        report,\n        health=health,\n        epg_coverage=epg_coverage,\n        epg_health=epg_health,\n        epg_policy=epg_policy,\n        source_concentration=source_concentration,\n        config=config,\n    )\n'''
replace_exact('tools/attention.py', old, new)

# The integration is now deliberately owned by the already-existing post-EPG attention step,
# so no permanent GitHub workflow edit is required.
path = Path('tests/test_epg_quality.py')
text = path.read_text(encoding='utf-8')
text = text.replace(
    '        workflow = (ROOT / ".github" / "workflows" / "build-and-publish.yml").read_text(encoding="utf-8")\n',
    '        attention = (ROOT / "tools" / "attention.py").read_text(encoding="utf-8")\n',
)
text = text.replace(
    '        self.assertIn("python3 -m epg.epg_quality", workflow)\n',
    '        self.assertIn("write_epg_quality_side_reports", attention)\n        self.assertIn("epg-quality.json", attention)\n',
)
path.write_text(text, encoding='utf-8')

# Add an integration test that proves the existing attention step writes all side reports.
path = Path('tests/test_epg_quality.py')
text = path.read_text(encoding='utf-8')
text = text.replace(
    'from epg.epg_quality import (\n',
    'from tools.attention import write_epg_quality_side_reports\nfrom epg.epg_quality import (\n',
)
needle = '''    def test_dashboard_exposes_quality_categories_and_reports(self):\n'''
test = '''    def test_attention_step_writes_epg_quality_side_reports(self):\n        report = {\n            \"channels\": [\n                {\"key\": \"HU:name:one\", \"name\": \"One\", \"country_code\": \"HU\", \"tvg_id\": \"One.hu\"},\n            ],\n            \"audit\": {\"channels\": [\n                {\"channel\": \"One\", \"country_code\": \"HU\", \"tvg_id\": \"One.hu\", \"decision\": \"Verified\", \"in_stable_playlist\": True},\n            ]},\n        }\n        coverage = {\"matched\": [\n            {\"tvg_id\": \"One.hu\", \"match_type\": \"exact\"},\n        ]}\n        with tempfile.TemporaryDirectory() as tmp:\n            root = Path(tmp)\n            quality = write_epg_quality_side_reports(\n                report=report,\n                epg_coverage=coverage,\n                epg_health={\"mapped_without_programmes\": []},\n                epg_policy={\"default\": \"expected\"},\n                config={\"epg\": {\"enabled\": True}},\n                output_dir=root,\n            )\n            self.assertIsNotNone(quality)\n            self.assertTrue((root / \"epg-quality.json\").is_file())\n            self.assertTrue((root / \"tvg-id-collisions.csv\").is_file())\n            self.assertTrue((root / \"verified-without-epg.csv\").is_file())\n\n'''
if text.count(needle) != 1:
    raise SystemExit('Could not locate dashboard test marker')
path.write_text(text.replace(needle, test + needle), encoding='utf-8')

print('Wired EPG quality generation into existing post-EPG attention step.')
