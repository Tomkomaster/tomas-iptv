import unittest
from pathlib import Path


class DashboardNextWorkPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = Path("templates/dashboard.html").read_text(encoding="utf-8")

    def test_panel_is_near_top_of_dashboard(self):
        summary_end = self.template.index('</div>\n\n  <section id="nextWorkPanel"')
        country_tabs = self.template.index('<nav id="countryTabs"')
        self.assertLess(summary_end, country_tabs)
        self.assertIn('What should I work on next?', self.template)
        self.assertIn('id="nextWorkSummary"', self.template)
        self.assertIn('id="nextWorkList"', self.template)

    def test_panel_uses_generated_operational_data(self):
        self.assertIn("fetch('attention.json'", self.template)
        self.assertIn("fetch('health.json'", self.template)
        self.assertIn("fetch('missing.csv'", self.template)
        self.assertIn("fetch('research.csv'", self.template)

    def test_panel_exposes_requested_priority_counts(self):
        self.assertIn('Stream failures', self.template)
        self.assertIn('P1 channels missing', self.template)
        self.assertIn('P2 candidates', self.template)
        self.assertIn('Expected EPG gaps', self.template)

    def test_recommendations_prioritize_operations_before_research(self):
        self.assertIn('score: 500 + Number(item.priority_score || 0)', self.template)
        self.assertIn("priority === 'P1' ? 400 : 300", self.template)
        self.assertIn('score: 200 + Number(item.priority_score || 0)', self.template)
        self.assertIn('if (top.length === 8) break;', self.template)


if __name__ == "__main__":
    unittest.main()
