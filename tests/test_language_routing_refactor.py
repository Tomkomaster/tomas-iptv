import unittest
from pathlib import Path

import build
from iptv import language_routing


EXTRACTED_NAMES = ('LANGUAGE_NAME_TO_CODE', 'normalize_language_code', 'normalize_language_codes', 'normalize_language_match', 'legacy_language_is_negative', 'derive_language_match', 'resolve_language_info', 'format_language_codes', 'language_mismatch_reason', 'configured_playlist_country_codes', 'configured_playlist_language_codes', 'configured_spoken_language_codes', 'audit_playlist_country_code', 'audit_playlist_scope_code', 'verified_output_country_code', 'verified_output_language_code', 'language_acceptance_state')
EXTRACTED_FUNCTIONS = ('normalize_language_code', 'normalize_language_codes', 'normalize_language_match', 'legacy_language_is_negative', 'derive_language_match', 'resolve_language_info', 'format_language_codes', 'language_mismatch_reason', 'configured_playlist_country_codes', 'configured_playlist_language_codes', 'configured_spoken_language_codes', 'audit_playlist_country_code', 'audit_playlist_scope_code', 'verified_output_country_code', 'verified_output_language_code', 'language_acceptance_state')


class LanguageRoutingRefactorTests(unittest.TestCase):
    def test_build_reexports_language_routing_api(self):
        for name in EXTRACTED_NAMES:
            self.assertIs(getattr(build, name), getattr(language_routing, name), name)

    def test_build_core_no_longer_defines_language_helpers(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        for name in EXTRACTED_FUNCTIONS:
            self.assertNotIn(f"def {name}(", text, name)
        self.assertNotIn("LANGUAGE_NAME_TO_CODE =", text)

    def test_legacy_language_normalization_contract(self):
        self.assertEqual(language_routing.normalize_language_code("Hungarian"), "HU")
        self.assertEqual(language_routing.normalize_language_code("ces"), "CZ")
        self.assertEqual(language_routing.normalize_language_codes("Hungarian, Czech"), ["HU", "CZ"])
        self.assertEqual(language_routing.normalize_language_match("wrong language"), "no")

    def test_language_acceptance_is_separate_from_country_routing(self):
        item = {
            "expected_language_codes": ["hun"],
            "observed_language_codes": ["ces"],
            "language_match": "no",
            "vlc": "works",
            "samsung": "works",
        }
        self.assertEqual(
            language_routing.language_acceptance_state(item, ["hun", "ces"]),
            "supported_cross_language",
        )
        self.assertEqual(
            language_routing.verified_output_country_code(
                {"decision": "Verified", "output_country_code": "CZ"},
                "SK",
                {"country_outputs": {"SK": "sk.m3u", "CZ": "cz.m3u"}},
            ),
            "CZ",
        )

    def test_audit_scope_prefers_explicit_country(self):
        self.assertEqual(
            language_routing.audit_playlist_country_code(
                {"playlist_country_code": "SK", "expected_language_codes": ["hun"]}
            ),
            "SK",
        )


if __name__ == "__main__":
    unittest.main()
