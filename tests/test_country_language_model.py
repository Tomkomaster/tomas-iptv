import unittest

from country_language import (
    configured_country_codes,
    configured_language_codes,
    normalize_country_code,
    normalize_language_code,
    normalize_language_codes,
    source_country_code,
    source_language_codes,
    verified_country_route,
)


class CountryLanguageModelTests(unittest.TestCase):
    def test_country_and_language_codes_are_distinct(self):
        self.assertEqual(normalize_country_code("AT"), "AT")
        self.assertEqual(normalize_language_code("German"), "deu")
        self.assertEqual(normalize_language_code("DE"), "deu")
        self.assertEqual(normalize_language_code("HU"), "hun")
        self.assertEqual(normalize_language_code("SK"), "slk")
        self.assertEqual(normalize_language_code("CZ"), "ces")
        self.assertEqual(normalize_country_code("deu"), "")

    def test_old_language_values_remain_accepted(self):
        self.assertEqual(
            normalize_language_codes(["HU", "Czech", "deu"]),
            ["hun", "ces", "deu"],
        )

    def test_legacy_source_config_maps_to_country_and_spoken_language(self):
        cfg = {
            "default_country_code": "HU",
            "country_outputs": {"HU": "hu.m3u", "SK": "sk.m3u"},
        }
        spec = {"language_code": "SK"}
        country = source_country_code(spec, cfg)
        self.assertEqual(country, "SK")
        self.assertEqual(source_language_codes(spec, cfg, country), ["slk"])

    def test_new_source_config_keeps_country_and_language_independent(self):
        cfg = {"default_country_code": "AT"}
        spec = {
            "country_code": "AT",
            "language_codes": ["deu"],
        }
        country = source_country_code(spec, cfg)
        self.assertEqual(country, "AT")
        self.assertEqual(source_language_codes(spec, cfg, country), ["deu"])

    def test_supported_languages_do_not_come_from_country_codes(self):
        cfg = {
            "country_outputs": {
                "RS": "rs.m3u",
                "RO": "ro.m3u",
            },
            "country_language_defaults": {
                "RS": ["srp", "hun"],
                "RO": ["ron", "hun"],
            },
        }
        self.assertEqual(configured_country_codes(cfg), ["RS", "RO"])
        self.assertEqual(
            configured_language_codes(cfg),
            ["srp", "hun", "ron"],
        )

    def test_country_reroute_requires_explicit_source_language_rule(self):
        cfg = {
            "verified_country_routes": [
                {
                    "source_country_code": "SK",
                    "observed_language_code": "ces",
                    "output_country_code": "CZ",
                }
            ]
        }
        self.assertEqual(
            verified_country_route(cfg, "SK", ["CZ"]),
            "CZ",
        )
        self.assertEqual(
            verified_country_route(cfg, "RS", ["HU"]),
            "",
        )


if __name__ == "__main__":
    unittest.main()
