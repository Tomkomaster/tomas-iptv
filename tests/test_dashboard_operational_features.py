import tempfile
import unittest
from pathlib import Path

from attention import make_base_item
from build import make_dashboard
from healthcheck import read_playlist


class DashboardOperationalFeatureTests(unittest.TestCase):
    def dashboard(self):
        return make_dashboard(
            cfg={
                "site_title": "Test IPTV",
                "country_outputs": {"HU": "public/hu.m3u", "SK": "public/sk.m3u", "CZ": "public/cz.m3u"},
                "epg": {"enabled": False},
            },
            generated="2026-08-12 09:00:00 UTC",
            final_entries=[{
                "classification": "Base channel",
                "source": "HU source",
                "channel_name": "Demo TV",
                "tvg_id": "Demo.hu",
                "group_title": "Hungary | General",
                "url": "https://example.test/demo.m3u8",
                "language_code": "HU",
            }],
            unique_channels=[{"channel_name": "Demo TV"}],
            source_stats=[{
                "name": "HU source",
                "language_code": "HU",
                "kind": "base",
                "raw_entries": 4,
                "unique_channels_in_source": 3,
                "kept_stream_urls": 2,
                "base_channels_contributed": 2,
                "added_channels_contributed": 0,
                "alternative_streams": 0,
                "duplicate_urls_ignored": 2,
            }],
            language_stats=[{
                "language_code": "HU",
                "source_count": 1,
                "base_source_count": 1,
                "unique_channels": 1,
                "stream_urls": 1,
                "base_channels": 1,
                "added_channels": 0,
                "alternative_streams": 0,
            }],
            duplicate_rows=[],
            changes={"previous_generated_at": None, "added_channels": [], "removed_channels": []},
            audit_rows=[{
                "channel": "Demo TV",
                "feed_label": "Single",
                "tvg_id": "Demo.hu",
                "source": "HU source",
                "discovery": "base",
                "protocol": "HLS",
                "playlist_language_code": "HU",
                "output_language_code": "HU",
                "expected_language_codes": ["HU"],
                "observed_language_codes": [],
                "language_acceptance": "unknown",
                "provenance": "Upstream",
                "source_flags": [],
                "vlc": "not_tested",
                "vlc_note": "",
                "samsung": "not_tested",
                "samsung_note": "",
                "decision": "Needs review",
                "in_playlist": True,
                "in_stable_playlist": False,
                "reason": "",
                "notes": "",
                "stream_url": "https://example.test/demo.m3u8",
            }],
            audit_ambiguity_warnings=["Demo TV became ambiguous after 2 feeds."],
        )

    def test_dashboard_has_country_operations_sections(self):
        page = self.dashboard()
        self.assertIn('data-country-tab="ALL"', page)
        self.assertIn('data-country-tab="HU"', page)
        self.assertIn('data-country="HU"', page)
        self.assertIn("Conflicting identities", page)
        self.assertIn("Candidate streams to test", page)
        self.assertIn("Health by country", page)
        self.assertIn("Source contribution and yield", page)
        self.assertIn("50.0%", page)
        self.assertIn("Demo TV became ambiguous after 2 feeds", page)

    def test_dashboard_js_uses_generated_country_and_research_data(self):
        script = Path("static/dashboard.js").read_text(encoding="utf-8")
        self.assertIn("selectedCountry", script)
        self.assertIn("fetch('research.csv'", script)
        self.assertIn("fetch('missing.csv'", script)
        self.assertIn("healthCountrySummary", script)
        self.assertIn("candidateNeedsTest", script)

    def test_stable_playlist_prefix_preserves_health_country(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stable.m3u"
            path.write_text(
                '#EXTM3U\n#EXTINF:-1 tvg-id="Prima.cz",[CZ] Prima\nhttps://example.test/prima.m3u8\n',
                encoding="utf-8",
            )
            rows = read_playlist(path)
        self.assertEqual(rows[0]["channel"], "Prima")
        self.assertEqual(rows[0]["language_code"], "CZ")

    def test_attention_base_item_preserves_published_country(self):
        item = make_base_item({
            "channel": "Cross-language TV",
            "playlist_language_code": "SK",
            "output_language_code": "CZ",
        })
        self.assertEqual(item["country"], "CZ")


if __name__ == "__main__":
    unittest.main()
