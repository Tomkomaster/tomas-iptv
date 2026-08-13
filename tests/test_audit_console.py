import json
import tempfile
import unittest
from pathlib import Path

from tools.audit_console import build_queue, save_result, write_audit


ROW = {
    "channel": "PRO TV",
    "stream_url": "https://EXAMPLE.com:443/live.m3u8#fragment",
    "tvg_id": "PROTV.ro",
    "playlist_country_code": "RO",
    "country_code": "RO",
    "expected_language_codes": ["ron"],
    "language_codes": ["ron"],
    "source": "Test source",
    "discovery": "Current playlist",
    "in_playlist": True,
    "decision": "Needs review",
    "feed_index": 1,
}


class AuditConsoleTests(unittest.TestCase):
    def test_completed_exact_url_audit_leaves_pending_queue(self):
        payload = {
            "schema_version": 2,
            "storage": "manual_only",
            "channels": [],
        }
        self.assertEqual(len(build_queue([ROW], payload)), 1)

        updated = save_result(
            payload,
            ROW,
            {
                "vlc": ["works"],
                "samsung": ["works"],
                "language": ["ron"],
                "provenance": ["Official broadcaster"],
                "notes": ["Passed both tests."],
            },
            tested_on="2026-08-13",
        )

        self.assertEqual(len(updated["channels"]), 1)
        item = updated["channels"][0]
        self.assertEqual(item["vlc"], "works")
        self.assertEqual(item["samsung"], "works")
        self.assertEqual(item["observed_language_codes"], ["ron"])
        self.assertEqual(item["tested_on"], "2026-08-13")
        self.assertEqual(build_queue([ROW], updated), [])

    def test_canonical_url_upsert_preserves_existing_manual_fields(self):
        payload = {
            "schema_version": 2,
            "storage": "manual_only",
            "channels": [
                {
                    "channel": "Old name",
                    "stream_url": "https://example.com/live.m3u8",
                    "output_country_code": "HU",
                    "decision": "needs_review",
                    "exclude_from_playlist": True,
                    "vlc": "works",
                }
            ],
        }

        updated = save_result(
            payload,
            ROW,
            {
                "vlc": ["works"],
                "samsung": ["generic_error"],
                "language": ["ron"],
                "provenance": ["Unknown"],
            },
            tested_on="2026-08-13",
        )

        self.assertEqual(len(updated["channels"]), 1)
        item = updated["channels"][0]
        self.assertEqual(item["output_country_code"], "HU")
        self.assertEqual(item["decision"], "needs_review")
        self.assertTrue(item["exclude_from_playlist"])

    def test_write_audit_keeps_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.json"
            path.write_text(
                '{"schema_version":2,"storage":"manual_only","channels":[]}\n',
                encoding="utf-8",
            )
            payload = {
                "schema_version": 2,
                "storage": "manual_only",
                "channels": [
                    {"channel": "Example", "stream_url": "https://example.test/live"}
                ],
            }

            write_audit(path, payload)

            self.assertTrue((Path(directory) / "audit.json.bak").is_file())
            written = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(written["channels"][0]["channel"], "Example")


if __name__ == "__main__":
    unittest.main()
