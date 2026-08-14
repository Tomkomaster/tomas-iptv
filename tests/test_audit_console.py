import json
import tempfile
import unittest
from pathlib import Path

from tools.audit_console import (
    build_queue,
    render,
    save_result,
    wanted_target_for_row,
    write_audit,
)


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
    "provenance": "IPTV-org source (manual playback review)",
    "in_playlist": True,
    "decision": "Needs review",
    "feed_index": 1,
    "feed_count": 2,
    "feed_label": "Feed 1/2",
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
                "source_type": ["Unknown"],
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
        self.assertEqual(
            item["provenance"],
            "IPTV-org source (manual playback review)",
        )
        self.assertEqual(build_queue([ROW], updated), [])
        self.assertEqual(len(build_queue([ROW], updated, mode="retest")), 1)

    def test_important_queue_contains_only_pending_p1_p2_and_sorts_priority_first(self):
        p2 = dict(ROW)
        p2.update({
            "channel": "Alpha P2",
            "tvg_id": "AlphaP2.ro",
            "stream_url": "https://example.com/alpha-p2.m3u8",
            "feed_count": 1,
        })
        p1 = dict(ROW)
        p1.update({
            "channel": "Zulu P1",
            "tvg_id": "ZuluP1.ro@HD",
            "stream_url": "https://example.com/zulu-p1.m3u8",
            "feed_count": 1,
        })
        p3 = dict(ROW)
        p3.update({
            "channel": "Beta P3",
            "tvg_id": "BetaP3.ro",
            "stream_url": "https://example.com/beta-p3.m3u8",
            "feed_count": 1,
        })
        wanted = [
            {"country_code": "RO", "channel": "Alpha P2", "tvg_id": "AlphaP2.ro", "priority": "P2", "reason": "Important thematic"},
            {"country_code": "RO", "channel": "Zulu P1", "tvg_id": "ZuluP1.ro", "priority": "P1", "reason": "Major national"},
            {"country_code": "RO", "channel": "Beta P3", "tvg_id": "BetaP3.ro", "priority": "P3", "reason": "Regional"},
        ]
        payload = {"schema_version": 2, "storage": "manual_only", "channels": []}

        queue = build_queue(
            [p2, p3, p1],
            payload,
            mode="important",
            country="RO",
            wanted_channels=wanted,
        )

        self.assertEqual([item["channel"] for item in queue], ["Zulu P1", "Alpha P2"])
        self.assertEqual([item["_priority"] for item in queue], ["P1", "P2"])

    def test_important_queue_drops_completed_priority_stream(self):
        wanted = [
            {"country_code": "RO", "channel": "PRO TV", "tvg_id": "PROTV.ro", "priority": "P1", "reason": "Major national"},
        ]
        payload = {
            "schema_version": 2,
            "storage": "manual_only",
            "channels": [
                {
                    "channel": "PRO TV",
                    "stream_url": "https://example.com/live.m3u8",
                    "playlist_country_code": "RO",
                    "tvg_id": "PROTV.ro",
                    "vlc": "works",
                    "samsung": "works",
                    "observed_language_codes": ["ron"],
                }
            ],
        }
        self.assertEqual(
            build_queue([ROW], payload, mode="important", wanted_channels=wanted),
            [],
        )

    def test_exact_wanted_id_does_not_promote_same_name_different_service(self):
        wanted = [
            {"country_code": "SK", "channel": "Prima SK", "tvg_id": "PrimaSK.sk", "priority": "P1"},
        ]
        right = {
            "channel": "Prima SK",
            "tvg_id": "PrimaSK.sk@HD",
            "playlist_country_code": "SK",
        }
        wrong = {
            "channel": "Prima SK",
            "tvg_id": "DifferentService.sk",
            "playlist_country_code": "SK",
        }

        self.assertIsNotNone(wanted_target_for_row(right, wanted))
        self.assertIsNone(wanted_target_for_row(wrong, wanted))

    def test_name_only_wanted_target_can_match_current_channel(self):
        wanted = [
            {"country_code": "RO", "channel": "PRO TV", "tvg_id": "", "priority": "P1"},
        ]
        self.assertEqual(wanted_target_for_row(ROW, wanted)["priority"], "P1")

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
                    "provenance": "Original research note",
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
                "source_type": ["Unknown"],
            },
            tested_on="2026-08-13",
        )

        self.assertEqual(len(updated["channels"]), 1)
        item = updated["channels"][0]
        self.assertEqual(item["output_country_code"], "HU")
        self.assertEqual(item["decision"], "needs_review")
        self.assertTrue(item["exclude_from_playlist"])
        self.assertEqual(item["provenance"], "Original research note")

    def test_retest_can_clear_stale_decision_without_clearing_manual_exclusion(self):
        payload = {
            "schema_version": 2,
            "storage": "manual_only",
            "channels": [
                {
                    "channel": "PRO TV",
                    "stream_url": "https://example.com/live.m3u8",
                    "playlist_country_code": "RO",
                    "output_country_code": "RO",
                    "decision": "rejected",
                    "reason": "Failed previous playback test.",
                    "exclude_from_playlist": True,
                    "vlc": "generic_error",
                    "samsung": "generic_error",
                    "observed_language_codes": ["ron"],
                }
            ],
        }

        updated = save_result(
            payload,
            ROW,
            {
                "vlc": ["works"],
                "samsung": ["works"],
                "language": ["ron"],
                "source_type": ["Unknown"],
                "recalculate_decision": ["1"],
            },
            tested_on="2026-08-14",
        )

        item = updated["channels"][0]
        self.assertNotIn("decision", item)
        self.assertNotIn("reason", item)
        self.assertTrue(item["exclude_from_playlist"])
        self.assertEqual(item["output_country_code"], "RO")
        self.assertEqual(item["vlc"], "works")
        self.assertEqual(item["samsung"], "works")
        self.assertEqual(item["tested_on"], "2026-08-14")

    def test_retest_can_explicitly_remove_manual_exclusion(self):
        payload = {
            "schema_version": 2,
            "storage": "manual_only",
            "channels": [
                {
                    "channel": "PRO TV",
                    "stream_url": "https://example.com/live.m3u8",
                    "playlist_country_code": "RO",
                    "decision": "rejected",
                    "exclude_from_playlist": True,
                    "vlc": "generic_error",
                    "samsung": "generic_error",
                }
            ],
        }
        updated = save_result(
            payload,
            ROW,
            {
                "vlc": ["works"],
                "samsung": ["works"],
                "language": ["ron"],
                "recalculate_decision": ["1"],
                "clear_exclusion": ["1"],
            },
            tested_on="2026-08-14",
        )
        item = updated["channels"][0]
        self.assertNotIn("decision", item)
        self.assertNotIn("exclude_from_playlist", item)

    def test_confirmed_source_type_can_replace_provenance(self):
        payload = {
            "schema_version": 2,
            "storage": "manual_only",
            "channels": [],
        }
        updated = save_result(
            payload,
            ROW,
            {
                "vlc": ["works"],
                "samsung": ["works"],
                "language": ["ron"],
                "source_type": ["Official broadcaster"],
            },
            tested_on="2026-08-13",
        )
        self.assertEqual(
            updated["channels"][0]["provenance"],
            "Official broadcaster",
        )

    def test_render_has_one_channel_jump_option_for_multiple_feeds(self):
        second = dict(ROW)
        second.update({
            "stream_url": "https://example.com/live-backup.m3u8",
            "feed_index": 2,
            "feed_label": "Feed 2/2",
        })
        alpha = dict(ROW)
        alpha.update({
            "channel": "Alpha TV",
            "stream_url": "https://example.com/alpha.m3u8",
            "tvg_id": "AlphaTV.ro",
            "feed_index": 1,
            "feed_count": 1,
            "feed_label": "Single",
        })
        payload = {
            "schema_version": 2,
            "storage": "manual_only",
            "channels": [],
        }

        page = render(
            [alpha, ROW, second],
            payload,
            [("ron", "Romanian")],
            "token",
            "pending",
            "RO",
        )

        self.assertIn('name="focus"', page)
        self.assertIn("PRO TV — RO — 2 feeds", page)
        self.assertEqual(page.count("PRO TV — RO — 2 feeds"), 1)
        self.assertIn("Alpha TV — RO", page)

    def test_render_important_mode_shows_priority_badge_and_reason(self):
        payload = {"schema_version": 2, "storage": "manual_only", "channels": []}
        wanted = [
            {
                "country_code": "RO",
                "channel": "PRO TV",
                "tvg_id": "PROTV.ro",
                "priority": "P1",
                "reason": "Major Romanian national channel.",
            }
        ]
        page = render(
            [ROW],
            payload,
            [("ron", "Romanian")],
            "token",
            "important",
            "RO",
            wanted_channels=wanted,
        )
        self.assertIn("Important pending (P1 + P2)", page)
        self.assertIn("[P1]", page)
        self.assertIn("Major Romanian national channel.", page)
        self.assertIn("P1 · PRO TV — RO", page)

    def test_render_retest_exposes_recalculation_controls(self):
        payload = {
            "schema_version": 2,
            "storage": "manual_only",
            "channels": [
                {
                    "channel": "PRO TV",
                    "stream_url": "https://example.com/live.m3u8",
                    "playlist_country_code": "RO",
                    "decision": "rejected",
                    "reason": "Old failure",
                    "exclude_from_playlist": True,
                    "vlc": "generic_error",
                    "samsung": "generic_error",
                    "observed_language_codes": ["ron"],
                }
            ],
        }
        page = render(
            [ROW],
            payload,
            [("ron", "Romanian")],
            "token",
            "retest",
            "RO",
        )
        self.assertIn("Retest handling", page)
        self.assertIn('name="recalculate_decision"', page)
        self.assertIn('name="clear_exclusion"', page)

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
