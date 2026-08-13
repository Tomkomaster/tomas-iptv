#!/usr/bin/env python3
"""Move remaining report state/export formatting out of build_core.py."""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "iptv" / "build_core.py"
REPORTS = ROOT / "iptv" / "reports.py"
TEST = ROOT / "tests" / "test_reports_completion.py"
DOCS = ROOT / "docs" / "build-structure.md"


def cut_block(source: str, start_marker: str, end_marker: str) -> tuple[str, str]:
    start = source.find(start_marker)
    end = source.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0 or end <= start:
        raise RuntimeError(f"Report block markers changed: {start_marker!r} -> {end_marker!r}")
    return source[:start] + source[end:], source[start:end]


def main() -> None:
    source = CORE.read_text(encoding="utf-8")
    before = len(source.encode("utf-8"))

    # 1. Audit playlist membership, unique-channel aggregation, country/language
    # summaries and previous-build channel diffing.
    context_start = "    stable_urls = {\n"
    context_end = "    out_path = ROOT / cfg.get(\n"
    context_start_pos = source.find(context_start)
    context_end_pos = source.find(context_end, context_start_pos)
    if context_start_pos < 0 or context_end_pos < 0:
        raise RuntimeError("Report context markers changed")
    context_block = textwrap.dedent(source[context_start_pos:context_end_pos])
    previous_line = 'previous_report = load_previous_report(cfg.get("previous_report_url"))\n'
    if previous_line not in context_block:
        raise RuntimeError("Previous report line changed")
    context_block = context_block.replace(previous_line, "", 1)
    context_function = '''def build_report_context(
    published_entries: list[dict],
    test_entries: list[dict],
    audit_rows: list[dict],
    source_stats: list[dict],
    previous_report: dict | None,
) -> tuple[list[dict], list[dict], list[dict], dict]:
    """Prepare mutable audit membership, channel inventory summaries and change diff."""
''' + textwrap.indent(context_block, "    ") + '''
    return unique_channels, country_stats, language_stats, changes
'''
    context_call = '''    previous_report = load_previous_report(cfg.get("previous_report_url"))
    unique_channels, country_stats, language_stats, changes = build_report_context(
        published_entries,
        test_entries,
        audit_rows,
        source_stats,
        previous_report,
    )

'''
    source = source[:context_start_pos] + context_call + source[context_end_pos:]

    # 2. CSV export shaping/writing.
    csv_start = "    inventory_rows = [\n"
    csv_end = "    report = {\n"
    csv_start_pos = source.find(csv_start)
    csv_end_pos = source.find(csv_end, csv_start_pos)
    if csv_start_pos < 0 or csv_end_pos < 0:
        raise RuntimeError("CSV export markers changed")
    csv_block = textwrap.dedent(source[csv_start_pos:csv_end_pos])
    csv_function = '''def write_build_csv_exports(
    public_dir: Path,
    published_entries: list[dict],
    duplicate_rows: list[dict],
    excluded_rows: list[dict],
    audit_rows: list[dict],
) -> None:
    """Write the generated channel, duplicate, exclusion and audit CSV exports."""
''' + textwrap.indent(csv_block, "    ")
    csv_call = '''    write_build_csv_exports(
        public_dir,
        published_entries,
        duplicate_rows,
        excluded_rows,
        audit_rows,
    )

'''
    source = source[:csv_start_pos] + csv_call + source[csv_end_pos:]

    # 3. Machine report JSON payload + write.
    report_start = "    report = {\n"
    report_end = "    copy_dashboard_assets(public_dir)\n"
    report_start_pos = source.find(report_start)
    report_end_pos = source.find(report_end, report_start_pos)
    if report_start_pos < 0 or report_end_pos < 0:
        raise RuntimeError("Machine report markers changed")
    report_block = textwrap.dedent(source[report_start_pos:report_end_pos])
    report_function = '''def write_machine_report(
    public_dir: Path,
    *,
    cfg: dict,
    generated: str,
    published_entries: list[dict],
    test_entries: list[dict],
    excluded_rows: list[dict],
    duplicate_rows: list[dict],
    source_stats: list[dict],
    country_stats: list[dict],
    language_stats: list[dict],
    source_concentration: dict,
    changes: dict,
    audit_warnings: list[str],
    audit_ambiguity_warnings: list[str],
    audit_rows: list[dict],
    unique_channels: list[dict],
    raw_identity_path: str,
    identity_registry,
    country_playlist_counts: dict[str, int],
    language_playlist_counts: dict[str, int],
) -> dict:
    """Build and write public/report.json, returning the payload for callers/tests."""
''' + textwrap.indent(report_block, "    ") + '''
    return report
'''
    report_call = '''    write_machine_report(
        public_dir,
        cfg=cfg,
        generated=generated,
        published_entries=published_entries,
        test_entries=test_entries,
        excluded_rows=excluded_rows,
        duplicate_rows=duplicate_rows,
        source_stats=source_stats,
        country_stats=country_stats,
        language_stats=language_stats,
        source_concentration=source_concentration,
        changes=changes,
        audit_warnings=audit_warnings,
        audit_ambiguity_warnings=audit_ambiguity_warnings,
        audit_rows=audit_rows,
        unique_channels=unique_channels,
        raw_identity_path=raw_identity_path,
        identity_registry=identity_registry,
        country_playlist_counts=country_playlist_counts,
        language_playlist_counts=language_playlist_counts,
    )

'''
    source = source[:report_start_pos] + report_call + source[report_end_pos:]

    # 4. Console build summary.
    console_start = '    print()\n    print("Build complete.")\n'
    console_end = '\n\nif __name__ == "__main__":\n'
    console_start_pos = source.find(console_start)
    console_end_pos = source.find(console_end, console_start_pos)
    if console_start_pos < 0 or console_end_pos < 0:
        raise RuntimeError("Console summary markers changed")
    console_block = textwrap.dedent(source[console_start_pos:console_end_pos])
    console_function = '''def print_build_summary(
    *,
    unique_channels: list[dict],
    published_entries: list[dict],
    test_entries: list[dict],
    excluded_rows: list[dict],
    duplicate_rows: list[dict],
    country_playlist_counts: dict[str, int],
    audit_rows: list[dict],
    source_stats: list[dict],
    country_stats: list[dict],
    language_stats: list[dict],
) -> None:
    """Print the human-readable build summary used by local runs and Actions logs."""
''' + textwrap.indent(console_block, "    ")
    console_call = '''    print_build_summary(
        unique_channels=unique_channels,
        published_entries=published_entries,
        test_entries=test_entries,
        excluded_rows=excluded_rows,
        duplicate_rows=duplicate_rows,
        country_playlist_counts=country_playlist_counts,
        audit_rows=audit_rows,
        source_stats=source_stats,
        country_stats=country_stats,
        language_stats=language_stats,
    )'''
    source = source[:console_start_pos] + console_call + source[console_end_pos:]

    # Import newly extracted reporting API through the historical core module.
    marker = "from iptv.reports import (\n"
    if marker not in source:
        raise RuntimeError("reports import block missing")
    additions = (
        "    build_report_context,\n"
        "    write_build_csv_exports,\n"
        "    write_machine_report,\n"
        "    print_build_summary,\n"
    )
    source = source.replace(marker, marker + additions, 1)

    reports = REPORTS.read_text(encoding="utf-8").rstrip()
    report_imports = "import json\nimport re\n"
    if "import json\n" not in reports:
        reports = reports.replace("import csv\n", "import csv\n" + report_imports, 1)
    dependency_import = '''from iptv.channel_identity import (
    canonical_stream_url,
    logical_channel_key,
    normalize_text,
)
from iptv.playback_status import is_tested_status
'''
    if "from iptv.channel_identity import" not in reports:
        marker = "from country_language import (\n"
        reports = reports.replace(marker, dependency_import + marker, 1)

    reports += "\n\n" + context_function.rstrip()
    reports += "\n\n" + csv_function.rstrip()
    reports += "\n\n" + report_function.rstrip()
    reports += "\n\n" + console_function.rstrip() + "\n"

    ast.parse(source)
    ast.parse(reports)
    CORE.write_text(source, encoding="utf-8")
    REPORTS.write_text(reports, encoding="utf-8")

    TEST.write_text(
        '''import json
import tempfile
import unittest
from pathlib import Path

import build
from iptv import reports


class ReportsCompletionTests(unittest.TestCase):
    def test_build_reexports_completed_reporting_api(self):
        for name in (
            "build_report_context",
            "write_build_csv_exports",
            "write_machine_report",
            "print_build_summary",
        ):
            self.assertIs(getattr(build, name), getattr(reports, name), name)

    def test_core_no_longer_owns_report_formatting_blocks(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        self.assertNotIn("inventory_rows = [", text)
        self.assertNotIn('"schema_version": 23', text)
        self.assertNotIn('print("Country summary:")', text)
        self.assertLess(Path("iptv/build_core.py").stat().st_size, 23_000)

    def test_report_context_marks_membership_and_builds_changes(self):
        published = [{
            "url": "https://example.test/a.m3u8",
            "country_code": "HU",
            "channel_key": "id:a.hu",
            "channel_name": "A",
            "canonical_id": "",
            "tvg_id": "A.hu",
            "source": "Fixture",
            "classification": "Base channel",
            "language_codes": ["hun"],
        }]
        test = list(published)
        audit = [{
            "stream_url": "https://example.test/a.m3u8",
            "in_playlist": True,
        }]
        previous = {"generated_at": "old", "channels": [{"key": "HU:id:old.hu", "name": "Old"}]}
        unique, countries, languages, changes = reports.build_report_context(
            published, test, audit, [], previous
        )
        self.assertTrue(audit[0]["in_playlist"])
        self.assertTrue(audit[0]["in_stable_playlist"])
        self.assertEqual(unique[0]["key"], "HU:id:a.hu")
        self.assertEqual(countries[0]["country_code"], "HU")
        self.assertEqual(languages[0]["language_code"], "hun")
        self.assertEqual(changes["added_channels"], ["A"])
        self.assertEqual(changes["removed_channels"], ["Old"])

    def test_machine_report_writer_preserves_schema(self):
        class Registry:
            identities = {"a": {}}
            selectors = [1]

        with tempfile.TemporaryDirectory() as tmp:
            public = Path(tmp)
            report = reports.write_machine_report(
                public,
                cfg={"output": "public/tv.m3u", "epg": {"enabled": False}},
                generated="2026-08-13 08:00:00 UTC",
                published_entries=[],
                test_entries=[],
                excluded_rows=[],
                duplicate_rows=[],
                source_stats=[],
                country_stats=[],
                language_stats=[],
                source_concentration={"summary": {}},
                changes={"previous_generated_at": None, "added_channels": [], "removed_channels": []},
                audit_warnings=[],
                audit_ambiguity_warnings=[],
                audit_rows=[],
                unique_channels=[],
                raw_identity_path="data/identity_overrides.json",
                identity_registry=Registry(),
                country_playlist_counts={},
                language_playlist_counts={},
            )
            saved = json.loads((public / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["schema_version"], 23)
        self.assertEqual(saved["schema_version"], 23)
        self.assertEqual(saved["identity"]["canonical_identities"], 1)


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )

    docs = DOCS.read_text(encoding="utf-8")
    marker = "- `reports.py` — country/language build summaries and CSV export helpers\n"
    replacement = (
        "- `reports.py` — channel/report context, previous-build diffing, country/language summaries, "
        "CSV/machine-report exports and console summaries\n"
    )
    if marker not in docs:
        raise RuntimeError("docs reports marker missing")
    DOCS.write_text(docs.replace(marker, replacement, 1), encoding="utf-8")

    print(f"Finished reports extraction: build_core.py {before:,} -> {CORE.stat().st_size:,} bytes")
    print(f"reports.py: {REPORTS.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
