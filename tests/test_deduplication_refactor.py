import unittest
from pathlib import Path

import build
from identity_overrides import IdentityRegistry
from iptv import deduplication


class DeduplicationRefactorTests(unittest.TestCase):
    def test_build_reexports_source_flag_helper(self):
        self.assertIs(build.extract_source_flags, deduplication.extract_source_flags)

    def test_core_main_no_longer_owns_seen_url_loop(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        self.assertNotIn("seen_urls: dict[str, dict]", text)
        self.assertNotIn("for source_index, spec in enumerate(", text)
        self.assertIn("collect_source_entries(", text)

    def test_canonical_equivalent_urls_are_globally_deduplicated(self):
        cfg = {
            "country_outputs": {"HU": "public/hu.m3u"},
            "country_names": {"HU": "Hungary"},
            "sources": [
                {"name": "One", "path": "one.m3u", "kind": "base", "country_code": "HU", "language_codes": ["hun"]},
                {"name": "Two", "path": "two.m3u", "kind": "base", "country_code": "HU", "language_codes": ["hun"]},
            ],
        }
        playlists = {
            "one.m3u": """#EXTM3U
#EXTINF:-1 tvg-id="Demo.hu" group-title="News",Demo
https://example.test:443/live.m3u8
""",
            "two.m3u": """#EXTM3U
#EXTINF:-1 tvg-id="Demo.hu" group-title="News",Demo
https://example.test/live.m3u8
""",
        }
        registry = IdentityRegistry({"schema_version": 1, "identities": {}, "selectors": []})
        final_entries, language_only, duplicates, stats = deduplication.collect_source_entries(
            cfg,
            registry,
            {"HU"},
            remote_loader=lambda url: (_ for _ in ()).throw(AssertionError(url)),
            local_loader=lambda path: playlists[path],
        )
        self.assertEqual(len(final_entries), 1)
        self.assertEqual(language_only, [])
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(stats[1]["duplicate_urls_ignored"], 1)

    def test_source_flags_stay_normalized(self):
        self.assertEqual(
            deduplication.extract_source_flags("Demo [Geo-blocked] [Not 24/7]"),
            ["Geo-blocked", "Not 24/7"],
        )


if __name__ == "__main__":
    unittest.main()
