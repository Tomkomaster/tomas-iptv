import csv
import tempfile
import unittest
from pathlib import Path

import research_exports
from wanted_channels import compile_wanted_channels


class WantedChannelTests(unittest.TestCase):
    def test_catalog_validation_and_normalization(self):
        compiled = compile_wanted_channels(
            {
                "schema_version": 1,
                "channels": [
                    {
                        "country_code": "sk",
                        "channel": "TA3",
                        "tvg_id": "TA3.sk",
                        "priority": "p1",
                    }
                ],
            }
        )
        self.assertEqual(compiled[0]["country_code"], "SK")
        self.assertEqual(compiled[0]["priority"], "P1")

        with self.assertRaises(ValueError):
            compile_wanted_channels(
                {
                    "channels": [
                        {"country_code": "SK", "channel": "TA3"},
                        {"country_code": "SK", "channel": "TA3"},
                    ]
                }
            )

        with self.assertRaises(ValueError):
            compile_wanted_channels(
                {
                    "channels": [
                        {
                            "country_code": "SK",
                            "channel": "TA3",
                            "priority": "P9",
                        }
                    ]
                }
            )

    def test_wanted_targets_cover_working_candidate_rejected_and_unseen(self):
        rows = [
            {
                "channel": "TA3",
                "tvg_id": "TA3.sk",
                "playlist_country_code": "SK",
                "in_playlist": "True",
                "in_stable_playlist": "True",
                "vlc": "works",
                "samsung": "works",
                "decision": "Verified",
            },
            {
                "channel": "Nova",
                "tvg_id": "Nova.cz",
                "playlist_country_code": "CZ",
                "in_playlist": "True",
                "in_stable_playlist": "False",
                "vlc": "not_tested",
                "samsung": "not_tested",
                "decision": "Needs review",
            },
            {
                "channel": "Hir TV",
                "tvg_id": "HirTV.hu",
                "playlist_country_code": "HU",
                "in_playlist": "False",
                "in_stable_playlist": "False",
                "vlc": "mrl_error",
                "samsung": "generic_error",
                "decision": "Rejected",
                "exclude_from_playlist": "True",
            },
        ]
        grouped = research_exports.group_channels(rows)
        wanted = compile_wanted_channels(
            {
                "channels": [
                    {
                        "country_code": "SK",
                        "channel": "TA3",
                        "tvg_id": "TA3.sk",
                        "priority": "P1",
                    },
                    {
                        "country_code": "CZ",
                        "channel": "Nova",
                        "tvg_id": "Nova.cz",
                        "priority": "P1",
                    },
                    {
                        "country_code": "HU",
                        "channel": "Hir TV",
                        "priority": "P1",
                    },
                    {
                        "country_code": "SK",
                        "channel": "Never Seen TV",
                        "tvg_id": "NeverSeenTV.sk",
                        "priority": "P2",
                    },
                ]
            }
        )

        missing = research_exports.make_missing_rows(
            grouped,
            priority_policy={"schema_version": 1, "default_priority": "P3"},
            wanted_channels=wanted,
        )
        by_name = {row["channel"]: row for row in missing}

        self.assertNotIn("TA3", by_name)
        self.assertEqual(by_name["Nova"]["status"], "CANDIDATES TO TEST")
        self.assertEqual(by_name["Hir TV"]["status"], "NO WORKING FEED")
        self.assertEqual(by_name["Never Seen TV"]["status"], "NOT RESEARCHED")

        unseen = by_name["Never Seen TV"]
        self.assertTrue(unseen["wanted"])
        self.assertEqual(unseen["known_feeds"], 0)
        self.assertEqual(unseen["current_candidates"], 0)
        self.assertEqual(unseen["tested_feeds"], 0)
        self.assertEqual(unseen["priority"], "P2")
        self.assertEqual(unseen["priority_match"], "wanted_channels")
        self.assertEqual(unseen["work_type"], "Find first candidate")
        self.assertIn("Find the first candidate", unseen["next_action"])

        self.assertTrue(by_name["Nova"]["wanted"])
        self.assertEqual(by_name["Nova"]["priority"], "P1")
        self.assertEqual(by_name["Nova"]["priority_match"], "wanted_channels")

    def test_unwanted_encountered_channels_remain_in_backlog(self):
        grouped = research_exports.group_channels(
            [
                {
                    "channel": "Regional Demo",
                    "tvg_id": "RegionalDemo.sk",
                    "playlist_country_code": "SK",
                    "in_playlist": "True",
                    "in_stable_playlist": "False",
                    "decision": "Needs review",
                    "vlc": "not_tested",
                    "samsung": "not_tested",
                }
            ]
        )
        missing = research_exports.make_missing_rows(
            grouped,
            priority_policy={"schema_version": 1, "default_priority": "P3"},
            wanted_channels=[],
        )
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["channel"], "Regional Demo")
        self.assertFalse(missing[0]["wanted"])
        self.assertEqual(missing[0]["status"], "CANDIDATES TO TEST")

    def test_generate_exports_writes_unseen_wanted_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            public_dir = Path(tmp)
            fieldnames = [
                "channel",
                "tvg_id",
                "playlist_country_code",
                "in_playlist",
                "in_stable_playlist",
                "vlc",
                "samsung",
                "decision",
            ]
            with (public_dir / "audit.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(
                    {
                        "channel": "Existing Demo",
                        "tvg_id": "ExistingDemo.sk",
                        "playlist_country_code": "SK",
                        "in_playlist": "True",
                        "in_stable_playlist": "False",
                        "vlc": "not_tested",
                        "samsung": "not_tested",
                        "decision": "Needs review",
                    }
                )

            (public_dir / "index.html").write_text(
                '<a href="audit.csv">Manual verification (CSV)</a>',
                encoding="utf-8",
            )
            wanted = compile_wanted_channels(
                {
                    "channels": [
                        {
                            "country_code": "CZ",
                            "channel": "Never Seen TV",
                            "tvg_id": "NeverSeenTV.cz",
                            "priority": "P1",
                        }
                    ]
                }
            )
            stats = research_exports.generate_exports(
                public_dir,
                generated_at="2026-08-12 17:00:00 UTC",
                priority_policy={"schema_version": 1, "default_priority": "P3"},
                wanted_channels=wanted,
            )

            with (public_dir / "missing.csv").open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                missing = list(csv.DictReader(handle))

            unseen = next(row for row in missing if row["channel"] == "Never Seen TV")
            self.assertEqual(unseen["wanted"], "True")
            self.assertEqual(unseen["status"], "NOT RESEARCHED")
            self.assertEqual(unseen["known_feeds"], "0")
            self.assertEqual(unseen["priority"], "P1")
            self.assertEqual(stats["wanted_channels"], 1)
            self.assertEqual(stats["wanted_missing"], 1)
            self.assertEqual(stats["wanted_not_researched"], 1)


if __name__ == "__main__":
    unittest.main()
