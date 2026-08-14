import json
import unittest
from pathlib import Path


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
        extras = {
            extra["path"]: extra
            for extra in self.cfg["extras"]
        }
        self.assertEqual(extras["extras/at.m3u"]["country_code"], "AT")
        self.assertEqual(extras["extras/at.m3u"]["language_codes"], ["deu"])
        self.assertTrue(Path("extras/at.m3u").is_file())

    def test_austria_has_dedicated_external_epg_configuration(self):
        epg = self.cfg["epg"]["countries"]["AT"]
        self.assertEqual(epg["sites"], ["epgshare01.online"])
        self.assertEqual(epg["external"]["provider"], "epgshare01.online")
        self.assertTrue(epg["external"]["url"].endswith("epg_ripper_AT1.xml.gz"))


if __name__ == "__main__":
    unittest.main()
