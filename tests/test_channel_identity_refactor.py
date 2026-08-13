import unittest
from pathlib import Path

import build
from iptv import channel_identity


EXTRACTED_NAMES = ('QUALITY_SUFFIX_RE', 'TVG_VARIANT_SUFFIX_RE', 'CUSTOM_PREFIX_RE', 'INTERNAL_PROVIDER_TEST_SUFFIX_RE', 'split_display_annotations', 'deduplicate_identical_annotations', 'collapse_duplicate_quality_suffixes', 'published_display_from_canonical', 'strip_display_annotations', 'normalize_text', 'strip_internal_candidate_annotations', 'normalized_tvg_id', 'canonical_stream_url', 'apply_canonical_identity', 'channel_key', 'strip_custom_prefix')


class ChannelIdentityRefactorTests(unittest.TestCase):
    def test_build_reexports_extracted_identity_api(self):
        for name in EXTRACTED_NAMES:
            self.assertIs(getattr(build, name), getattr(channel_identity, name), name)

    def test_build_core_no_longer_defines_identity_helpers(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        for name in ('split_display_annotations', 'deduplicate_identical_annotations', 'collapse_duplicate_quality_suffixes', 'published_display_from_canonical', 'strip_display_annotations', 'normalize_text', 'strip_internal_candidate_annotations', 'normalized_tvg_id', 'canonical_stream_url', 'apply_canonical_identity', 'channel_key', 'strip_custom_prefix'):
            self.assertNotIn(f"def {name}(", text, name)
        self.assertLess(Path("iptv/build_core.py").stat().st_size, 142_000)

    def test_stream_and_channel_identity_behavior(self):
        self.assertEqual(
            channel_identity.canonical_stream_url(
                "HTTPS://Example.COM:443/live.m3u8#fragment"
            ),
            "https://example.com/live.m3u8",
        )
        self.assertEqual(channel_identity.normalized_tvg_id("Demo.hu@HD"), "demo.hu")
        self.assertEqual(
            channel_identity.normalized_tvg_id("ducktv.sk@HD"),
            "ducktvhd.sk",
        )
        self.assertEqual(
            channel_identity.channel_key({"canonical_id": "Demo.Channel"}),
            "canonical:demo.channel",
        )

    def test_display_cleanup_behavior(self):
        self.assertEqual(
            channel_identity.collapse_duplicate_quality_suffixes(
                "Demo TV (1080p) (1080p)"
            ),
            "Demo TV (1080p)",
        )
        self.assertEqual(
            channel_identity.strip_internal_candidate_annotations(
                "JOJ Šport 2 ANTIK TEST"
            ),
            "JOJ Šport 2",
        )


if __name__ == "__main__":
    unittest.main()
