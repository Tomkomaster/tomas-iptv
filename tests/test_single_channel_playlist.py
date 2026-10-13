import unittest

import build


class SingleChannelPlaylistTests(unittest.TestCase):
    def test_uses_only_czech_prima_cool(self):
        slovak = {
            "country_code": "SK",
            "tvg_id": "PrimaCoolSK.sk@SD",
            "published_name": "[SK OK] Prima Cool SK",
        }
        czech = {
            "country_code": "CZ",
            "tvg_id": "PrimaCool.cz@HD",
            "published_name": "[CZ OK] Prima Cool",
        }
        another = {
            "country_code": "CZ",
            "tvg_id": "PrimaLove.cz",
            "published_name": "[CZ OK] Prima Love",
        }
        self.assertEqual(
            build.select_prima_cool_cz_entries([slovak, czech, another]),
            [czech],
        )

    def test_falls_back_to_name_when_guide_id_is_missing(self):
        czech = {
            "country_code": "CZ",
            "published_name": "[CZ OK] Prima Cool",
        }
        self.assertEqual(
            build.select_prima_cool_cz_entries([czech]),
            [czech],
        )

    def test_limits_multiple_candidates_to_one_feed(self):
        entries = [
            {"country_code": "CZ", "tvg_id": "PrimaCool.cz@HD"},
            {"country_code": "CZ", "tvg_id": "PrimaCool.cz@SD"},
        ]
        self.assertEqual(
            build.select_prima_cool_cz_entries(entries),
            entries[:1],
        )

    def test_no_czech_feed_returns_empty_playlist_entries(self):
        self.assertEqual(
            build.select_prima_cool_cz_entries([
                {"country_code": "SK", "tvg_id": "PrimaCoolSK.sk"}
            ]),
            [],
        )


if __name__ == "__main__":
    unittest.main()
