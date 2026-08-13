import csv
import tempfile
import unittest
from pathlib import Path

import build
from iptv import reports


EXTRACTED_NAMES = ('summarize_country_stats', 'summarize_language_stats', 'safe_csv_value', 'write_csv')


class ReportsRefactorTests(unittest.TestCase):
    def test_build_reexports_reports_api(self):
        for name in EXTRACTED_NAMES:
            self.assertIs(getattr(build, name), getattr(reports, name), name)

    def test_build_core_no_longer_defines_report_helpers(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        for name in EXTRACTED_NAMES:
            self.assertNotIn(f"def {name}(", text, name)

    def test_country_and_language_summaries(self):
        entries = [
            {
                "country_code": "HU",
                "language_codes": ["hun"],
                "channel_key": "id:alpha.hu",
                "classification": "Base channel",
            },
            {
                "country_code": "HU",
                "language_codes": ["hun"],
                "channel_key": "id:beta.hu",
                "classification": "Added channel",
            },
        ]
        sources = [
            {"country_code": "HU", "language_codes": ["hun"], "kind": "base"},
            {"country_code": "HU", "language_codes": ["hun"], "kind": "extras"},
        ]
        country = reports.summarize_country_stats(entries, sources)[0]
        language = reports.summarize_language_stats(entries, sources)[0]
        self.assertEqual(country["country_code"], "HU")
        self.assertEqual(country["unique_channels"], 2)
        self.assertEqual(country["base_channels"], 1)
        self.assertEqual(country["added_channels"], 1)
        self.assertEqual(language["language_code"], "hun")
        self.assertEqual(language["unique_channels"], 2)

    def test_write_csv_sanitizes_newlines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            reports.write_csv(path, ["name", "note"], [{"name": "Demo", "note": "a\nb"}])
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(rows, [{"name": "Demo", "note": "a b"}])


if __name__ == "__main__":
    unittest.main()
