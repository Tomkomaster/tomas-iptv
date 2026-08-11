import unittest
from datetime import date

from attention import build_attention


class AttentionTests(unittest.TestCase):
    def stable_row(
        self,
        channel="Example TV",
        tvg_id="Example.hu@SD",
        url="https://example.test/live.m3u8",
        tested_on="2026-08-01",
    ):
        return {
            "channel": channel,
            "tvg_id": tvg_id,
            "stream_url": url,
            "source": "Example source",
            "decision": "Verified",
            "tested_on": tested_on,
            "in_playlist": True,
            "in_stable_playlist": True,
        }

    def report(self, rows):
        return {
            "generated_at": "2026-08-11 08:00:00 UTC",
            "audit": {"channels": rows},
        }

    def test_combines_multiple_signals_into_one_critical_item(self):
        row = self.stable_row(tested_on="2026-05-01")
        health = {
            "streams": [
                {
                    "channel": row["channel"],
                    "tvg_id": row["tvg_id"],
                    "stream_url": row["stream_url"],
                    "success": False,
                    "status": "HTTP error",
                    "consecutive_failures": 3,
                    "manual_retest_recommended": True,
                    "detail": "HTTP 404",
                }
            ]
        }
        coverage = {
            "matched": [
                {
                    "tvg_id": row["tvg_id"],
                    "provider": "example.epg",
                }
            ],
            "unmatched_tvg_ids": [],
        }
        epg_health = {
            "mapped_without_programmes": [
                {
                    "tvg_id": row["tvg_id"],
                    "provider": "example.epg",
                }
            ]
        }

        result = build_attention(
            self.report([row]),
            health=health,
            epg_coverage=coverage,
            epg_health=epg_health,
            config={
                "attention": {
                    "manual_stale_days": 30,
                    "manual_very_stale_days": 90,
                }
            },
            reference_date=date(2026, 8, 11),
        )

        self.assertEqual(result["summary"]["items"], 1)
        item = result["items"][0]
        self.assertEqual(item["severity"], "critical")
        self.assertEqual(item["reason_count"], 3)
        self.assertEqual(item["auto_status"], "HTTP error")
        self.assertEqual(item["epg_status"], "Mapped, no programmes")
        self.assertEqual(
            {signal["category"] for signal in item["signals"]},
            {
                "stream_manual_retest",
                "manual_stale",
                "epg_mapped_empty",
            },
        )

    def test_first_stream_failure_is_only_medium_warning(self):
        row = self.stable_row()
        result = build_attention(
            self.report([row]),
            health={
                "streams": [
                    {
                        "channel": row["channel"],
                        "tvg_id": row["tvg_id"],
                        "stream_url": row["stream_url"],
                        "success": False,
                        "status": "Timeout",
                        "consecutive_failures": 1,
                        "manual_retest_recommended": False,
                        "detail": "Timed out",
                    }
                ]
            },
            epg_coverage={
                "matched": [{"tvg_id": row["tvg_id"]}],
                "unmatched_tvg_ids": [],
            },
            reference_date=date(2026, 8, 11),
        )

        item = result["items"][0]
        self.assertEqual(item["severity"], "medium")
        self.assertEqual(item["signals"][0]["category"], "stream_failure")
        self.assertEqual(item["consecutive_failures"], 1)

    def test_verified_stream_missing_from_current_inputs_is_high_priority(self):
        historical = self.stable_row(
            channel="Old Local TV",
            tvg_id="OldLocal.hu@SD",
            url="https://old.example/live.m3u8",
        )
        historical["in_playlist"] = False
        historical["in_stable_playlist"] = False

        result = build_attention(
            self.report([historical]),
            reference_date=date(2026, 8, 11),
        )

        self.assertEqual(result["summary"]["items"], 1)
        item = result["items"][0]
        self.assertEqual(item["severity"], "high")
        self.assertEqual(item["signals"][0]["category"], "upstream_missing")

    def test_rejected_historical_stream_is_not_upstream_attention(self):
        historical = self.stable_row()
        historical.update({
            "decision": "Rejected",
            "in_playlist": False,
            "in_stable_playlist": False,
        })

        result = build_attention(
            self.report([historical]),
            reference_date=date(2026, 8, 11),
        )
        self.assertEqual(result["summary"]["items"], 0)

    def test_missing_tvg_id_is_low_epg_attention(self):
        row = self.stable_row(tvg_id="")
        result = build_attention(
            self.report([row]),
            health={
                "streams": [
                    {
                        "channel": row["channel"],
                        "stream_url": row["stream_url"],
                        "success": True,
                        "status": "Online",
                        "consecutive_failures": 0,
                    }
                ]
            },
            reference_date=date(2026, 8, 11),
        )

        item = result["items"][0]
        self.assertEqual(item["severity"], "low")
        self.assertEqual(item["epg_status"], "No tvg-id")
        self.assertEqual(item["signals"][0]["category"], "epg_missing_id")
        self.assertEqual(item["auto_status"], "Online")

    def test_healthy_fresh_stream_with_programme_data_is_omitted(self):
        row = self.stable_row(tested_on="2026-08-10")
        result = build_attention(
            self.report([row]),
            health={
                "streams": [
                    {
                        "channel": row["channel"],
                        "tvg_id": row["tvg_id"],
                        "stream_url": row["stream_url"],
                        "success": True,
                        "status": "Online",
                        "consecutive_failures": 0,
                    }
                ]
            },
            epg_coverage={
                "matched": [{"tvg_id": row["tvg_id"]}],
                "unmatched_tvg_ids": [],
            },
            epg_health={"mapped_without_programmes": []},
            reference_date=date(2026, 8, 11),
        )

        self.assertEqual(result["summary"]["items"], 0)
        self.assertEqual(result["status"], "healthy")


if __name__ == "__main__":
    unittest.main()
