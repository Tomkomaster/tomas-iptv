import csv
import json
import tempfile
import unittest
from pathlib import Path

from health_policy import compile_health_policy, resolve_health_policy
from healthcheck import apply_history
from migrate_audit import migrate


ROOT = Path(__file__).resolve().parents[1]


class ManualTvVerifiedHealthTests(unittest.TestCase):
    def test_policy_is_valid_and_failed_probe_is_informational(self):
        default, indexes = compile_health_policy({
            "default": "normal",
            "entries": [{
                "tvg_id": "24.sk@SD",
                "health_policy": "manual_tv_verified",
                "reason": "Manual Samsung verification is current.",
            }],
        })
        policy = resolve_health_policy(
            {"tvg_id": "24.sk@SD", "channel": ":24"},
            default=default,
            indexes=indexes,
        )
        entry = {
            "channel": ":24",
            "tvg_id": "24.sk@SD",
            "stream_url": "http://example.test/24.m3u8",
            "health_policy": policy["health_policy"],
            "health_policy_reason": policy["reason"],
            "health_policy_match": policy["matched_by"],
        }
        probe = {
            "status": "HTTP error",
            "success": False,
            "detail": "HTTP 403",
            "http_status": 403,
        }
        row = apply_history(
            entry,
            probe,
            {"consecutive_failures": 2, "checked_at": "2026-08-11 04:00:00 UTC"},
            "2026-08-12 04:00:00 UTC",
        )
        self.assertFalse(row["success"])
        self.assertFalse(row["actionable_failure"])
        self.assertEqual(row["consecutive_failures"], 0)
        self.assertFalse(row["manual_retest_recommended"])
        self.assertEqual(row["attention"], "informational")
        self.assertEqual(row["stream_state"], "manual_tv_verified_probe_failure")
        self.assertEqual(row["probe_status"], "HTTP error")
        self.assertEqual(row["status"], "TV verified; PC probe unavailable")

    def test_three_current_false_positives_are_explicitly_scoped(self):
        payload = json.loads((ROOT / "health_policy.json").read_text(encoding="utf-8"))
        default, indexes = compile_health_policy(payload)
        for tvg_id in (
            "24.sk@SD",
            "Sport.sk@SD",
            "VasarhelyiTelevizio.hu@SD",
        ):
            with self.subTest(tvg_id=tvg_id):
                result = resolve_health_policy(
                    {"tvg_id": tvg_id},
                    default=default,
                    indexes=indexes,
                )
                self.assertEqual(result["health_policy"], "manual_tv_verified")
                self.assertEqual(result["matched_by"], "tvg_id")


class ModernAuditMigrationTests(unittest.TestCase):
    def write_current(self, path: Path):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["channel", "tvg_id", "stream_url", "protocol"],
            )
            writer.writeheader()
            writer.writerow({
                "channel": "Example",
                "tvg_id": "Example.sk@SD",
                "stream_url": "https://example.test/live.m3u8",
                "protocol": "HLS",
            })

    def test_modernize_only_adds_iso_fields_and_keeps_legacy_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = root / "audit.json"
            current = root / "audit.csv"
            audit.write_text(json.dumps({
                "channels": [{
                    "channel": "Example",
                    "tvg_id": "Example.sk@SD",
                    "stream_url": "https://example.test/live.m3u8",
                    "language": "Slovak",
                    "language_code": "SK",
                    "expected_language_codes": ["SK"],
                    "observed_language_codes": ["SK"],
                }]
            }), encoding="utf-8")
            self.write_current(current)
            summary = migrate(
                audit,
                current,
                write=True,
                modernize_only=True,
            )
            item = json.loads(audit.read_text(encoding="utf-8"))["channels"][0]
            self.assertEqual(item["language_code"], "SK")
            self.assertEqual(item["playlist_country_code"], "SK")
            self.assertEqual(item["output_country_code"], "SK")
            self.assertEqual(item["language_codes"], ["slk"])
            self.assertEqual(item["expected_language_codes"], ["slk"])
            self.assertEqual(item["observed_language_codes"], ["slk"])
            self.assertEqual(summary["modernized"], 1)

    def test_cross_language_output_is_not_pinned_by_metadata_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = root / "audit.json"
            current = root / "audit.csv"
            audit.write_text(json.dumps({
                "channels": [{
                    "channel": "Cross",
                    "tvg_id": "Cross.sk@SD",
                    "stream_url": "https://example.test/cross.m3u8",
                    "language_code": "SK",
                    "expected_language_codes": ["SK"],
                    "observed_language_codes": ["CZ"],
                }]
            }), encoding="utf-8")
            self.write_current(current)
            migrate(audit, current, write=True, modernize_only=True)
            item = json.loads(audit.read_text(encoding="utf-8"))["channels"][0]
            self.assertEqual(item["playlist_country_code"], "SK")
            self.assertEqual(item["output_country_code"], "")
            self.assertEqual(item["expected_language_codes"], ["slk"])
            self.assertEqual(item["observed_language_codes"], ["ces"])

    def test_nicktoons_czech_audit_is_modern_and_not_legacy_hu_rejected(self):
        payload = json.loads((ROOT / "audit.json").read_text(encoding="utf-8"))
        rows = [
            item for item in payload["channels"]
            if item.get("stream_url")
            == "http://88.212.15.19/live/test_nicktoons/playlist.m3u8"
        ]
        self.assertEqual(len(rows), 1)
        item = rows[0]
        self.assertEqual(item["language_code"], "CZ")
        self.assertEqual(item["playlist_country_code"], "CZ")
        self.assertEqual(item["output_country_code"], "CZ")
        self.assertEqual(item["expected_language_codes"], ["ces"])
        self.assertEqual(item["observed_language_codes"], ["ces"])
        self.assertEqual(item["vlc"], "works")
        self.assertEqual(item["samsung"], "works")
        self.assertFalse(item["exclude_from_playlist"])


if __name__ == "__main__":
    unittest.main()
