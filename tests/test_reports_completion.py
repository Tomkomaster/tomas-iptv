import json
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
