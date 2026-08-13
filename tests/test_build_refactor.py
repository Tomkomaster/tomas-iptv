import tempfile
import unittest
from pathlib import Path

import build
import iptv.build_core as build_core
from iptv import source_loader


class BuildRefactorTests(unittest.TestCase):
    def test_build_import_is_the_core_module_for_runtime_monkeypatching(self):
        self.assertIs(build, build_core)

        sentinel = object()
        original = build.score_feed_quality
        try:
            build.score_feed_quality = sentinel
            self.assertIs(build_core.score_feed_quality, sentinel)
        finally:
            build.score_feed_quality = original

    def test_source_loader_helpers_are_the_active_build_api(self):
        self.assertIs(build.parse_entries, source_loader.parse_entries)
        self.assertIs(build.split_extinf, source_loader.split_extinf)
        self.assertIs(build.normalize_source_kind, source_loader.normalize_source_kind)
        self.assertIs(build.source_spec, source_loader.source_spec)

    def test_playlist_writer_drops_stale_smart_builder_version(self):
        entry = {
            "lines": [
                '#EXTINF:-1 tvg-name="Example TV" group-title="General",Example TV',
                "https://example.test/live.m3u8",
            ],
            "published_name": "[HU OK] Example TV",
            "display_name": "Example TV",
            "country_code": "HU",
            "group_title": "Hungary | General",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tv.m3u"
            build.write_m3u_playlist(
                path,
                {"epg": {"enabled": False}, "default_country_code": "HU"},
                [entry],
                "2026-08-12 18:00:00 UTC",
                "Stable family playlist",
                name_style="country",
            )
            text = path.read_text(encoding="utf-8")

        self.assertIn("# Generated automatically: 2026-08-12 18:00:00 UTC", text)
        self.assertIn("# Playlist: Stable family playlist", text)
        self.assertIn("[HU] Example TV", text)
        self.assertNotIn("smart builder v19", text)

    def test_root_keeps_entrypoints_while_helpers_are_grouped(self):
        self.assertLess(Path("build.py").stat().st_size, 10_000)
        self.assertLess(
            Path("iptv/build_core.py").stat().st_size,
            20_000,
            "build_core.py should remain a thin orchestration/compatibility layer",
        )

        for path in (
            "iptv/build_core.py",
            "iptv/channel_identity.py",
            "iptv/source_loader.py",
            "iptv/deduplication.py",
            "iptv/playlist_writer.py",
            "iptv/publication.py",
            "iptv/reports.py",
            "iptv/playback_status.py",
            "iptv/language_routing.py",
            "iptv/audit.py",
            "iptv/feed_selection.py",
            "iptv/stable_selection.py",
            "iptv/dashboard.py",
            "iptv/identity_overrides.py",
            "iptv/source_concentration.py",
            "data/identity_overrides.json",
        ):
            self.assertTrue(Path(path).is_file(), path)

        for old_root_path in (
            "dashboard.py",
            "identity_overrides.py",
            "source_concentration.py",
            "identity_overrides.json",
        ):
            self.assertFalse(Path(old_root_path).exists(), old_root_path)


if __name__ == "__main__":
    unittest.main()
