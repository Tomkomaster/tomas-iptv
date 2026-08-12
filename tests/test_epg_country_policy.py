import unittest

from epg_policy import compile_epg_policy, resolve_epg_policy


class CountryEpgPolicyTests(unittest.TestCase):
    def test_country_default_is_used_after_exact_selectors(self):
        default, indexes = compile_epg_policy({
            "default": "optional",
            "country_defaults": {
                "HU": "expected",
                "SK": "expected",
                "CZ": "not_expected",
            },
            "entries": [
                {
                    "channel": "Czech Special",
                    "status": "optional",
                }
            ],
        })

        cz_default = resolve_epg_policy(
            {
                "channel": "Ordinary Czech TV",
                "output_language_code": "CZ",
            },
            default=default,
            indexes=indexes,
        )
        self.assertEqual(cz_default["status"], "not_expected")
        self.assertEqual(cz_default["matched_by"], "country_default")

        exact = resolve_epg_policy(
            {
                "channel": "Czech Special",
                "output_language_code": "CZ",
            },
            default=default,
            indexes=indexes,
        )
        self.assertEqual(exact["status"], "optional")
        self.assertEqual(exact["matched_by"], "channel")

    def test_invalid_country_default_is_rejected(self):
        with self.assertRaises(ValueError):
            compile_epg_policy({
                "country_defaults": {"CZ": "sometimes"},
            })


if __name__ == "__main__":
    unittest.main()
