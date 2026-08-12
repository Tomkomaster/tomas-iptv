from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


path = Path("build.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''        audit = candidate.get("_audit") or {}
        output_code = normalize_country_code(
''',
    '''        audit = candidate.get("_audit") or {}
        decision = str(candidate.get("_decision") or audit.get("decision") or "").strip()
        observed_languages = normalize_spoken_language_codes(
            audit.get("observed_language_codes")
        )
        if decision in {"Verified", "TV verified"} and observed_languages:
            candidate["language_codes"] = observed_languages
        else:
            candidate["language_codes"] = normalize_spoken_language_codes(
                candidate.get("language_codes")
            )

        output_code = normalize_country_code(
''',
    "verified observed language metadata",
)
path.write_text(text, encoding="utf-8")

# Build-level regressions for the exact expansion problem this refactor solves.
test_path = Path("tests/test_country_language_integration.py")
test_path.write_text(
    '''import unittest

import build


class CountryLanguageIntegrationTests(unittest.TestCase):
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
''',
    encoding="utf-8",
)

print("country/language verified-language semantics applied")
