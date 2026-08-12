import json
import unittest
from pathlib import Path

from country_language import (
    country_code_from_tvg_id,
    source_country_code,
    source_country_mode,
)


ROOT = Path(__file__).resolve().parents[1]


class LanguageSourceCountryDerivationTests(unittest.TestCase):
    def test_country_is_derived_from_iptv_org_tvg_id(self):
        self.assertEqual(country_code_from_tvg_id("Duna.hu@SD"), "HU")
        self.assertEqual(country_code_from_tvg_id("PannonRTV.rs@HD"), "RS")
        self.assertEqual(country_code_from_tvg_id("AMCEurope.uk@Hungary"), "UK")
        self.assertEqual(country_code_from_tvg_id("NoCountrySuffix"), "")

    def test_language_wide_sources_have_no_fixed_country(self):
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        language_sources = [
            source
            for source in cfg.get("sources", [])
            if isinstance(source, dict)
            and "/languages/" in str(source.get("url") or "")
        ]
        self.assertTrue(language_sources)
        for source in language_sources:
            self.assertEqual(source_country_mode(source), "tvg_id")
            self.assertNotIn("country_code", source)
            self.assertEqual(source_country_code(source, cfg), "")
            self.assertTrue(source.get("language_codes"))

    def test_invalid_country_mode_is_rejected(self):
        with self.assertRaises(RuntimeError):
            source_country_mode({"country_mode": "guess-from-language"})


if __name__ == "__main__":
    unittest.main()
