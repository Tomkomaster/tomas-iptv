import json
import tempfile
import unittest
from pathlib import Path

from epg.epg_policy import compile_epg_policy, resolve_epg_policy
from tools.attention import write_epg_quality_side_reports
from epg.epg_quality import (
    QUALITY_ALIAS,
    QUALITY_EXACT,
    QUALITY_GUESSED,
    QUALITY_MISSING,
    QUALITY_UNAVAILABLE,
    build_epg_quality,
    write_epg_quality_outputs,
)


ROOT = Path(__file__).resolve().parents[1]


class EpgQualityTests(unittest.TestCase):
    def sample_report(self):
        channels = [
            {"key": "HU:name:exact", "name": "Exact", "country_code": "HU", "tvg_id": "Exact.hu"},
            {"key": "HU:name:alias", "name": "Alias", "country_code": "HU", "tvg_id": "Alias.hu"},
            {"key": "HU:name:guess", "name": "Guess", "country_code": "HU", "tvg_id": "Guess.hu"},
            {"key": "HU:name:missing", "name": "Missing", "country_code": "HU", "tvg_id": ""},
            {"key": "HU:name:empty", "name": "Empty", "country_code": "HU", "tvg_id": "Empty.hu"},
            {"key": "HU:name:optional", "name": "Optional", "country_code": "HU", "tvg_id": ""},
        ]
        audit = []
        for channel in channels:
            audit.append({
                "channel": channel["name"],
                "country_code": "HU",
                "output_country_code": "HU",
                "tvg_id": channel["tvg_id"],
                "stream_url": f"https://example.test/{channel['name'].lower()}.m3u8",
                "decision": "Verified",
                "in_stable_playlist": True,
            })
        return {"channels": channels, "audit": {"channels": audit}}

    def test_five_quality_categories_and_completeness(self):
        coverage = {
            "matched": [
                {"tvg_id": "Exact.hu", "match_type": "external_exact_id", "fresh_programmes": 5},
                {"tvg_id": "Alias.hu", "match_type": "external_explicit_alias", "fresh_programmes": 5},
                {"tvg_id": "Guess.hu", "match_type": "external_unique_name", "fresh_programmes": 5},
                {"tvg_id": "Empty.hu", "match_type": "exact", "fresh_programmes": 0},
            ]
        }
        policy = {
            "default": "expected",
            "entries": [{"channel": "Optional", "status": "optional", "reason": "test"}],
        }
        quality = build_epg_quality(
            self.sample_report(), coverage,
            health={"mapped_without_programmes": [{"tvg_id": "Empty.hu", "provider": "test"}]},
            policy_payload=policy,
        )
        by_name = {row["channel"]: row for row in quality["channels"]}
        self.assertEqual(by_name["Exact"]["quality_category"], QUALITY_EXACT)
        self.assertEqual(by_name["Alias"]["quality_category"], QUALITY_ALIAS)
        self.assertEqual(by_name["Guess"]["quality_category"], QUALITY_GUESSED)
        self.assertEqual(by_name["Missing"]["quality_category"], QUALITY_MISSING)
        self.assertEqual(by_name["Empty"]["quality_category"], QUALITY_UNAVAILABLE)
        self.assertEqual(by_name["Optional"]["quality_category"], QUALITY_MISSING)

        summary = quality["summary"]
        self.assertEqual(summary["exact_tvg_id"], 1)
        self.assertEqual(summary["alias"], 1)
        self.assertEqual(summary["guessed"], 1)
        self.assertEqual(summary["missing"], 2)
        self.assertEqual(summary["epg_unavailable"], 1)
        self.assertEqual(summary["epg_expected_channels"], 5)
        self.assertEqual(summary["epg_expected_with_programmes"], 3)
        self.assertEqual(summary["epg_completeness_percent"], 60.0)

    def test_unexpected_tvg_id_collision_uses_logical_channels(self):
        report = {
            "channels": [
                {"key": "HU:name:one", "name": "One", "country_code": "HU", "tvg_id": "Shared.hu"},
                {"key": "HU:name:two", "name": "Two", "country_code": "HU", "tvg_id": "Shared.hu"},
                {"key": "HU:name:other", "name": "Other", "country_code": "HU", "tvg_id": "Other.hu"},
            ],
            "audit": {"channels": []},
        }
        quality = build_epg_quality(report, {"matched": []}, policy_payload={"default": "expected"})
        self.assertEqual(quality["summary"]["tvg_id_collision_count"], 1)
        collision = quality["tvg_id_collisions"][0]
        self.assertEqual(collision["tvg_id"], "Shared.hu")
        self.assertEqual(collision["logical_channel_count"], 2)
        self.assertEqual({row["channel"] for row in collision["channels"]}, {"One", "Two"})

    def test_verified_without_mapping_and_mapped_empty_are_separate(self):
        report = {
            "channels": [
                {"key": "HU:name:mapped", "name": "Mapped", "country_code": "HU", "tvg_id": "Mapped.hu"},
                {"key": "HU:name:unmapped", "name": "Unmapped", "country_code": "HU", "tvg_id": "Unmapped.hu"},
                {"key": "HU:name:no-id", "name": "No ID", "country_code": "HU", "tvg_id": ""},
                {"key": "HU:name:empty", "name": "Empty", "country_code": "HU", "tvg_id": "Empty.hu"},
            ],
            "audit": {"channels": [
                {"channel": "Mapped", "country_code": "HU", "tvg_id": "Mapped.hu", "decision": "Verified", "in_stable_playlist": True},
                {"channel": "Unmapped", "country_code": "HU", "tvg_id": "Unmapped.hu", "decision": "TV verified", "in_stable_playlist": True},
                {"channel": "No ID", "country_code": "HU", "tvg_id": "", "decision": "Verified", "in_stable_playlist": True},
                {"channel": "Empty", "country_code": "HU", "tvg_id": "Empty.hu", "decision": "Verified", "in_stable_playlist": True},
                {"channel": "Review", "country_code": "HU", "tvg_id": "Review.hu", "decision": "Needs review", "in_stable_playlist": True},
            ]},
        }
        coverage = {"matched": [
            {"tvg_id": "Mapped.hu", "match_type": "exact", "fresh_programmes": 2},
            {"tvg_id": "Empty.hu", "match_type": "exact", "fresh_programmes": 0},
        ]}
        health = {"mapped_without_programmes": [{"tvg_id": "Empty.hu", "provider": "test"}]}
        quality = build_epg_quality(report, coverage, health=health, policy_payload={"default": "expected"})
        gaps = quality["verified_without_epg_mapping"]
        self.assertEqual({row["channel"] for row in gaps}, {"Unmapped", "No ID"})
        self.assertEqual(
            {row["issue"] for row in gaps},
            {"no_epg_mapping", "missing_tvg_id"},
        )
        self.assertEqual(
            [row["channel"] for row in quality["verified_mapped_without_programmes"]],
            ["Empty"],
        )

    def test_modern_country_field_selects_country_policy_default(self):
        default, indexes = compile_epg_policy({
            "default": "expected",
            "country_defaults": {"CZ": "optional"},
        })
        resolved = resolve_epg_policy(
            {"channel": "Example", "output_country_code": "CZ"},
            default=default,
            indexes=indexes,
        )
        self.assertEqual(resolved["status"], "optional")
        self.assertEqual(resolved["matched_by"], "country_default")

    def test_csv_reports_are_written(self):
        report = {
            "channels": [
                {"key": "HU:name:one", "name": "One", "country_code": "HU", "tvg_id": "Shared.hu"},
                {"key": "HU:name:two", "name": "Two", "country_code": "HU", "tvg_id": "Shared.hu"},
            ],
            "audit": {"channels": [
                {"channel": "One", "country_code": "HU", "tvg_id": "Shared.hu", "decision": "Verified", "in_stable_playlist": True},
            ]},
        }
        quality = build_epg_quality(report, {"matched": []}, policy_payload={"default": "expected"})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_epg_quality_outputs(
                quality,
                output_path=root / "quality.json",
                collisions_csv_path=root / "collisions.csv",
                verified_missing_csv_path=root / "verified.csv",
            )
            self.assertEqual(json.loads((root / "quality.json").read_text(encoding="utf-8"))["schema_version"], 1)
            self.assertIn("Shared.hu", (root / "collisions.csv").read_text(encoding="utf-8-sig"))
            self.assertIn("One", (root / "verified.csv").read_text(encoding="utf-8-sig"))

    def test_attention_step_writes_epg_quality_side_reports(self):
        report = {
            "channels": [
                {"key": "HU:name:one", "name": "One", "country_code": "HU", "tvg_id": "One.hu"},
            ],
            "audit": {"channels": [
                {"channel": "One", "country_code": "HU", "tvg_id": "One.hu", "decision": "Verified", "in_stable_playlist": True},
            ]},
        }
        coverage = {"matched": [
            {"tvg_id": "One.hu", "match_type": "exact"},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            quality = write_epg_quality_side_reports(
                report=report,
                epg_coverage=coverage,
                epg_health={"mapped_without_programmes": []},
                epg_policy={"default": "expected"},
                config={"epg": {"enabled": True}},
                output_dir=root,
            )
            self.assertIsNotNone(quality)
            self.assertTrue((root / "epg-quality.json").is_file())
            self.assertTrue((root / "tvg-id-collisions.csv").is_file())
            self.assertTrue((root / "verified-without-epg.csv").is_file())

    def test_dashboard_exposes_quality_categories_and_reports(self):
        template = (ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "dashboard.js").read_text(encoding="utf-8")
        attention = (ROOT / "tools" / "attention.py").read_text(encoding="utf-8")
        for label in (
            "Exact tvg-id", "Alias", "Guessed", "Missing", "EPG unavailable",
        ):
            self.assertIn(label, template + script)
        self.assertIn("epg-quality.json", script)
        self.assertIn("tvg-id collisions", template.casefold())
        self.assertIn("Verified channels without EPG mapping", template)
        self.assertIn("write_epg_quality_side_reports", attention)
        self.assertIn("epg-quality.json", attention)


if __name__ == "__main__":
    unittest.main()
