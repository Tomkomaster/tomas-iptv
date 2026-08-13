import unittest
from pathlib import Path

import build
from iptv import audit


MOVED_FUNCTIONS = ('calculate_audit_decision', 'infer_protocol', 'canonical_audit_name', 'normalize_audit_decision_token', 'audit_status_is_recognized', 'audit_excluded', 'exact_url_audit_matches_entry', 'validate_audit_items', 'audit_match_key', 'prepare_audit_rows', 'audit_rows_by_stream_url')


class AuditRefactorTests(unittest.TestCase):
    def test_build_reexports_audit_api(self):
        for name in MOVED_FUNCTIONS:
            self.assertIs(getattr(build, name), getattr(audit, name), name)

    def test_build_core_no_longer_defines_audit_logic(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        for name in MOVED_FUNCTIONS:
            self.assertNotIn(f"def {name}(", text, name)
        self.assertLess(Path("iptv/build_core.py").stat().st_size, 95_000)

    def test_audit_decision_contract(self):
        verified = {
            "vlc": "works",
            "samsung": "works",
            "expected_language_codes": ["hun"],
            "observed_language_codes": ["hun"],
            "decision": "auto",
        }
        decision, reason = audit.calculate_audit_decision(verified, ["hun"])
        self.assertEqual(decision, "Verified")
        self.assertEqual(reason, "")

        pc_only = dict(verified, samsung="format_error")
        decision, _ = audit.calculate_audit_decision(pc_only, ["hun"])
        self.assertEqual(decision, "PC only")

    def test_exclude_flag_requires_real_boolean(self):
        self.assertTrue(audit.audit_excluded({"exclude_from_playlist": True}))
        self.assertFalse(audit.audit_excluded({"exclude_from_playlist": "true"}))


if __name__ == "__main__":
    unittest.main()
