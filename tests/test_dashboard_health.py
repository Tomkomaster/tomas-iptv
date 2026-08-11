import unittest

from build import make_dashboard


class DashboardHealthTests(unittest.TestCase):
    def test_dashboard_includes_advisory_health_section(self):
        page = make_dashboard(
            cfg={"site_title": "Test IPTV", "epg": {"enabled": False}},
            generated="2026-08-11 08:00:00 UTC",
            final_entries=[],
            unique_channels=[],
            source_stats=[],
            language_stats=[],
            duplicate_rows=[],
            changes={
                "previous_generated_at": None,
                "added_channels": [],
                "removed_channels": [],
            },
            audit_rows=[],
            audit_ambiguity_warnings=[],
        )

        self.assertIn("Automated stream health", page)
        self.assertIn("health.json", page)
        self.assertIn("never changes manual VLC + Samsung verification", page)
        self.assertIn("healthTable", page)
        self.assertIn("fetch('health.json'", page)


if __name__ == "__main__":
    unittest.main()
