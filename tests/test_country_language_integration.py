import unittest

import build


class CountryLanguageIntegrationTests(unittest.TestCase):
    def test_legacy_audit_language_api_maps_iso_inputs_to_historical_tokens(self):
        self.assertEqual(
            build.normalize_language_codes(["hun", "slk", "ces"]),
            ["HU", "SK", "CZ"],
        )

    def test_hungarian_language_does_not_move_serbian_channel_without_route(self):
        candidate = {
            "channel_name": "Vojvodina Demo",
            "channel_key": "vojvodina-demo",
            "country_code": "RS",
            "language_code": "RS",
            "language_codes": ["srp", "hun"],
            "_decision": "Verified",
            "_audit": {
                "decision": "Verified",
                "observed_language_codes": ["HU"],
            },
        }
        cfg = {
            "country_outputs": {
                "RS": "public/rs.m3u",
                "HU": "public/hu.m3u",
            },
            "verified_country_routes": [],
        }

        routed = build.route_candidates_to_verified_countries([candidate], cfg)

        self.assertEqual(len(routed), 1)
        self.assertEqual(routed[0]["country_code"], "RS")
        self.assertEqual(routed[0]["language_codes"], ["hun"])

    def test_explicit_sk_czech_route_changes_country_and_spoken_language(self):
        candidate = {
            "channel_name": "Czech Demo",
            "channel_key": "czech-demo",
            "country_code": "SK",
            "language_code": "SK",
            "language_codes": ["slk"],
            "_decision": "Verified",
            "_audit": {
                "decision": "Verified",
                "observed_language_codes": ["CZ"],
            },
        }
        cfg = {
            "country_outputs": {
                "SK": "public/sk.m3u",
                "CZ": "public/cz.m3u",
            },
            "verified_country_routes": [
                {
                    "source_country_code": "SK",
                    "observed_language_code": "ces",
                    "output_country_code": "CZ",
                }
            ],
        }

        routed = build.route_candidates_to_verified_countries([candidate], cfg)

        self.assertEqual(len(routed), 1)
        self.assertEqual(routed[0]["source_country_code"], "SK")
        self.assertEqual(routed[0]["country_code"], "CZ")
        self.assertEqual(routed[0]["language_codes"], ["ces"])


if __name__ == "__main__":
    unittest.main()
