import tempfile
import unittest
from pathlib import Path

from tools.priority_coverage import build_priority_coverage, inject_priority_coverage


def audit_row(channel, tvg_id, country, *, stable=False, decision="Needs review"):
    return {
        "channel": channel,
        "tvg_id": tvg_id,
        "playlist_country_code": country,
        "playlist_language_code": country,
        "in_playlist": "True",
        "in_stable_playlist": "True" if stable else "False",
        "vlc": "works" if stable else "not_tested",
        "samsung": "works" if stable else "not_tested",
        "decision": "Verified" if stable else decision,
        "stream_url": f"https://example.test/{channel}.m3u8",
        "source": "Fixture",
        "tested_on": "2026-08-13" if stable else "",
        "exclude_from_playlist": "False",
    }


class PriorityCoverageTests(unittest.TestCase):
    def test_counts_stable_targets_and_lists_missing_targets(self):
        rows = [
            audit_row("Alpha", "Alpha.hu", "HU", stable=True),
            audit_row("Beta", "Beta.hu", "HU"),
            audit_row("Movie One", "MovieOne.hu", "HU", stable=True),
        ]
        config = {
            "country_names": {"HU": "Hungary"},
            "country_outputs": {"HU": "public/hu.m3u"},
        }
        policy = {
            "schema_version": 1,
            "default_priority": "P3",
            "entries": [
                {"country": "HU", "channel": "Movie One", "priority": "P2"},
                {"country": "HU", "channel": "Movie Two", "priority": "P2"},
            ],
        }
        wanted = [
            {"country_code": "HU", "channel": "Alpha", "tvg_id": "Alpha.hu", "priority": "P1"},
            {"country_code": "HU", "channel": "Beta", "tvg_id": "Beta.hu", "priority": "P1"},
            {"country_code": "HU", "channel": "Gamma", "tvg_id": "Gamma.hu", "priority": "P1"},
        ]

        coverage = build_priority_coverage(
            rows,
            config=config,
            priority_policy=policy,
            wanted_channels=wanted,
        )

        hu = coverage["countries"]["HU"]["priorities"]
        self.assertEqual((hu["P1"]["found"], hu["P1"]["total"]), (1, 3))
        self.assertEqual((hu["P2"]["found"], hu["P2"]["total"]), (1, 2))
        self.assertEqual(
            [item["channel"] for item in hu["P1"]["missing"]],
            ["Beta", "Gamma"],
        )
        self.assertEqual(
            [item["channel"] for item in hu["P2"]["missing"]],
            ["Movie Two"],
        )

    def test_logo_score_uses_only_stable_priority_targets(self):
        rows = [
            audit_row("Alpha", "Alpha.hu", "HU", stable=True),
            audit_row("Beta", "Beta.hu", "HU"),
            audit_row("Movie One", "MovieOne.hu", "HU", stable=True),
        ]
        config = {
            "country_names": {"HU": "Hungary"},
            "country_outputs": {"HU": "public/hu.m3u"},
        }
        policy = {
            "schema_version": 1,
            "default_priority": "P3",
            "entries": [{"country": "HU", "channel": "Movie One", "priority": "P2"}],
        }
        wanted = [
            {"country_code": "HU", "channel": "Alpha", "tvg_id": "Alpha.hu", "priority": "P1"},
            {"country_code": "HU", "channel": "Beta", "tvg_id": "Beta.hu", "priority": "P1"},
        ]
        logos = {
            "channels": [
                {"country_code": "HU", "channel": "Alpha", "tvg_id": "Alpha.hu", "quality_category": "Canonical"},
                {"country_code": "HU", "channel": "Movie One", "tvg_id": "MovieOne.hu", "quality_category": "Source fallback"},
            ]
        }

        coverage = build_priority_coverage(
            rows,
            config=config,
            priority_policy=policy,
            wanted_channels=wanted,
            logo_quality=logos,
        )

        hu = coverage["countries"]["HU"]["priorities"]
        self.assertEqual(hu["P1"]["logo_coverage"]["stable_targets"], 1)
        self.assertEqual(hu["P1"]["logo_coverage"]["canonical_logo"], 1)
        self.assertEqual(hu["P2"]["logo_coverage"]["stable_targets"], 1)
        self.assertEqual(hu["P2"]["logo_coverage"]["source_fallback"], 1)
        self.assertEqual(coverage["logo_summary"]["stable_targets"], 2)
        self.assertEqual(coverage["logo_summary"]["with_logo"], 2)
        self.assertEqual(coverage["logo_summary"]["canonical_logo"], 1)
        self.assertEqual(coverage["logo_summary"]["missing_logo"], 0)
        self.assertEqual(coverage["logo_summary"]["canonical_logo_coverage_percent"], 50.0)

    def test_logo_score_bridges_published_country_for_exact_tvg_identity(self):
        rows = [
            audit_row("AMC Europe Czech Republic", "AMCEurope.uk@CzechRepublic", "SK", stable=True),
            audit_row("Disney Channel Feed 1", "DisneyChannel.cz@SD", "HU", stable=True),
        ]
        config = {
            "country_names": {"HU": "Hungary", "SK": "Slovakia"},
            "country_outputs": {"HU": "public/hu.m3u", "SK": "public/sk.m3u"},
        }
        policy = {
            "schema_version": 1,
            "default_priority": "P3",
            "entries": [
                {"country": "SK", "channel": "AMC Europe Czech Republic", "priority": "P2"},
                {"country": "HU", "channel": "Disney Channel Feed 1", "priority": "P2"},
            ],
        }
        logos = {
            "channels": [
                {
                    "country_code": "CZ",
                    "channel": "AMC Europe Czech Republic",
                    "tvg_id": "AMCEurope.uk@CzechRepublic",
                    "quality_category": "Canonical",
                },
                {
                    "country_code": "HU",
                    "channel": "Disney Channel",
                    "tvg_id": "DisneyChannel.hu@SD",
                    "quality_category": "Source fallback",
                },
            ]
        }

        coverage = build_priority_coverage(
            rows,
            config=config,
            priority_policy=policy,
            wanted_channels=[],
            logo_quality=logos,
        )

        summary = coverage["logo_summary"]
        self.assertEqual(summary["stable_targets"], 2)
        self.assertEqual(summary["with_logo"], 2)
        self.assertEqual(summary["canonical_logo"], 1)
        self.assertEqual(summary["source_fallback"], 1)
        self.assertEqual(summary["missing_logo"], 0)
        self.assertEqual(summary["logo_availability_percent"], 100.0)

    def test_injects_prominent_scorecard_before_next_work(self):
        coverage = {
            "countries": {
                "HU": {
                    "name": "Hungary",
                    "priorities": {
                        "P1": {
                            "found": 1,
                            "total": 2,
                            "missing": [
                                {"channel": "Beta", "status": "NOT RESEARCHED", "tvg_id": "Beta.hu"}
                            ],
                        },
                        "P2": {"found": 1, "total": 1, "missing": []},
                    },
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.html"
            path.write_text(
                "<html><head></head><body>\n"
                '  <section id="nextWorkPanel" class="panel"></section>\n'
                "</body></html>",
                encoding="utf-8",
            )
            inject_priority_coverage(path, coverage)
            first = path.read_text(encoding="utf-8")
            inject_priority_coverage(path, coverage)
            second = path.read_text(encoding="utf-8")

        self.assertEqual(first, second)
        self.assertIn('id="priorityCoverage"', first)
        self.assertIn("Hungary", first)
        self.assertIn("1/2", first)
        self.assertIn("1 missing", first)
        self.assertIn("Beta", first)
        self.assertLess(first.index('id="priorityCoverage"'), first.index('id="nextWorkPanel"'))
        self.assertEqual(first.count('id="priorityCoverageStyles"'), 1)


if __name__ == "__main__":
    unittest.main()
