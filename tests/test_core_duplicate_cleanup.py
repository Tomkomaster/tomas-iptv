import unittest
from pathlib import Path

import build
from iptv import playlist_writer, source_loader


class CoreDuplicateCleanupTests(unittest.TestCase):
    def test_source_helpers_are_not_redefined_in_core(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        for name in (
            "http_get_text", "download_m3u", "split_extinf", "parse_entries",
            "normalize_source_kind", "source_spec", "playlist_header",
        ):
            self.assertNotIn(f"def {name}(", text, name)

    def test_build_uses_canonical_source_helpers(self):
        self.assertIs(build.http_get_text, source_loader.http_get_text)
        self.assertIs(build.download_m3u, source_loader.download_m3u)
        self.assertIs(build.split_extinf, source_loader.split_extinf)
        self.assertIs(build.parse_entries, source_loader.parse_entries)
        self.assertIs(build.normalize_source_kind, source_loader.normalize_source_kind)
        self.assertIs(build.source_spec, source_loader.source_spec)
        self.assertIs(build.playlist_header, playlist_writer.playlist_header)

    def test_playlist_writer_core_copy_is_only_a_wrapper(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        self.assertEqual(text.count("def write_m3u_playlist("), 1)
        self.assertIn("return _write_m3u_playlist(", text)
        self.assertNotIn("# Tomas IPTV smart builder v19", text)


if __name__ == "__main__":
    unittest.main()
