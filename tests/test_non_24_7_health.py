import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from attention import build_attention
from build import make_dashboard
from healthcheck import apply_history, build_report


class Non247HealthTests(unittest.TestCase):
    def entry(self):
        return {
            "channel": "Országgyűlés (Plenáris)",
            "playlist_name": "[HU OK] Országgyűlés (Plenáris)",
            "manual_status": "Samsung + VLC",
            "tvg_id": "OrszaggyulesOGYplenaris.hu@SD",
            "group_title": "Hungary | Legislative",
            "stream_url": "https://example.test/plenary.m3u8",
            "health_policy": "event_based",
            "health_policy_reason": "Only broadcasts during plenary sittings.",
            "health_policy_match": "tvg_id",
        }

    def failed_probe(self):
        return {
            "status": "Manifest unavailable",
            "success": False,
            "startup_seconds": 0.2,
            "probe_type": "HLS",
            "redirected": False,
            "final_url": "https://example.test/plenary.m3u8",
            "http_status": 404,
            "request_count": 1,
            "detail": "No active manifest right now.",
            "tls_certificate_warning": False,
            "tls_certificate_detail": "",
        }

    def test_event_based_failure_is_informational_and_does_not_build_streak(self):
        previous = {
            "consecutive_failures": 2,
            "last_success_at": "2026-08-01 10:00:00 UTC",
            "last_failure_at": "2026-08-10 04:23:00 UTC",
        }
        result = apply_history(
            self.entry(),
            self.failed_probe(),
            previous,
            "2026-08-11 04:23:00 UTC",
        )

        self.assertFalse(result["success"])
        self.assertFalse(result["actionable_failure"])
        self.assertEqual(result["status"], "Event inactive")
        self.assertEqual(result["probe_status"], "Manifest unavailable")
        self.assertEqual(result["attention"], "informational")
        self.assertEqual(result["consecutive_failures"], 0)
        self.assertFalse(result["manual_retest_recommended"])
        self.assertEqual(result["last_failure_at"], previous["last_failure_at"])
        self.assertEqual(result["last_inactive_at"], "2026-08-11 04:23:00 UTC")

    def test_normal_failure_keeps_existing_three_day_retest_rule(self):
        entry = dict(self.entry())
        entry.update({
            "channel": "Normal TV",
            "tvg_id": "NormalTV.hu@SD",
            "health_policy": "normal",
            "health_policy_reason": "Normal 24/7 channel.",
        })
        previous = {"consecutive_failures": 2, "last_success_at": "earlier"}
        result = apply_history(
            entry,
            self.failed_probe(),
            previous,
            "2026-08-11 04:23:00 UTC",
        )

        self.assertTrue(result["actionable_failure"])
        self.assertEqual(result["consecutive_failures"], 3)
        self.assertTrue(result["manual_retest_recommended"])
        self.assertEqual(result["attention"], "needs_manual_retest")

    def test_report_separates_event_inactivity_from_actionable_failures(self):
        policy = {
            "schema_version": 1,
            "default": "normal",
            "entries": [
                {
                    "tvg_id": "OrszaggyulesOGYplenaris.hu@SD",
                    "health_policy": "event_based",
                    "reason": "Plenary event feed.",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            playlist = Path(tmp) / "tv.m3u"
            playlist.write_text(
                "#EXTM3U\n"
                '#EXTINF:-1 tvg-id="OrszaggyulesOGYplenaris.hu@SD" group-title="Hungary | Legislative",[HU OK] Országgyűlés (Plenáris)\n'
                "https://example.test/plenary.m3u8\n",
                encoding="utf-8",
            )

            with patch("healthcheck.probe_stream", return_value=self.failed_probe()):
                report = build_report(
                    playlist,
                    previous=None,
                    health_policy=policy,
                    workers=1,
                )

        self.assertEqual(report["summary"]["total"], 1)
        self.assertEqual(report["summary"]["playable"], 0)
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertEqual(report["summary"]["informational_unavailable"], 1)
        self.assertEqual(report["summary"]["needs_manual_retest"], 0)
        self.assertEqual(report["summary"]["health_policy_counts"]["event_based"], 1)
        self.assertEqual(report["streams"][0]["status"], "Event inactive")

    def test_attention_ignores_event_inactive_stream_failure_signal(self):
        row = {
            "channel": "Országgyűlés (Plenáris)",
            "tvg_id": "OrszaggyulesOGYplenaris.hu@SD",
            "stream_url": "https://example.test/plenary.m3u8",
            "source": "Example",
            "decision": "Verified",
            "tested_on": "2026-08-10",
            "in_playlist": True,
            "in_stable_playlist": True,
        }
        health = {
            "streams": [
                {
                    "channel": row["channel"],
                    "tvg_id": row["tvg_id"],
                    "stream_url": row["stream_url"],
                    "success": False,
                    "actionable_failure": False,
                    "status": "Event inactive",
                    "probe_status": "Manifest unavailable",
                    "attention": "informational",
                    "consecutive_failures": 0,
                    "manual_retest_recommended": False,
                    "detail": "Event feed inactive outside broadcast hours.",
                }
            ]
        }
        result = build_attention(
            {
                "generated_at": "2026-08-11 08:00:00 UTC",
                "audit": {"channels": [row]},
            },
            health=health,
            epg_coverage={"matched": [{"tvg_id": row["tvg_id"]}], "unmatched_tvg_ids": []},
            epg_health={"mapped_without_programmes": []},
            epg_policy={
                "default": "expected",
                "entries": [
                    {
                        "tvg_id": row["tvg_id"],
                        "status": "not_expected",
                        "reason": "Event feed.",
                    }
                ],
            },
            reference_date=date(2026, 8, 11),
        )
        self.assertEqual(result["summary"]["items"], 0)

    def test_dashboard_exposes_event_inactive_as_its_own_filter_and_summary(self):
        page = make_dashboard(
            cfg={"site_title": "Test IPTV", "epg": {"enabled": False}},
            generated="2026-08-11 08:00:00 UTC",
            final_entries=[],
            unique_channels=[],
            source_stats=[],
            language_stats=[],
            duplicate_rows=[],
            changes={"previous_generated_at": None, "added_channels": [], "removed_channels": []},
            audit_rows=[],
            audit_ambiguity_warnings=[],
        )
        self.assertIn('value="Event inactive"', page)
        self.assertIn("Event-based inactive", page)
        self.assertIn("data-health-actionable", page)


if __name__ == "__main__":
    unittest.main()
