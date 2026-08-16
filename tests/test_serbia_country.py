import json
import unittest
from pathlib import Path

import build
from tools.priority_coverage import build_priority_coverage, render_priority_coverage_html
from wanted_channels import load_wanted_channels


class SerbiaCountryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))

    def test_serbia_is_a_first_class_country_and_language_output(self):
        self.assertEqual(self.cfg["country_names"]["RS"], "Serbia")
        self.assertEqual(self.cfg["country_outputs"]["RS"], "public/rs.m3u")
        self.assertEqual(self.cfg["language_names"]["srp"], "Serbian")
        self.assertEqual(
            self.cfg["language_outputs"]["srp"],
            "public/by-language/srp.m3u",
        )
        self.assertEqual(self.cfg["country_language_defaults"]["RS"], ["srp"])

    def test_serbia_has_country_raw_language_and_manual_sources(self):
        sources = {source["name"]: source for source in self.cfg["sources"]}
        self.assertIn("IPTV-org Serbia", sources)
        self.assertIn("IPTV-org Serbia raw alternatives", sources)
        self.assertIn("IPTV-org Serbian language", sources)
        self.assertEqual(sources["IPTV-org Serbia"]["country_code"], "RS")
        self.assertEqual(sources["IPTV-org Serbia"]["language_codes"], ["srp"])
        self.assertEqual(
            sources["IPTV-org Serbian language"]["country_mode"],
            "tvg_id",
        )

        extras = {extra["path"]: extra for extra in self.cfg["extras"]}
        self.assertEqual(extras["extras/rs.m3u"]["country_code"], "RS")
        self.assertEqual(extras["extras/rs.m3u"]["language_codes"], ["srp"])
        self.assertTrue(Path("extras/rs.m3u").is_file())

    def test_serbia_has_dedicated_epg_configuration(self):
        epg = self.cfg["epg"]["countries"]["RS"]
        self.assertEqual(epg["sites"], ["mts.rs"])
        self.assertEqual(epg["external"]["provider"], "epgshare01.online")
        self.assertTrue(epg["external"]["url"].endswith("epg_ripper_RS1.xml.gz"))

    def test_serbian_language_does_not_move_channel_out_of_serbia_without_route(self):
        candidate = {
            "channel_name": "Serbian Demo",
            "channel_key": "serbian-demo",
            "country_code": "RS",
            "language_code": "RS",
            "language_codes": ["srp"],
            "_decision": "Verified",
            "_audit": {
                "decision": "Verified",
                "observed_language_codes": ["srp"],
            },
        }

        routed = build.route_candidates_to_verified_countries([candidate], self.cfg)

        self.assertEqual(len(routed), 1)
        self.assertEqual(routed[0]["country_code"], "RS")
        self.assertEqual(routed[0]["language_codes"], ["srp"])
        self.assertEqual(build.entries_for_spoken_language(routed, "srp"), routed)

    def test_serbian_research_catalog_tracks_failed_and_missing_channels(self):
        path = Path("data/wanted_channels_rs.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(len(payload["channels"]), 80)

        names = {row["channel"] for row in payload["channels"]}
        self.assertIn("Arena Sport 2 Premium", names)
        self.assertIn("Pink", names)
        self.assertIn("RTS 1", names)
        self.assertIn("RTV Bap", names)
        self.assertIn("TV Pirot", names)
        self.assertIn("B92", names)
        self.assertIn("Happy", names)
        self.assertIn("N1", names)
        self.assertIn("TV Studio B", names)
        self.assertIn("TV Panonija", names)
        self.assertNotIn("TV Kanal 9", names)
        self.assertNotIn("TV Šabac", names)
        self.assertNotIn("AXN Adria", names)
        self.assertNotIn("RTV Novi Pazar", names)
        self.assertNotIn("Regionalna TV", names)
        self.assertNotIn("TV Panon", names)
        self.assertNotIn("Pannon RTV", names)
        self.assertNotIn("Nova", names)

        wanted = load_wanted_channels(Path("data/wanted_channels.json"))
        serbian = [row for row in wanted if row["country_code"] == "RS"]
        self.assertEqual(len(serbian), 80)
        self.assertEqual({row["channel"] for row in serbian}, names)

    def test_serbia_is_present_in_dashboard_priority_report_with_flag(self):
        coverage = build_priority_coverage(
            [],
            config=self.cfg,
            priority_policy={
                "schema_version": 1,
                "default_priority": "P3",
                "entries": [],
            },
            wanted_channels=[],
        )

        self.assertIn("RS", coverage["countries"])
        serbia = coverage["countries"]["RS"]
        self.assertEqual(serbia["name"], "Serbia")
        self.assertEqual(serbia["priorities"]["P1"]["total"], 0)
        self.assertEqual(serbia["priorities"]["P2"]["total"], 0)

        rendered = render_priority_coverage_html({"countries": {"RS": serbia}})
        self.assertIn("🇷🇸 Serbia", rendered)
        self.assertNotIn("🌐 Serbia", rendered)


if __name__ == "__main__":
    unittest.main()
