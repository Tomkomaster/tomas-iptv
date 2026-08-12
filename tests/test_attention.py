import unittest
from datetime import date

from attention import build_attention, row_country


class AttentionTests(unittest.TestCase):
    def stable_row(
        self,
        channel="Example TV",
        tvg_id="Example.hu@SD",
        url="https://example.test/live.m3u8",
        tested_on="2026-08-01",
        country="HU",
    ):
        return {
            "channel": channel,
            "tvg_id": tvg_id,
            "stream_url": url,
            "source": "Example source",
            "decision": "Verified",
            "tested_on": tested_on,
            "playlist_country_code": country,
            "output_country_code": country,
            "expected_language_codes": {
                "HU": "hun",
                "SK": "slk",
                "CZ": "ces",
            }.get(country, ""),
            "in_playlist": True,
            "in_stable_playlist": True,
        }

    def report(self, rows):
        return {
            "generated_at": "2026-08-11 08:00:00 UTC",
            "audit": {"channels": rows},
        }

    def test_row_country_prefers_modern_geography_over_spoken_language(self):
        self.assertEqual(
            row_country({
                "playlist_country_code": "SK",
                "playlist_language_code": "HU",
                "expected_language_codes": "hun",
            }),
            "SK",
        )
        self.assertEqual(
            row_country({
                "playlist_language_code": "CZ",
                "expected_language_codes": "slk",
            }),
            "CZ",
        )
        self.assertEqual(
            row_country({"expected_language_codes": "slk"}),
            "UNKNOWN",
        )

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

    def test_concentrated_relay_reports_host_and_only_channels_without_independent_backup(self):
        relay_a = self.stable_row(
            channel="Relay A",
            tvg_id="RelayA.sk",
            url="https://relay.example/a.m3u8",
            tested_on="2026-08-10",
            country="SK",
        )
        relay_b = self.stable_row(
            channel="Relay B",
            tvg_id="RelayB.sk",
            url="https://relay.example/b.m3u8",
            tested_on="2026-08-10",
            country="SK",
        )
        relay_c = self.stable_row(
            channel="Relay C",
            tvg_id="RelayC.sk",
            url="https://relay.example/c.m3u8",
            tested_on="2026-08-10",
            country="SK",
        )

        same_host_backup = dict(relay_a)
        same_host_backup.update({
            "stream_url": "https://relay.example/a-backup.m3u8",
            "in_stable_playlist": False,
            "decision": "TV verified",
        })
        independent_backup = dict(relay_c)
        independent_backup.update({
            "stream_url": "https://independent.example/c.m3u8",
            "source": "Independent broadcaster CDN",
            "in_stable_playlist": False,
            "decision": "TV verified",
        })

        source_concentration = {
            "flags": [
                {
                    "severity": "high",
                    "country_code": "SK",
                    "hostname": "relay.example",
                    "third_party_relay_channels": 3,
                    "third_party_relay_percent": 60.0,
                }
            ],
            "channels": [
                {
                    "country_code": "SK",
                    "channel": row["channel"],
                    "tvg_id": row["tvg_id"],
                    "hostname": "relay.example",
                    "source_type": "Third-party relay",
                    "stream_url": row["stream_url"],
                }
                for row in (relay_a, relay_b, relay_c)
            ],
        }
        coverage = {
            "matched": [
                {"tvg_id": row["tvg_id"]}
                for row in (relay_a, relay_b, relay_c)
            ],
            "unmatched_tvg_ids": [],
        }

        result = build_attention(
            self.report([
                relay_a,
                relay_b,
                relay_c,
                same_host_backup,
                independent_backup,
            ]),
            epg_coverage=coverage,
            source_concentration=source_concentration,
            reference_date=date(2026, 8, 11),
        )

        self.assertEqual(result["schema_version"], 3)
        self.assertEqual(result["summary"]["relay_concentration_hosts"], 1)
        self.assertEqual(result["summary"]["relay_stable_channels"], 3)
        self.assertEqual(result["summary"]["relay_channels_with_independent_backup"], 1)
        self.assertEqual(result["summary"]["relay_channels_without_independent_backup"], 2)
        self.assertEqual(result["summary"]["category_counts"]["relay_concentration"], 1)
        self.assertEqual(result["summary"]["category_counts"]["no_independent_backup"], 2)

        by_channel = {item["channel"]: item for item in result["items"]}
        self.assertIn("Relay dependency: relay.example", by_channel)
        self.assertIn("Relay A", by_channel)
        self.assertIn("Relay B", by_channel)
        self.assertNotIn("Relay C", by_channel)

        host_item = by_channel["Relay dependency: relay.example"]
        self.assertEqual(host_item["severity"], "high")
        self.assertIn("2 of those channels", host_item["signals"][0]["detail"])

        relay_a_item = by_channel["Relay A"]
        self.assertEqual(relay_a_item["severity"], "high")
        self.assertEqual(relay_a_item["redundancy_status"], "Fragile")
        self.assertEqual(
            relay_a_item["signals"][0]["category"],
            "no_independent_backup",
        )

    def test_single_third_party_relay_without_backup_is_medium_even_without_concentration_flag(self):
        row = self.stable_row(
            channel="Fragile Local",
            tvg_id="FragileLocal.sk",
            url="https://small-relay.example/live.m3u8",
            tested_on="2026-08-10",
            country="SK",
        )
        result = build_attention(
            self.report([row]),
            epg_coverage={"matched": [{"tvg_id": row["tvg_id"]}]},
            source_concentration={
                "flags": [],
                "channels": [
                    {
                        "country_code": "SK",
                        "channel": row["channel"],
                        "tvg_id": row["tvg_id"],
                        "hostname": "small-relay.example",
                        "source_type": "Third-party relay",
                        "stream_url": row["stream_url"],
                    }
                ],
            },
            reference_date=date(2026, 8, 11),
        )

        self.assertEqual(result["summary"]["items"], 1)
        item = result["items"][0]
        self.assertEqual(item["severity"], "medium")
        self.assertEqual(item["signals"][0]["category"], "no_independent_backup")


if __name__ == "__main__":
    unittest.main()
