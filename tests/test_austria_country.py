import json
import unittest
from pathlib import Path

from tools.priority_coverage import render_priority_coverage_html


class AustriaCountryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))

    def test_austria_is_a_first_class_country_and_german_output(self):
        self.assertEqual(self.cfg["country_names"]["AT"], "Austria")
        self.assertEqual(self.cfg["country_outputs"]["AT"], "public/at.m3u")
        self.assertEqual(self.cfg["language_names"]["deu"], "German")
        self.assertEqual(
            self.cfg["language_outputs"]["deu"],
            "public/by-language/deu.m3u",
        )
        self.assertEqual(self.cfg["country_language_defaults"]["AT"], ["deu"])

    def test_austria_uses_only_country_and_raw_sources(self):
        source_names = {source["name"] for source in self.cfg["sources"]}
        self.assertIn("IPTV-org Austria", source_names)
        self.assertIn("IPTV-org Austria raw alternatives", source_names)

        german_language_sources = [
            source
            for source in self.cfg["sources"]
            if "/languages/deu.m3u" in str(source.get("url") or "")
        ]
        self.assertEqual(german_language_sources, [])
        self.assertNotIn("IPTV-org German language", source_names)

    def test_austria_has_manual_extras_bucket(self):
        extras = {extra["path"]: extra for extra in self.cfg["extras"]}
        self.assertEqual(extras["extras/at.m3u"]["country_code"], "AT")
        self.assertEqual(extras["extras/at.m3u"]["language_codes"], ["deu"])
        self.assertTrue(Path("extras/at.m3u").is_file())

    def test_austria_has_expanded_country_scoped_epg_configuration(self):
        epg = self.cfg["epg"]["countries"]["AT"]
        self.assertEqual(
            epg["sites"],
            [
                "tvheute.at",
                "pluto.tv/pluto.tv_de.channels.xml",
            ],
        )
        self.assertEqual(epg["external"]["provider"], "epgshare01.online")
        self.assertTrue(epg["external"]["url"].endswith("epg_ripper_AT1.xml.gz"))

    def test_austria_has_wanted_channel_catalog(self):
        path = Path("data/wanted_channels_at.json")
        self.assertTrue(path.is_file())
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertNotIn("replace_country", payload)

        channels = payload["channels"]
        self.assertTrue(channels)
        self.assertTrue(all(row["country_code"] == "AT" for row in channels))
        self.assertTrue(
            all(row["priority"] in {"P1", "P2", "P3", "P4"} for row in channels)
        )

        by_name = {row["channel"]: row for row in channels}
        self.assertEqual(by_name["ORF 1"]["priority"], "P1")
        self.assertEqual(by_name["PULS 4"]["priority"], "P1")
        self.assertEqual(by_name["ORF Sport+"]["priority"], "P2")
        self.assertEqual(by_name["RTS Regional TV Salzburg"]["priority"], "P3")
        self.assertEqual(by_name["KT1"]["priority"], "P3")
        self.assertEqual(by_name["Landeck TV"]["priority"], "P4")

    def test_priority_coverage_uses_austrian_flag(self):
        coverage = {
            "countries": {
                "AT": {
                    "name": "Austria",
                    "priorities": {
                        "P1": {"found": 0, "total": 0, "missing": []},
                        "P2": {"found": 0, "total": 0, "missing": []},
                    },
                }
            }
        }
        rendered = render_priority_coverage_html(coverage)
        self.assertIn("🇦🇹 Austria", rendered)
        self.assertNotIn("🌐 Austria", rendered)


if __name__ == "__main__":
    unittest.main()
