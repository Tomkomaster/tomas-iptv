import unittest
from pathlib import Path

import build
from iptv import language_routing

MOVED = ('country_name_for_code', 'country_name_for_language', 'route_candidates_to_verified_countries', 'route_candidates_to_verified_languages', 'build_language_catalog_entries', 'entries_for_spoken_language')


class LanguageRoutingCompletionTests(unittest.TestCase):
    def test_build_reexports_remaining_routing_helpers(self):
        for name in MOVED:
            self.assertIs(getattr(build, name), getattr(language_routing, name), name)

    def test_core_no_longer_defines_remaining_routing_helpers(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        for name in MOVED:
            self.assertNotIn(f"def {name}(", text, name)

    def test_language_catalog_keeps_country_authority_and_merges_languages(self):
        country = [{"url": "https://example.test/a.m3u8", "country_code": "RS", "language_codes": ["srp"]}]
        language = [{"url": "https://example.test/a.m3u8", "country_code": "HU", "language_codes": ["hun"]}]
        result = language_routing.build_language_catalog_entries(country, language)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["country_code"], "RS")
        self.assertEqual(result[0]["language_codes"], ["srp", "hun"])

    def test_country_name_uses_configured_name(self):
        cfg = {"country_names": {"CZ": "Czechia"}}
        self.assertEqual(language_routing.country_name_for_code(cfg, "CZ"), "Czechia")


if __name__ == "__main__":
    unittest.main()
