import json
import unittest
from pathlib import Path

from iptv.audit import validate_audit_items
from iptv.audit_storage import (
    GENERATED_CONTEXT_FIELDS,
    MANUAL_AUDIT_SCHEMA_VERSION,
    MANUAL_AUDIT_STORAGE_KIND,
    compact_manual_audit_item,
    machine_telemetry_fields,
)


ROOT = Path(__file__).resolve().parents[1]


class AuditStorageTests(unittest.TestCase):
    def test_compaction_keeps_manual_facts_and_drops_generated_defaults(self):
        compact = compact_manual_audit_item({
            "channel": "Example TV",
            "stream_url": "https://example.test/live.m3u8",
            "protocol": "HLS",
            "language": "Czech",
            "language_code": "CZ",
            "language_codes": ["ces"],
            "expected_language_codes": ["ces"],
            "playlist_language_code": "CZ",
            "output_language_code": "CZ",
            "vlc": "works",
            "samsung": "not_tested",
            "vlc_note": "manual VLC check",
            "samsung_note": "",
            "decision": "auto",
            "exclude_from_playlist": False,
            "tested_on": "2026-08-13",
            "notes": "Keep this manual note.",
        })

        self.assertEqual(compact["playlist_country_code"], "CZ")
        self.assertEqual(compact["output_country_code"], "CZ")
        self.assertEqual(compact["observed_language_codes"], ["ces"])
        self.assertEqual(compact["expected_language_codes"], ["ces"])
        self.assertEqual(compact["vlc"], "works")
        self.assertEqual(compact["vlc_note"], "manual VLC check")
        self.assertEqual(compact["tested_on"], "2026-08-13")
        self.assertEqual(compact["notes"], "Keep this manual note.")
        self.assertIs(compact["exclude_from_playlist"], False)

        for field in (
            "protocol", "language", "language_code", "language_codes",
            "playlist_language_code", "output_language_code", "samsung",
            "samsung_note", "decision",
        ):
            self.assertNotIn(field, compact)

    def test_explicit_manual_overrides_are_preserved(self):
        compact = compact_manual_audit_item({
            "channel": "Cross-language TV",
            "playlist_country_code": "SK",
            "output_country_code": "CZ",
            "expected_language_codes": ["slk"],
            "observed_language_codes": ["ces"],
            "language_match": "no",
            "decision": "rejected",
            "exclude_from_playlist": True,
            "reason": "Manual decision.",
        })
        self.assertEqual(compact["output_country_code"], "CZ")
        self.assertEqual(compact["language_match"], "no")
        self.assertEqual(compact["decision"], "rejected")
        self.assertIs(compact["exclude_from_playlist"], True)
        self.assertEqual(compact["reason"], "Manual decision.")

    def test_machine_telemetry_is_rejected(self):
        row = {"channel": "Example", "probe_status": "HTTP error", "http_status": 503}
        self.assertEqual(machine_telemetry_fields(row), ["http_status", "probe_status"])
        with self.assertRaisesRegex(ValueError, "Machine telemetry"):
            compact_manual_audit_item(row)
        with self.assertRaisesRegex(RuntimeError, "Machine telemetry fields"):
            validate_audit_items([row], [])

    def test_repository_audit_is_manual_only_schema(self):
        path = ROOT / "audit.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], MANUAL_AUDIT_SCHEMA_VERSION)
        self.assertEqual(payload["storage"], MANUAL_AUDIT_STORAGE_KIND)
        self.assertGreater(len(payload["channels"]), 0)

        failures = []
        for index, row in enumerate(payload["channels"], start=1):
            telemetry = machine_telemetry_fields(row)
            generated = sorted(set(row).intersection(GENERATED_CONTEXT_FIELDS))
            if telemetry:
                failures.append(f"row {index}: telemetry {telemetry}")
            if generated:
                failures.append(f"row {index}: generated context {generated}")
            if row.get("decision") == "auto":
                failures.append(f"row {index}: explicit default decision")

        self.assertEqual(failures, [], "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
