#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_exact(path: str, old: str, new: str, expected: int = 1) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"{path}: expected {expected} occurrence(s), found {count}: {old!r}"
        )
    p.write_text(text.replace(old, new), encoding="utf-8")


# These tests used to require legacy/generated fields to be physically stored.
# Under schema v2, the same semantic facts remain available through modern
# manual fields or are reconstructed in the generated runtime audit view.
replace_exact(
    "tests/test_health_audit_followup.py",
    "    def test_modernize_only_adds_iso_fields_and_keeps_legacy_aliases(self):\n",
    "    def test_modernize_only_adds_iso_fields_and_compacts_legacy_aliases(self):\n",
)
replace_exact(
    "tests/test_health_audit_followup.py",
    '            self.assertEqual(item["language_code"], "SK")\n',
    '            self.assertNotIn("language_code", item)\n',
)
replace_exact(
    "tests/test_health_audit_followup.py",
    '            self.assertEqual(item["language_codes"], ["slk"])\n',
    '            self.assertNotIn("language_codes", item)\n',
)
replace_exact(
    "tests/test_health_audit_followup.py",
    '            self.assertEqual(item["output_country_code"], "")\n',
    '            self.assertEqual(item.get("output_country_code", ""), "")\n',
)
replace_exact(
    "tests/test_health_audit_followup.py",
    '            self.assertEqual(item["language_code"], "DE")\n',
    '            self.assertNotIn("language_code", item)\n',
)
replace_exact(
    "tests/test_health_audit_followup.py",
    '            self.assertEqual(item["language_codes"], ["deu"])\n',
    '            self.assertNotIn("language_codes", item)\n',
)
replace_exact(
    "tests/test_migrate_audit.py",
    '            self.assertEqual(\n                item["protocol"],\n                "HLS",\n            )\n',
    '            self.assertNotIn("protocol", item)\n',
)
