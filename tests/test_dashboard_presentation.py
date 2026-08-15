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
        self.assertIn("@@COUNTRY_PLAYLIST_LINKS@@", template)
        self.assertNotIn('href="hu.m3u">Stable Hungary', template)
        self.assertNotIn('href="ro.m3u">Stable Romania', template)

    def test_dashboard_uses_compact_view_navigation(self):
        template = Path("templates/dashboard.html").read_text(encoding="utf-8")
        css = Path("static/dashboard.css").read_text(encoding="utf-8")

        self.assertIn('class="dashboard-toolbar"', template)
        self.assertIn('href="#overview">Overview</a>', template)
        self.assertIn('href="#attention">Needs attention</a>', template)
        self.assertIn('href="#epg">EPG</a>', template)
        self.assertIn('href="#inventory">Inventory</a>', template)
        self.assertIn('id="attention" class="dashboard-section"', template)
        self.assertIn('id="inventory" class="dashboard-section"', template)
        self.assertIn(".dashboard-section:target", css)
        self.assertIn("max-height: min(62vh, 620px)", css)
        self.assertIn("position: sticky", css)

    def test_configured_country_outputs_generate_dashboard_playlist_links(self):
        cfg = {
            "site_title": "Test IPTV",
            "country_names": {
                "HU": "Hungary",
                "RO": "Romania",
                "AT": "Austria",
            },
            "country_outputs": {
                "HU": "public/hu.m3u",
                "RO": "public/ro.m3u",
                "AT": "public/at.m3u",
            },
            "epg": {"enabled": False},
        }
        page = build.make_dashboard(
            cfg=cfg,
            generated="2026-08-14 20:00:00 UTC",
            final_entries=[],
            unique_channels=[],
            source_stats=[],
            language_stats=[],
            duplicate_rows=[],
            changes={"previous_generated_at": None},
            audit_rows=[],
            audit_ambiguity_warnings=[],
            country_stats=[],
        )

        self.assertIn('href="hu.m3u">Stable Hungary (hu.m3u)</a>', page)
        self.assertIn('href="ro.m3u">Stable Romania (ro.m3u)</a>', page)
        self.assertIn('href="at.m3u">Stable Austria (at.m3u)</a>', page)
        self.assertLess(page.index("Stable Hungary"), page.index("Stable Romania"))
        self.assertLess(page.index("Stable Romania"), page.index("Stable Austria"))

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
