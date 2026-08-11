import unittest
from datetime import date

from attention import build_attention
from epg_policy import compile_epg_policy, resolve_epg_policy


class EpgPolicyAttentionTests(unittest.TestCase):
    def stable_row(
        self,
        channel="Local Example TV",
        tvg_id="LocalExample.sk@SD",
        url="https://example.test/live.m3u8",
    ):
        return {
            "channel": channel,
            "tvg_id": tvg_id,
            "stream_url": url,
            "source": "Example source",
            "decision": "Verified",
            "tested_on": "2026-08-10",
            "in_playlist": True,
            "in_stable_playlist": True,
        }

    def report(self, rows):
        return {
            "generated_at": "2026-08-11 08:00:00 UTC",
            "audit": {"channels": rows},
        }

    def test_optional_unmapped_epg_gap_is_suppressed(self):
        row = self.stable_row()
        result = build_attention(
            self.report([row]),
            epg_coverage={
                "matched": [],
                "unmatched_tvg_ids": [row["tvg_id"]],
            },
            epg_policy={
                "default": "expected",
                "entries": [
                    {
                        "tvg_id": row["tvg_id"],
                        "status": "optional",
                        "reason": "Local guide is useful but not required.",
                    }
                ],
            },
            reference_date=date(2026, 8, 11),
        )

        self.assertEqual(result["summary"]["items"], 0)
        self.assertEqual(result["summary"]["epg_suppressed_gaps"], 1)
        self.assertEqual(
            result["summary"]["epg_suppressed_gap_counts"]["optional"],
            1,
        )
        self.assertEqual(result["summary"]["epg_policy_counts"]["optional"], 1)

    def test_optional_epg_gap_does_not_hide_stream_failure(self):
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
                "matched": [],
                "unmatched_tvg_ids": [row["tvg_id"]],
            },
            epg_policy={
                "default": "expected",
                "entries": [
                    {
                        "tvg_id": row["tvg_id"],
                        "status": "optional",
                        "reason": "Local guide is useful but not required.",
                    }
                ],
            },
            reference_date=date(2026, 8, 11),
        )

        self.assertEqual(result["summary"]["items"], 1)
        item = result["items"][0]
        self.assertEqual(
            [signal["category"] for signal in item["signals"]],
            ["stream_failure"],
        )
        self.assertEqual(item["epg_policy"], "optional")
        self.assertEqual(item["epg_policy_match"], "tvg_id")
        self.assertEqual(item["epg_status"], "Optional: Unmapped")
        self.assertEqual(result["summary"]["epg_suppressed_gaps"], 1)

    def test_not_expected_missing_id_is_suppressed(self):
        row = self.stable_row(channel="Bunyó TV", tvg_id="")
        result = build_attention(
            self.report([row]),
            epg_policy={
                "default": "expected",
                "entries": [
                    {
                        "channel": "Bunyó TV",
                        "status": "not_expected",
                        "reason": "No conventional schedule is expected.",
                    }
                ],
            },
            reference_date=date(2026, 8, 11),
        )

        self.assertEqual(result["summary"]["items"], 0)
        self.assertEqual(result["summary"]["epg_suppressed_gaps"], 1)
        self.assertEqual(
            result["summary"]["epg_suppressed_gap_counts"]["not_expected"],
            1,
        )

    def test_policy_selector_precedence_is_url_then_tvg_then_channel(self):
        row = self.stable_row()
        default, indexes = compile_epg_policy(
            {
                "default": "expected",
                "entries": [
                    {"channel": row["channel"], "status": "not_expected"},
                    {"tvg_id": row["tvg_id"], "status": "optional"},
                    {"stream_url": row["stream_url"], "status": "expected"},
                ],
            }
        )
        resolved = resolve_epg_policy(row, default=default, indexes=indexes)
        self.assertEqual(resolved["status"], "expected")
        self.assertEqual(resolved["matched_by"], "stream_url")

    def test_invalid_policy_status_is_rejected(self):
        with self.assertRaises(ValueError):
            compile_epg_policy(
                {
                    "entries": [
                        {"channel": "Example TV", "status": "sometimes"}
                    ]
                }
            )


if __name__ == "__main__":
    unittest.main()
