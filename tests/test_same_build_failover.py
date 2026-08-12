import unittest

import feed_quality
import same_build_failover
import stable_build


class SameBuildFailoverTests(unittest.TestCase):
    def audit_row(self, **kwargs):
        row = {
            "channel": "Demo TV",
            "tvg_id": "DemoTV.sk",
            "playlist_country_code": "SK",
            "output_country_code": "SK",
            "stream_url": "https://example.test/feed.m3u8",
            "decision": "Verified",
            "in_playlist": "True",
            "exclude_from_playlist": "False",
        }
        row.update(kwargs)
        return row

    def test_only_redundant_manually_tv_safe_feeds_are_probed(self):
        rows = [
            self.audit_row(stream_url="https://example.test/a.m3u8"),
            self.audit_row(
                stream_url="https://example.test/b.m3u8",
                decision="TV verified",
            ),
            self.audit_row(
                stream_url="https://example.test/unverified.m3u8",
                decision="Needs review",
            ),
            self.audit_row(
                channel="Single Verified",
                tvg_id="SingleVerified.sk",
                stream_url="https://example.test/single.m3u8",
            ),
            self.audit_row(
                stream_url="https://example.test/rejected.m3u8",
                decision="Rejected",
            ),
            self.audit_row(
                stream_url="https://example.test/excluded.m3u8",
                exclude_from_playlist="True",
            ),
            self.audit_row(
                stream_url="https://example.test/history.m3u8",
                in_playlist="False",
            ),
        ]

        groups = same_build_failover.tv_safe_redundant_groups(rows)
        self.assertEqual(len(groups), 1)
        feeds = next(iter(groups.values()))
        self.assertEqual(
            {row["stream_url"] for row in feeds},
            {
                "https://example.test/a.m3u8",
                "https://example.test/b.m3u8",
            },
        )
        self.assertEqual(
            {row["decision"] for row in feeds},
            {"Verified", "TV verified"},
        )

    def test_probe_report_preserves_manual_authority(self):
        rows = [
            self.audit_row(stream_url="https://example.test/a.m3u8"),
            self.audit_row(stream_url="https://example.test/b.m3u8"),
            self.audit_row(
                stream_url="https://example.test/nope.m3u8",
                decision="Needs review",
            ),
        ]

        def fake_probe(entry, **_kwargs):
            url = entry["stream_url"]
            success = url.endswith("b.m3u8")
            return {
                "status": "Online" if success else "HTTP error",
                "success": success,
                "startup_seconds": 0.1,
                "redirected": False,
                "request_count": 1,
                "probe_type": "HLS",
                "detail": "fake",
                "final_url": url,
                "http_status": 200 if success else 503,
                "tls_certificate_warning": False,
                "tls_certificate_detail": "",
            }

        report = same_build_failover.probe_verified_redundancy(
            rows,
            workers=2,
            probe_fn=fake_probe,
        )
        self.assertTrue(report["selection_only"])
        self.assertEqual(report["summary"]["redundant_channels"], 1)
        self.assertEqual(report["summary"]["probed_feeds"], 2)
        self.assertEqual(report["summary"]["playable"], 1)
        self.assertEqual(report["summary"]["failed"], 1)
        self.assertNotIn(
            "https://example.test/nope.m3u8",
            {item["stream_url"] for item in report["streams"]},
        )
        self.assertTrue(
            all(item["decision"] == "Verified" for item in report["streams"])
        )

    def test_unexpected_probe_error_is_not_selection_evidence(self):
        rows = [
            self.audit_row(stream_url="https://example.test/a.m3u8"),
            self.audit_row(stream_url="https://example.test/b.m3u8"),
        ]

        def broken_probe(_entry, **_kwargs):
            raise RuntimeError("probe implementation exploded")

        report = same_build_failover.probe_verified_redundancy(
            rows,
            workers=1,
            probe_fn=broken_probe,
        )
        self.assertEqual(report["summary"]["unknown"], 2)
        self.assertEqual(stable_build.same_build_health_by_url(report), {})
        self.assertTrue(
            all(item["usable_evidence"] is False for item in report["streams"])
        )

    def test_live_verified_feed_beats_higher_quality_failed_feed(self):
        cfg = {
            "stable_playlist": {
                "feed_quality": {
                    "weights": dict(feed_quality.DEFAULT_WEIGHTS),
                }
            }
        }
        audit = {
            "samsung": "works",
            "vlc": "works",
            "decision": "Verified",
        }
        official = {
            "url": "https://official.example/a.m3u8",
            "source": "Official broadcaster",
            "_audit": audit,
        }
        relay = {
            "url": "https://relay.example/b.m3u8",
            "source": "Antik provider relay",
            "_audit": audit,
        }

        official_base = feed_quality.score_feed_quality(
            official,
            cfg,
            context={"health_by_url": {}},
        )
        relay_base = feed_quality.score_feed_quality(
            relay,
            cfg,
            context={"health_by_url": {}},
        )
        self.assertGreater(official_base["score"], relay_base["score"])

        current = {
            feed_quality.canonical_stream_url(official["url"]): {
                "success": False,
                "status": "HTTP error",
            },
            feed_quality.canonical_stream_url(relay["url"]): {
                "success": True,
                "status": "Online",
            },
        }
        official_today = stable_build.apply_same_build_selection_guard(
            official_base,
            official,
            cfg,
            current,
        )
        relay_today = stable_build.apply_same_build_selection_guard(
            relay_base,
            relay,
            cfg,
            current,
        )
        self.assertLess(official_today["score"], relay_today["score"])
        self.assertTrue(
            any(
                component["key"] == "same_build_unplayable"
                for component in official_today["components"]
            )
        )

    def test_recovered_feed_can_switch_back_to_quality_winner(self):
        cfg = {}
        audit = {
            "samsung": "works",
            "vlc": "works",
            "decision": "Verified",
        }
        official = {
            "url": "https://official.example/a.m3u8",
            "source": "Official broadcaster",
            "_audit": audit,
        }
        relay = {
            "url": "https://relay.example/b.m3u8",
            "source": "Antik provider relay",
            "_audit": audit,
        }
        official_base = feed_quality.score_feed_quality(official, cfg, context={})
        relay_base = feed_quality.score_feed_quality(relay, cfg, context={})

        both_live = {
            feed_quality.canonical_stream_url(official["url"]): {
                "success": True,
                "status": "Online",
            },
            feed_quality.canonical_stream_url(relay["url"]): {
                "success": True,
                "status": "Online",
            },
        }
        official_recovered = stable_build.apply_same_build_selection_guard(
            official_base,
            official,
            cfg,
            both_live,
        )
        relay_live = stable_build.apply_same_build_selection_guard(
            relay_base,
            relay,
            cfg,
            both_live,
        )
        self.assertGreater(official_recovered["score"], relay_live["score"])

    def test_if_every_verified_alternative_fails_quality_order_is_preserved(self):
        cfg = {}
        audit = {
            "samsung": "works",
            "vlc": "works",
            "decision": "Verified",
        }
        better = {
            "url": "https://official.example/a.m3u8",
            "source": "Official broadcaster",
            "_audit": audit,
        }
        worse = {
            "url": "http://relay.example/b.m3u8",
            "source": "Antik provider relay",
            "_audit": audit,
        }
        better_base = feed_quality.score_feed_quality(better, cfg, context={})
        worse_base = feed_quality.score_feed_quality(worse, cfg, context={})
        both_failed = {
            feed_quality.canonical_stream_url(better["url"]): {
                "success": False,
                "status": "Timeout",
            },
            feed_quality.canonical_stream_url(worse["url"]): {
                "success": False,
                "status": "HTTP error",
            },
        }
        better_failed = stable_build.apply_same_build_selection_guard(
            better_base,
            better,
            cfg,
            both_failed,
        )
        worse_failed = stable_build.apply_same_build_selection_guard(
            worse_base,
            worse,
            cfg,
            both_failed,
        )
        self.assertGreater(better_failed["score"], worse_failed["score"])


if __name__ == "__main__":
    unittest.main()
