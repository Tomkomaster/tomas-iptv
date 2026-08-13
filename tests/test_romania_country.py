import json
import unittest
from pathlib import Path

import build
from wanted_channels import load_wanted_channels


class RomaniaCountryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))

    def test_romania_is_a_first_class_country_and_language_output(self):
        self.assertEqual(self.cfg["country_names"]["RO"], "Romania")
        self.assertEqual(self.cfg["country_outputs"]["RO"], "public/ro.m3u")
        self.assertEqual(self.cfg["language_names"]["ron"], "Romanian")
        self.assertEqual(
            self.cfg["language_outputs"]["ron"],
            "public/by-language/ron.m3u",
        )
        self.assertEqual(self.cfg["country_language_defaults"]["RO"], ["ron"])

    def test_romania_has_country_raw_language_and_manual_sources(self):
        source_names = {source["name"] for source in self.cfg["sources"]}
        self.assertIn("IPTV-org Romania", source_names)
        self.assertIn("IPTV-org Romania raw alternatives", source_names)
        self.assertIn("IPTV-org Romanian language", source_names)

        extras = {
            extra["path"]: extra
            for extra in self.cfg["extras"]
        }
        self.assertEqual(extras["extras/ro.m3u"]["country_code"], "RO")
        self.assertEqual(extras["extras/ro.m3u"]["language_codes"], ["ron"])

    def test_romania_has_dedicated_epg_configuration(self):
        epg = self.cfg["epg"]["countries"]["RO"]
        self.assertEqual(epg["sites"], ["epgshare01.online"])
        self.assertTrue(epg["external"]["url"].endswith("epg_ripper_RO1.xml.gz"))

    def test_hungarian_language_does_not_move_romanian_channel_without_route(self):
        candidate = {
            "channel_name": "Erdely Demo",
            "channel_key": "erdely-demo",
            "country_code": "RO",
            "language_code": "RO",
            "language_codes": ["ron"],
            "_decision": "Verified",
            "_audit": {
                "decision": "Verified",
                "observed_language_codes": ["HU"],
            },
        }

        routed = build.route_candidates_to_verified_countries([candidate], self.cfg)

        self.assertEqual(len(routed), 1)
        self.assertEqual(routed[0]["country_code"], "RO")
        self.assertEqual(routed[0]["language_codes"], ["hun"])
        self.assertEqual(
            build.entries_for_spoken_language(routed, "hun"),
            routed,
        )

    def test_romanian_wanted_catalog_only_tracks_missing_or_unusable_sources(self):
        wanted = load_wanted_channels(Path("data/wanted_channels.json"))
        romanian = [row for row in wanted if row["country_code"] == "RO"]

        self.assertGreaterEqual(len(romanian), 50)
        self.assertLess(len(romanian), 100)

        by_name = {row["channel"]: row for row in romanian}

        # Missing major stations remain research targets.
        self.assertEqual(by_name["Pro TV"]["priority"], "P1")
        self.assertEqual(by_name["Antena 1"]["priority"], "P1")
        self.assertEqual(by_name["Erdély TV"]["priority"], "P3")

        # Stations already supplied by the configured IPTV-org Romanian sources
        # must not clutter the wanted/research catalog.
        for supplied in (
            "TVR 1",
            "TVR 2",
            "TVR 3",
            "TVR Info",
            "TVR Sport",
            "Digi 24",
            "Kanal D",
            "Kanal D2",
            "Realitatea Plus",
            "Kiss TV",
            "Magic TV",
            "Rock TV",
            "Aleph News",
            "Aleph Business",
        ):
            self.assertNotIn(supplied, by_name)

        # A source may still be wanted if the only upstream candidate is
        # explicitly unusable for normal access.
        self.assertIn("geo-blocked", by_name["TeleMoldova Plus"]["reason"])
        self.assertIn("geo-blocked", by_name["TV SUD"]["reason"])


if __name__ == "__main__":
    unittest.main()
