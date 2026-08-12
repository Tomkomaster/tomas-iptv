import unittest
from pathlib import Path


class DashboardNextWorkPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = Path("templates/dashboard.html").read_text(encoding="utf-8")
        cls.script = Path("static/dashboard.js").read_text(encoding="utf-8")

    def test_panel_is_near_top_of_dashboard(self):
        panel = self.template.index('<section id="nextWorkPanel"')
        country_tabs = self.template.index('<nav id="countryTabs"')
        self.assertLess(panel, country_tabs)
        self.assertIn('What should I work on next?', self.template)
        self.assertIn('id="nextWorkSummary"', self.template)
        self.assertIn('id="nextWorkList"', self.template)

    def test_panel_uses_generated_operational_data(self):
        self.assertIn("fetch('attention.json'", self.script)
        self.assertIn("fetch('health.json'", self.script)
        self.assertIn("fetch('missing.csv'", self.script)
        self.assertIn("function renderNextWorkPanel()", self.script)

    def test_panel_exposes_requested_priority_counts(self):
        self.assertIn('Stream failures', self.script)
        self.assertIn('P1 channels missing', self.script)
        self.assertIn('P2 candidates', self.script)
        self.assertIn('Expected EPG gaps', self.script)

    def test_recommendations_prioritize_operations_before_research(self):
        self.assertIn('score: 500 + Number(item.priority_score || 0)', self.script)
        self.assertIn("priority === 'P1' ? 400 : 300", self.script)
        self.assertIn('score: 200 + Number(item.priority_score || 0)', self.script)
        self.assertIn('if (top.length === 8) break;', self.script)

    def test_template_keeps_behavior_external(self):
        self.assertNotIn("<script>", self.template.lower())
        self.assertIn('src="static/dashboard.js"', self.template)


if __name__ == "__main__":
    unittest.main()
