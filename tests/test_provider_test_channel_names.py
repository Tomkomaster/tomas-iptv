import tempfile
import unittest
from pathlib import Path

import build


class ProviderTestChannelNameTests(unittest.TestCase):
    def test_strips_internal_provider_test_suffixes(self):
        cases = {
            "Televízia Turiec - PANACCESS TEST": "Televízia Turiec",
            "Televízia ZEMPLÍN - ANTIK TEST": "Televízia ZEMPLÍN",
            "Bardejovská TV - KABELKO TEST": "Bardejovská TV",
            "TV REGION - LEGACY TEST": "TV REGION",
            "JOJ +1 - LEGACY ANTIK TEST": "JOJ +1",
            "JOJ Šport 2 ANTIK TEST": "JOJ Šport 2",
            "JOJ Cinema JOJ CDN TEST": "JOJ Cinema",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(
                    build.strip_internal_candidate_annotations(raw),
                    expected,
                )

    def test_provider_suffix_does_not_create_a_new_logical_identity(self):
        clean = build.parse_entries(
            '#EXTM3U\n#EXTINF:-1 tvg-name="JOJ Šport 2",JOJ Šport 2\nhttps://example.test/clean.m3u8\n'
        )[0]
        antik = build.parse_entries(
            '#EXTM3U\n#EXTINF:-1 tvg-name="JOJ Šport 2 ANTIK TEST",JOJ Šport 2\nhttps://example.test/antik.m3u8\n'
        )[0]
        rebit = build.parse_entries(
            '#EXTM3U\n#EXTINF:-1 tvg-name="JOJ Šport 2 REBIT TEST",JOJ Šport 2\nhttps://example.test/rebit.m3u8\n'
        )[0]
        self.assertEqual(build.channel_key(clean), build.channel_key(antik))
        self.assertEqual(build.channel_key(clean), build.channel_key(rebit))

    def test_published_playlist_uses_channel_and_language_not_provider_label(self):
        source = build.parse_entries(
            '#EXTM3U\n'
            '#EXTINF:-1 tvg-id="TVSen.sk" tvg-name="TV Sen" group-title="Slovakia Test",TV Sen - PANACCESS TEST\n'
            'https://cdn.example.test/tvsen/index.m3u8\n'
        )[0]
        source.update({
            "channel_name": "TV Sen - PANACCESS TEST",
            "language_code": "SK",
            "country_name": "Slovakia",
            "content_group": "General",
            "source_group_title": "Slovakia Test",
            "_decision": "Verified",
            "_source_order": 1,
        })

        published = build.prepare_published_entries(
            [source],
            {"default_country_code": "HU", "country_names": {"SK": "Slovakia"}},
        )
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0]["published_name"], "[SK OK] TV Sen")
        self.assertNotIn("PANACCESS TEST", published[0]["lines"][0])
        self.assertIn('tvg-name="TV Sen"', published[0]["lines"][0])

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tv.m3u"
            build.write_m3u_playlist(
                path,
                {"default_country_code": "HU", "country_names": {"SK": "Slovakia"}},
                published,
                "2026-08-12 00:00:00 UTC",
                "test",
                name_style="language",
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn(",[SK] TV Sen", text)
            self.assertNotIn("PANACCESS TEST", text)


if __name__ == "__main__":
    unittest.main()
