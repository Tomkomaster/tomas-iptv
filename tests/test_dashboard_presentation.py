import tempfile
import unittest
from pathlib import Path

import build
from iptv.dashboard import copy_dashboard_assets


class DashboardPresentationTests(unittest.TestCase):
    def test_dashboard_presentation_is_outside_build_entrypoint(self):
        source = Path("build.py").read_text(encoding="utf-8")
        self.assertNotIn("<!doctype html>", source.lower())
        self.assertNotIn("<style>", source.lower())
        self.assertNotIn("function renderEpgCountryCoverage", source)
        self.assertIn("from iptv import dashboard as _dashboard", source)
        self.assertTrue(Path("iptv/dashboard.py").is_file())
        self.assertLess(Path("build.py").stat().st_size, 10_000)

    def test_dashboard_template_references_external_assets(self):
        template = Path("templates/dashboard.html").read_text(encoding="utf-8")
        self.assertIn('href="static/dashboard.css"', template)
        self.assertIn('src="static/dashboard.js"', template)
        self.assertNotIn("<style>", template.lower())
        self.assertNotIn("<script>", template.lower())
        self.assertIn("EPG coverage by country", template)
        self.assertIn("Needs attention", template)
        self.assertIn("Automated stream health", template)

    def test_dashboard_assets_are_publishable(self):
        with tempfile.TemporaryDirectory() as tmp:
            public = Path(tmp)
            copy_dashboard_assets(public)
            for name in ("dashboard.css", "dashboard.js"):
                generated = public / "static" / name
                source = Path("static") / name
                self.assertTrue(generated.is_file())
                self.assertEqual(generated.read_bytes(), source.read_bytes())

    def test_existing_build_api_still_exposes_make_dashboard(self):
        self.assertTrue(callable(build.make_dashboard))


if __name__ == "__main__":
    unittest.main()
