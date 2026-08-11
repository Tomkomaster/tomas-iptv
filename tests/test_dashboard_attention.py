import unittest

from build import make_dashboard


class DashboardAttentionTests(unittest.TestCase):
    def test_dashboard_includes_unified_attention_queue(self):
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

        self.assertIn("Needs attention", page)
        self.assertIn("attention.json", page)
        self.assertIn("attentionTable", page)
        self.assertIn("attentionSeverityFilter", page)
        self.assertIn("attentionCategoryFilter", page)
        self.assertIn("fetch('attention.json'", page)
        self.assertIn("Automated results remain advisory", page)


if __name__ == "__main__":
    unittest.main()
