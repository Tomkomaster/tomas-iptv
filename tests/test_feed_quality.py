import unittest
from datetime import date

from build import select_stable_playlist_candidates
from feed_quality import score_feed_quality


class FeedQualityScoringTests(unittest.TestCase):
    def test_requested_quality_signals_are_weighted(self):
        entry = {
            "url": "https://official.example/live/demo-1080p.m3u8",
            "tvg_id": "Demo.hu",
            "channel_name": "Demo TV (1080p)",
            "source_flags": [],
            "_audit": {
                "samsung": "works",
                "vlc": "works",
                "tested_on": "2026-08-10",
                "quality_flags": ["official_broadcaster", "broadcaster_cdn"],
            },
        }
        context = {
            "reference_date": date(2026, 8, 12),
            "health_by_url": {},
            "epg_mapped_ids": {"Demo.hu"},
            "epg_empty_ids": set(),
        }

        result = score_feed_quality(entry, {}, context=context)
        points = {component["key"]: component["points"] for component in result["components"]}

        self.assertEqual(points["samsung_works"], 100)
        self.assertEqual(points["vlc_works"], 60)
        self.assertEqual(points["official_broadcaster"], 50)
        self.assertEqual(points["broadcaster_cdn"], 30)
        self.assertEqual(points["https"], 20)
        self.assertEqual(points["current_epg"], 20)
        self.assertEqual(points["high_definition"], 10)
        self.assertEqual(points["recent_manual_test"], 10)
        self.assertEqual(result["score"], 300)

    def test_health_relay_stale_and_event_penalties_apply(self):
        url = "https://relay.example/event/1080p.m3u8"
        entry = {
            "url": url,
            "tvg_id": "Event.hu",
            "channel_name": "Event TV 1080p",
            "source_flags": ["Not 24/7"],
            "_audit": {
                "samsung": "works",
                "vlc": "works_with_warning",
                "tested_on": "2026-06-01",
                "quality_flags": ["provider_relay"],
            },
        }
        context = {
            "reference_date": date(2026, 8, 12),
            "health_by_url": {
                url: {
                    "status": "TLS certificate warning",
                    "redirected": True,
                    "tls_certificate_warning": True,
                    "actionable_failure": True,
                    "health_policy": "event_based",
                }
            },
            "epg_mapped_ids": set(),
            "epg_empty_ids": set(),
        }

        result = score_feed_quality(entry, {}, context=context)
        points = {component["key"]: component["points"] for component in result["components"]}

        self.assertEqual(points["redirect"], -15)
        self.assertEqual(points["tls_certificate_warning"], -25)
        self.assertEqual(points["provider_relay"], -30)
        self.assertEqual(points["health_warning"], -40)
        self.assertEqual(points["stale_manual_test"], -50)
        self.assertEqual(points["event_only"], -80)

    def test_720p_official_verified_feed_beats_1080p_provider_relay(self):
        official_url = "https://broadcaster.example/live/demo-720.m3u8"
        relay_url = "https://relay.example/live/demo-1080p.m3u8"
        final_entries = [
            {
                "url": official_url,
                "tvg_id": "Demo.hu",
                "channel_name": "Demo TV",
                "display_name": "Demo TV (720p)",
                "tvg_name": "Demo TV",
                "language_code": "HU",
                "source": "Broadcaster",
                "source_kind": "extras",
                "source_flags": [],
            },
            {
                "url": relay_url,
                "tvg_id": "Demo.hu",
                "channel_name": "Demo TV",
                "display_name": "Demo TV (1080p)",
                "tvg_name": "Demo TV",
                "language_code": "HU",
                "source": "Provider relay",
                "source_kind": "alternatives",
                "source_flags": [],
            },
        ]
        audit_rows = [
            {
                "channel": "Demo TV",
                "stream_url": official_url,
                "tvg_id": "Demo.hu",
                "decision": "Verified",
                "samsung": "works",
                "vlc": "works",
                "provenance": "Current broadcaster stream",
                "output_language_code": "HU",
                "in_playlist": True,
                "exclude_from_playlist": False,
            },
            {
                "channel": "Demo TV",
                "stream_url": relay_url,
                "tvg_id": "Demo.hu",
                "decision": "Verified",
                "samsung": "works",
                "vlc": "works",
                "provenance": "Panaccess provider relay",
                "output_language_code": "HU",
                "in_playlist": True,
                "exclude_from_playlist": False,
            },
        ]
        cfg = {
            "default_language_code": "HU",
            "country_names": {"HU": "Hungary"},
            "country_outputs": {"HU": "public/hu.m3u"},
            "stable_playlist": {
                "allowed_decisions": ["Verified", "TV verified"],
                "blocked_hosts": [],
                "blocked_name_terms": [],
                "blocked_source_flags": ["Offline"],
                "feed_quality": {
                    "official_source_terms": ["never-match-this-test"],
                    "provider_relay_terms": ["never-match-this-test"],
                },
            },
        }

        selected, excluded = select_stable_playlist_candidates(final_entries, audit_rows, cfg)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["url"], official_url)
        self.assertGreater(selected[0]["_feed_quality_score"], 0)
        relay_exclusion = next(row for row in excluded if row["stream_url"] == relay_url)
        self.assertIn("feed-quality score", relay_exclusion["reason"])


if __name__ == "__main__":
    unittest.main()
