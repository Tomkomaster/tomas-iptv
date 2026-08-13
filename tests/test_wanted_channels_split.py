import json
import tempfile
import unittest
from pathlib import Path

from wanted_channels import load_wanted_channels


class SplitWantedChannelCatalogTests(unittest.TestCase):
    def test_main_catalog_merges_country_catalogs(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "wanted_channels.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "channels": [
                            {
                                "country_code": "SK",
                                "channel": "TA3",
                                "priority": "P1",
                            }
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
                            {
                                "country_code": "SK",
                                "channel": "JOJ 24",
                                "priority": "P1",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            compiled = load_wanted_channels(data_dir / "wanted_channels.json")
            self.assertEqual(
                [row["channel"] for row in compiled],
                ["TA3", "JOJ 24"],
            )

    def test_duplicate_across_split_catalogs_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            common = {
                "schema_version": 1,
                "channels": [
                    {
                        "country_code": "SK",
                        "channel": "TA3",
                        "priority": "P1",
                    }
                ],
            }
            (data_dir / "wanted_channels.json").write_text(
                json.dumps(common), encoding="utf-8"
            )
            (data_dir / "wanted_channels_sk.json").write_text(
                json.dumps(common), encoding="utf-8"
            )

            with self.assertRaises(ValueError):
                load_wanted_channels(data_dir / "wanted_channels.json")


if __name__ == "__main__":
    unittest.main()
