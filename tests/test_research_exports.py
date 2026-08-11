import csv
import tempfile
import unittest
from pathlib import Path

import research_exports


FIELDNAMES = [
    "channel",
    "feed_label",
    "feed_index",
    "feed_count",
    "tvg_id",
    "source",
    "discovery",
    "stream_url",
    "protocol",
    "expected_language_codes",
    "observed_language_codes",
    "language_match",
    "language",
    "language_code",
    "provenance",
    "source_flags",
    "vlc",
    "vlc_note",
    "samsung",
    "samsung_note",
    "decision",
    "exclude_from_playlist",
    "in_playlist",
    "in_stable_playlist",
    "tested_on",
    "reason",
    "notes",
]


def row(**kwargs):
    base = {
        "channel": "Demo TV",
        "feed_label": "Single",
        "feed_index": "1",
        "feed_count": "1",
        "tvg_id": "DemoTV.hu",
        "source": "Source A",
        "discovery": "Source A",
        "stream_url": "https://example.test/live.m3u8",
        "protocol": "HLS",
        "expected_language_codes": "HU",
        "observed_language_codes": "HU",
        "language_match": "yes",
        "language": "Hungarian",
        "language_code": "HU",
        "provenance": "Test",
        "source_flags": "",
        "vlc": "not_tested",
        "vlc_note": "",
        "samsung": "not_tested",
        "samsung_note": "",
        "decision": "Needs review",
        "exclude_from_playlist": "False",
        "in_playlist": "True",
        "in_stable_playlist": "False",
        "tested_on": "",
        "reason": "",
        "notes": "",
    }
    base.update(kwargs)
    return base


class ResearchExportTests(unittest.TestCase):
    def write_fixture(self, public_dir: Path) -> None:
        rows = [
            row(
                channel="TV2",
                tvg_id="TV2.hu",
                stream_url="https://example.test/tv2.m3u8",
                vlc="works",
                samsung="works",
                decision="Verified",
                in_stable_playlist="True",
                tested_on="2026-08-10",
            ),
            row(
                channel="RTL Klub",
                tvg_id="RTLKlub.hu",
                language_code="DE",
                expected_language_codes="HU",
                observed_language_codes="DE",
                language_match="no",
                stream_url="https://example.test/rtl.m3u8",
                vlc="mrl_error",
                samsung="generic_error",
                decision="Rejected",
                exclude_from_playlist="True",
                tested_on="2026-08-09",
            ),
            row(
                channel="Spektrum",
                tvg_id="Spektrum.hu",
                stream_url="https://example.test/spektrum.m3u8",
                decision="Needs review",
            ),
            row(
                channel="Film+",
                tvg_id="FilmPlus.hu",
                stream_url="https://example.test/filmplus.m3u8",
                vlc="works",
                samsung="format_error",
                decision="PC only",
                tested_on="2026-08-08",
            ),
            row(
                channel="RTL Klub",
                tvg_id="RTLKlub.hu",
                source="Old source",
                stream_url="https://old.example.test/rtl.m3u8",
                vlc="generic_error",
                samsung="generic_error",
                decision="Rejected",
                in_playlist="False",
                tested_on="2026-07-01",
            ),
            row(
                channel="Markiza",
                tvg_id="Markiza.sk",
                language_code="SK",
                expected_language_codes="SK",
                observed_language_codes="SK",
                stream_url="https://example.test/markiza.m3u8",
                vlc="works",
                samsung="works",
                decision="Verified",
                in_stable_playlist="True",
                tested_on="2026-08-10",
            ),
        ]

        with (public_dir / "audit.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)

        (public_dir / "index.html").write_text(
            '<div class="links">\n'
            '    <a href="audit.csv">Manual verification (CSV)</a>\n'
            '    <a href="report.json">Machine report (JSON)</a>\n'
            '</div>\n',
            encoding="utf-8",
        )

    def test_exports_and_dashboard_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            public_dir = Path(tmp)
            self.write_fixture(public_dir)

            stats = research_exports.generate_exports(
                public_dir,
                generated_at="2026-08-11 10:00:00 UTC",
            )

            self.assertEqual(stats["channels"], 5)
            self.assertEqual(stats["research_rows"], 6)
            self.assertEqual(stats["missing_channels"], 3)

            with (public_dir / "research.csv").open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                research_rows = list(csv.DictReader(handle))

            statuses = {}
            countries = {}
            for item in research_rows:
                statuses.setdefault(item["channel"], item["channel_status"])
                countries.setdefault(item["channel"], item["country"])

            self.assertEqual(statuses["TV2"], "WORKING")
            self.assertEqual(statuses["RTL Klub"], "NO WORKING FEED")
            self.assertEqual(statuses["Spektrum"], "CANDIDATES TO TEST")
            self.assertEqual(statuses["Film+"], "PARTIAL")
            self.assertEqual(statuses["Markiza"], "WORKING")
            self.assertEqual(countries["RTL Klub"], "HU")

            with (public_dir / "missing.csv").open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                missing_rows = list(csv.DictReader(handle))

            missing_names = {item["channel"] for item in missing_rows}
            self.assertEqual(missing_names, {"RTL Klub", "Spektrum", "Film+"})

            rtl = next(item for item in missing_rows if item["channel"] == "RTL Klub")
            self.assertEqual(rtl["country"], "HU")
            self.assertEqual(rtl["known_feeds"], "2")
            self.assertEqual(rtl["rejected_feeds"], "2")
            self.assertEqual(rtl["last_tested"], "2026-08-09")
            self.assertIn("Hunt for a new source/feed", rtl["next_action"])

            research_md = (public_dir / "research.md").read_text(encoding="utf-8")
            self.assertIn("# HU", research_md)
            self.assertIn("# SK", research_md)
            self.assertNotIn("# DE", research_md)
            self.assertIn("## ✅ TV2", research_md)
            self.assertIn("## ❌ RTL Klub", research_md)
            self.assertIn("https://example.test/tv2.m3u8", research_md)
            self.assertIn("https://old.example.test/rtl.m3u8", research_md)

            index_html = (public_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn('href="research.csv"', index_html)
            self.assertIn('href="research.md"', index_html)
            self.assertIn('href="missing.csv"', index_html)

            research_exports.inject_dashboard_links(public_dir / "index.html")
            index_html_again = (public_dir / "index.html").read_text(encoding="utf-8")
            self.assertEqual(index_html_again.count('href="research.csv"'), 1)
            self.assertEqual(index_html_again.count('href="research.md"'), 1)
            self.assertEqual(index_html_again.count('href="missing.csv"'), 1)


if __name__ == "__main__":
    unittest.main()
