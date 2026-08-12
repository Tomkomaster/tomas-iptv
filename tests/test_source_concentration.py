import unittest
from pathlib import Path

from feed_quality import classify_feed_source, score_feed_quality
from source_concentration import build_source_concentration


class SourceClassificationTests(unittest.TestCase):
    def test_requested_source_types_reuse_feed_quality_evidence(self):
        official = {
            "url": "https://official.example/live.m3u8",
            "_audit": {"quality_flags": ["official_broadcaster"]},
        }
        cdn = {
            "url": "https://cdn.example/live.m3u8",
            "_audit": {"quality_flags": ["broadcaster_cdn"]},
        }
        relay = {
            "url": "https://relay.example/live.m3u8",
            "_audit": {"quality_flags": ["provider_relay"]},
        }
        unknown = {"url": "https://unknown.example/live.m3u8", "_audit": {}}

        self.assertEqual(classify_feed_source(official)["source_type"], "Official broadcaster")
        self.assertEqual(classify_feed_source(cdn)["source_type"], "Broadcaster CDN")
        self.assertEqual(classify_feed_source(relay)["source_type"], "Third-party relay")
        self.assertEqual(classify_feed_source(unknown)["source_type"], "Unclassified")

        score = score_feed_quality(relay, {}, context={})
        keys = {component["key"] for component in score["components"]}
        self.assertIn("provider_relay", keys)

    def test_relay_wins_conflicting_provenance_classification(self):
        entry = {
            "url": "https://relay.example/live.m3u8",
            "_audit": {
                "quality_flags": [
                    "official_broadcaster",
                    "broadcaster_cdn",
                    "provider_relay",
                ]
            },
        }
        result = classify_feed_source(entry)
        self.assertTrue(result["official_broadcaster"])
        self.assertTrue(result["broadcaster_cdn"])
        self.assertTrue(result["provider_relay"])
        self.assertEqual(result["source_type"], "Third-party relay")


class SourceConcentrationTests(unittest.TestCase):
    def test_counts_percentages_and_flags_large_relay_dependency(self):
        cfg = {
            "source_concentration": {
                "warning_min_channels": 2,
                "warning_percent": 20,
                "high_min_channels": 3,
                "high_percent": 30,
                "critical_min_channels": 4,
                "critical_percent": 40,
            }
        }
        entries = []
        for index in range(4):
            entries.append({
                "country_code": "HU",
                "channel_name": f"Relay {index}",
                "url": f"https://relay.example/{index}.m3u8",
                "_audit": {"quality_flags": ["provider_relay"]},
            })
        for index in range(3):
            entries.append({
                "country_code": "HU",
                "channel_name": f"Official {index}",
                "url": f"https://official{index}.example/live.m3u8",
                "_audit": {"quality_flags": ["official_broadcaster"]},
            })
        for index in range(2):
            entries.append({
                "country_code": "HU",
                "channel_name": f"CDN {index}",
                "url": f"https://cdn.example/{index}.m3u8",
                "_audit": {"quality_flags": ["broadcaster_cdn"]},
            })
        entries.append({
            "country_code": "HU",
            "channel_name": "Unknown",
            "url": "https://unknown.example/live.m3u8",
            "_audit": {},
        })

        report = build_source_concentration(entries, cfg, generated_at="2026-08-12T18:00:00+02:00")
        hu = report["countries"]["HU"]
        counts = {row["source_type"]: row for row in hu["source_types"]}

        self.assertEqual(hu["stable_channels"], 10)
        self.assertEqual(counts["Third-party relay"]["channels"], 4)
        self.assertEqual(counts["Third-party relay"]["percent"], 40.0)
        self.assertEqual(counts["Official broadcaster"]["channels"], 3)
        self.assertEqual(counts["Broadcaster CDN"]["channels"], 2)
        self.assertEqual(counts["Unclassified"]["channels"], 1)

        relay_host = next(row for row in hu["hostnames"] if row["hostname"] == "relay.example")
        self.assertEqual(relay_host["channels"], 4)
        self.assertEqual(relay_host["third_party_relay_percent"], 40.0)
        self.assertEqual(relay_host["risk"], "critical")
        self.assertEqual(report["flags"][0]["hostname"], "relay.example")

    def test_broadcaster_cdn_concentration_is_measured_but_not_relay_flagged(self):
        entries = [
            {
                "country_code": "SK",
                "channel_name": f"JOJ {index}",
                "url": f"https://joj-cdn.example/{index}.m3u8",
                "_audit": {"quality_flags": ["broadcaster_cdn"]},
            }
            for index in range(12)
        ]
        report = build_source_concentration(entries, generated_at="now")
        host = report["countries"]["SK"]["hostnames"][0]
        self.assertEqual(host["country_percent"], 100.0)
        self.assertEqual(host["source_type"], "Broadcaster CDN")
        self.assertEqual(host["risk"], "none")
        self.assertEqual(report["flags"], [])

    def test_dashboard_loads_generated_source_concentration_report(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / "templates" / "dashboard.html").read_text(encoding="utf-8")
        js = (root / "static" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn('id="sourceConcentrationSummary"', template)
        self.assertIn('id="sourceConcentrationTable"', template)
        self.assertIn('source-concentration.json', template)
        self.assertIn("fetch('source-concentration.json'", js)
        self.assertIn('renderSourceConcentration();', js)


if __name__ == "__main__":
    unittest.main()
