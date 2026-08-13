import json
import unittest
from pathlib import Path


class ConfigLanguageKeyTests(unittest.TestCase):
    def test_country_and_language_defaults_use_distinct_code_systems(self):
        cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
        legacy_key = "default_language_" + "code"

        self.assertNotIn(legacy_key, cfg)
        self.assertEqual(cfg["default_country_code"], "HU")
        self.assertEqual(cfg["default_language_codes"], ["hun"])

        configured_languages = set(cfg["language_outputs"])
        for code in cfg["default_language_codes"]:
            self.assertEqual(len(code), 3)
            self.assertIn(code, configured_languages)


if __name__ == "__main__":
    unittest.main()
