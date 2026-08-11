import csv
import json
import tempfile
import unittest
from pathlib import Path

import research_exports
from research_priority import (
    compile_research_priority_policy,
    resolve_research_priority,
)


FIELDNAMES = [
    "channel",
    "feed_label",
    "feed_index",
    "feed_count",
    "tvg_id",
    "source",
    "discovery",
    "stream_url",
    "protocol",
    "expected_language_codes",
    "observed_language_codes",
    "language_match",
    "language",
    "language_code",
    "provenance",
    "source_flags",
    "vlc",
    "vlc_note",
    "samsung",
    "samsung_note",
    "decision",
    "exclude_from_playlist",
    "in_playlist",
    "in_stable_playlist",
    "tested_on",
    "reason",
    "notes",
]


def audit_row(channel, country="HU", tvg_id="", **kwargs):
    row = {
        "channel": channel,
        "feed_label": "Single",
        "feed_index": "1",
        "feed_count": "1",
        "tvg_id": tvg_id,
        "source": "Test source",
        "discovery": "Test source",
        "stream_url": f"https://example.test/{abs(hash((country, channel))) % 100000}.m3u8",
        "protocol": "HLS",
        "expected_language_codes": country,
        "observed_language_codes": country,
        "language_match": "yes",
        "language": "Hungarian" if country == "HU" else "Slovak",
        "language_code": country,
        "provenance": "Test",
        "source_flags": "",
        "vlc": "generic_error",
        "vlc_note": "",
        "samsung": "generic_error",
        "samsung_note": "",
        "decision": "Rejected",
        "exclude_from_playlist": "True",
        "in_playlist": "False",
        "in_stable_playlist": "False",
        "tested_on": "2026-08-10",
        "reason": "",
        "notes": "",
    }
    row.update(kwargs)
    return row


class ResearchPriorityTests(unittest.TestCase):
    def policy(self):
        return {
            "schema_version": 1,
            "default_priority": "P3",
            "entries": [
                {
                    "country": "HU",
                    "channel": "Major TV",
                    "priority": "P1",
                    "reason": "Major national channel.",
                }
            ],
            "rules": [
                {
                    "priority": "P5",
                    "contains_any": ["Webcam", "Identity check"],
                    "reason": "Low-value camera/test entry.",
                },
                {
                    "priority": "P4",
                    "contains_any": ["Web TV", "Religious"],
                    "reason": "Niche service.",
                },
            ],
        }

    def test_exact_override_beats_generic_rule(self):
        payload = self.policy()
        payload["entries"][0]["channel"] = "Major TV [Web TV]"
        compiled = compile_research_priority_policy(payload)
        result = resolve_research_priority(
            {"country": "HU", "channel": "Major TV [Web TV]", "tvg_id": ""},
            compiled,
        )
        self.assertEqual(result["priority"], "P1")
        self.assertEqual(result["matched_by"], "channel")

    def test_rule_and_default_priorities(self):
        compiled = compile_research_priority_policy(self.policy())
        webcam = resolve_research_priority(
            {"country": "HU", "channel": "Town square Webcam", "tvg_id": ""},
            compiled,
        )
        local = resolve_research_priority(
            {"country": "HU", "channel": "Town TV", "tvg_id": "TownTV.hu"},
            compiled,
        )
        self.assertEqual(webcam["priority"], "P5")
        self.assertTrue(webcam["matched_by"].startswith("rule:"))
        self.assertEqual(local["priority"], "P3")
        self.assertEqual(local["matched_by"], "default")

    def test_invalid_priority_and_duplicate_selector_are_rejected(self):
        with self.assertRaises(ValueError):
            compile_research_priority_policy({"default_priority": "P9"})

        payload = self.policy()
        payload["entries"].append(dict(payload["entries"][0]))
        with self.assertRaises(ValueError):
            compile_research_priority_policy(payload)

    def test_missing_csv_is_sorted_as_a_real_priority_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            public_dir = Path(tmp)
            rows = [
                audit_row("Local TV"),
                audit_row("Major TV"),
                audit_row("Nature Webcam"),
                audit_row(
                    "Candidate TV",
                    vlc="not_tested",
                    samsung="not_tested",
                    decision="Needs review",
                    exclude_from_playlist="False",
                    in_playlist="True",
                    tested_on="",
                ),
            ]
            with (public_dir / "audit.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
                writer.writeheader()
                writer.writerows(rows)

            (public_dir / "index.html").write_text(
                '<a href="audit.csv">Manual verification (CSV)</a>\n',
                encoding="utf-8",
            )

            stats = research_exports.generate_exports(
                public_dir,
                generated_at="2026-08-11 12:00:00 UTC",
                priority_policy=self.policy(),
            )

            with (public_dir / "missing.csv").open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual([row["channel"] for row in rows], [
                "Major TV",
                "Candidate TV",
                "Local TV",
                "Nature Webcam",
            ])
            self.assertEqual([row["priority"] for row in rows], ["P1", "P3", "P3", "P5"])
            self.assertEqual(rows[0]["work_type"], "Hunt new source")
            self.assertEqual(rows[1]["work_type"], "Test candidates")
            self.assertIn("Major national", rows[0]["priority_reason"])
            self.assertEqual(stats["priority_counts"]["P1"], 1)
            self.assertEqual(stats["priority_counts"]["P5"], 1)


if __name__ == "__main__":
    unittest.main()
