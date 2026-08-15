import json
import unittest
from pathlib import Path

import build
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

    def test_serbia_has_initial_wanted_channel_catalog(self):
        wanted = load_wanted_channels(Path("data/wanted_channels.json"))
        serbian = [row for row in wanted if row["country_code"] == "RS"]

        self.assertEqual(len(serbian), 45)
        self.assertTrue(
            all(row["priority"] in {"P1", "P2", "P3", "P4"} for row in serbian)
        )

        by_name = {row["channel"]: row for row in serbian}
        self.assertEqual(by_name["RTS 1"]["priority"], "P1")
        self.assertEqual(by_name["Pink"]["priority"], "P1")
        self.assertEqual(by_name["N1"]["priority"], "P1")
        self.assertEqual(by_name["Arena Sport 1"]["priority"], "P2")
        self.assertEqual(by_name["Novosadska TV"]["priority"], "P3")
        self.assertEqual(by_name["TV Priboj"]["priority"], "P4")


if __name__ == "__main__":
    unittest.main()
