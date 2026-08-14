import json
import tempfile
import unittest
from pathlib import Path

from wanted_channels import load_wanted_channels


class WantedChannelSplitTests(unittest.TestCase):
    def test_country_split_can_replace_legacy_rows_for_one_country(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            main_path = data_dir / "wanted_channels.json"
            main_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "channels": [
                            {"country_code": "CZ", "channel": "Nova", "priority": "P1"},
                            {"country_code": "SK", "channel": "TA3", "priority": "P1"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "wanted_channels_cz.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "replace_country": "CZ",
                        "channels": [
                            {"country_code": "CZ", "channel": "Prima Max", "priority": "P2"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "wanted_channels_sk.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "channels": [
                            {"country_code": "SK", "channel": "TV JOJ", "priority": "P1"}
                        ],
                    }
                ),
                encoding="utf-8",
            )

            compiled = load_wanted_channels(main_path)
            names = {(row["country_code"], row["channel"]) for row in compiled}
            self.assertNotIn(("CZ", "Nova"), names)
            self.assertIn(("CZ", "Prima Max"), names)
            self.assertIn(("SK", "TA3"), names)
            self.assertIn(("SK", "TV JOJ"), names)

    def test_fully_split_catalogs_work_without_legacy_master_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            main_path = data_dir / "wanted_channels.json"
            (data_dir / "wanted_channels_hu.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "channels": [
                            {"country_code": "HU", "channel": "Duna", "priority": "P1"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "wanted_channels_ro.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "replace_country": "RO",
                        "channels": [
                            {"country_code": "RO", "channel": "PRO TV", "priority": "P1"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "wanted_channels_at.json").write_text(
                json.dumps({"schema_version": 1, "channels": []}),
                encoding="utf-8",
            )

            compiled = load_wanted_channels(main_path)
            names = {(row["country_code"], row["channel"]) for row in compiled}
            self.assertEqual(names, {("HU", "Duna"), ("RO", "PRO TV")})

    def test_duplicate_detection_still_applies_after_split_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            main_path = data_dir / "wanted_channels.json"
            main_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "channels": [
                            {"country_code": "SK", "channel": "TA3", "priority": "P1"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "wanted_channels_sk.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "channels": [
                            {"country_code": "SK", "channel": "TA3", "priority": "P1"}
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Duplicate wanted channel name"):
                load_wanted_channels(main_path)


if __name__ == "__main__":
    unittest.main()
