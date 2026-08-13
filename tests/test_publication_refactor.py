import unittest
from pathlib import Path

import build
from iptv import publication

MOVED = ('normalize_content_group', 'rewrite_extinf_line', 'rewrite_entry_lines', 'playlist_status_suffix', 'prepare_published_entries')


class PublicationRefactorTests(unittest.TestCase):
    def test_build_reexports_publication_api(self):
        for name in MOVED:
            self.assertIs(getattr(build, name), getattr(publication, name), name)

    def test_core_no_longer_defines_publication_logic(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        for name in MOVED:
            self.assertNotIn(f"def {name}(", text, name)

    def test_group_normalization_stays_idempotent(self):
        self.assertEqual(
            publication.normalize_content_group(
                "Hungary | News", country_name="Hungary", language_code="HU"
            ),
            "News",
        )
        self.assertEqual(
            publication.normalize_content_group(
                "HU | Verified", country_name="Hungary", language_code="HU"
            ),
            "General",
        )

    def test_extinf_rewrite_cleans_internal_tvg_name(self):
        line = '#EXTINF:-1 tvg-name="JOJ Sport ANTIK TEST" group-title="Sports",JOJ Sport ANTIK TEST'
        result = publication.rewrite_extinf_line(line, "[SK OK] JOJ Sport", "Slovakia | Sports")
        self.assertIn('tvg-name="JOJ Sport"', result)
        self.assertIn('group-title="Slovakia | Sports"', result)
        self.assertTrue(result.endswith(",[SK OK] JOJ Sport"))

    def test_prepare_published_entries_numbers_alternative_feeds(self):
        entries = [
            {
                "url": "https://example.test/a1.m3u8",
                "country_code": "HU",
                "country_name": "Hungary",
                "canonical_id": "demo",
                "channel_name": "Demo TV",
                "display_name": "Demo TV",
                "source_group_title": "News",
                "lines": ['#EXTINF:-1 group-title="News",Demo TV', "https://example.test/a1.m3u8"],
                "_decision": "Verified",
                "_source_order": 0,
            },
            {
                "url": "https://example.test/a2.m3u8",
                "country_code": "HU",
                "country_name": "Hungary",
                "canonical_id": "demo",
                "channel_name": "Demo TV",
                "display_name": "Demo TV",
                "source_group_title": "News",
                "lines": ['#EXTINF:-1 group-title="News",Demo TV', "https://example.test/a2.m3u8"],
                "_decision": "Verified",
                "_source_order": 1,
            },
        ]
        out = publication.prepare_published_entries(entries, {"country_names": {"HU": "Hungary"}})
        self.assertEqual([item["published_name"] for item in out], ["[HU OK] Demo TV", "[HU OK] Demo TV Feed 2"])


if __name__ == "__main__":
    unittest.main()
