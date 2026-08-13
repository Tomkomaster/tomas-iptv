import unittest

from build import (
    collapse_duplicate_quality_suffixes,
    prepare_published_entries,
    published_display_from_canonical,
)


class CanonicalPublishedNameTests(unittest.TestCase):
    def test_duplicate_identical_quality_suffix_is_collapsed(self):
        self.assertEqual(
            collapse_duplicate_quality_suffixes("Minimax (576p) (576p)"),
            "Minimax (576p)",
        )
        self.assertEqual(
            collapse_duplicate_quality_suffixes("Demo TV (1080p) (1080p)"),
            "Demo TV (1080p)",
        )
        self.assertEqual(
            collapse_duplicate_quality_suffixes("Demo TV [720p] [720P]"),
            "Demo TV [720p]",
        )

    def test_different_annotations_are_preserved(self):
        self.assertEqual(
            collapse_duplicate_quality_suffixes("Demo TV (1080p) [Geo-blocked]"),
            "Demo TV (1080p) [Geo-blocked]",
        )

    def test_candidate_and_test_words_are_not_generically_deleted(self):
        self.assertEqual(
            published_display_from_canonical(
                "Candidate Test Television",
                "Candidate Test Television (720p)",
            ),
            "Candidate Test Television (720p)",
        )

    def test_single_feed_publication_uses_canonical_identity(self):
        entries = prepare_published_entries(
            [
                {
                    "channel_name": "Minimax",
                    "tvg_name": "Minimax (576p)",
                    "display_name": "Minimax research candidate (576p) (576p)",
                    "tvg_id": "Minimax.cz",
                    "language_code": "CZ",
                    "country_name": "Czechia",
                    "content_group": "Kids",
                    "source_group_title": "Kids",
                    "group_title": "Kids",
                    "source": "Research source",
                    "classification": "Base channel",
                    "source_flags": [],
                    "url": "https://example.test/minimax.m3u8",
                    "lines": [
                        '#EXTINF:-1 tvg-id="Minimax.cz",Minimax research candidate (576p) (576p)',
                        "https://example.test/minimax.m3u8",
                    ],
                    "_decision": "Verified",
                    "_source_order": 0,
                }
            ],
            {
                "default_country_code": "HU",
                "country_names": {"CZ": "Czechia"},
            },
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["published_name"], "[CZ OK] Minimax (576p)")
        self.assertNotIn("research candidate", entries[0]["published_name"].casefold())
        self.assertNotIn("(576p) (576p)", entries[0]["published_name"] )


if __name__ == "__main__":
    unittest.main()
