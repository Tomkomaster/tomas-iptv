import json
import unittest
from pathlib import Path

from iptv.identity_overrides import load_identity_registry


class TargetedEpgIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_identity_registry(Path("data/identity_overrides.json"))
        cls.aliases = json.loads(
            Path("data/epg_aliases.json").read_text(encoding="utf-8")
        )["aliases"]

    def test_selected_slovak_streams_have_stable_epg_identities(self):
        cases = {
            "https://ocko-live-dash.ssl.cdn.cra.cz/cra_live2/ocko.stream.1.smil/playlist.m3u8": (
                "sk:ocko",
                "Ocko.sk",
            ),
            "http://88.212.15.19/live/test_joj_svet/playlist.m3u8": (
                "sk:joj-svet",
                "JOJSvet.sk",
            ),
            "https://dash2.antik.sk/live/rik_atk/index.m3u8": (
                "sk:rik-tv",
                "TVRiK.sk",
            ),
            "http://88.212.15.19/live/test_folklorika_atktv/playlist.m3u8": (
                "sk:folklorika-tv",
                "FolklorikaTV.sk",
            ),
        }

        for url, (canonical_id, tvg_id) in cases.items():
            with self.subTest(url=url):
                result = self.registry.resolve({"url": url})
                self.assertIsNotNone(result)
                self.assertEqual(result["canonical_id"], canonical_id)
                self.assertEqual(result["identity"]["tvg_id"], tvg_id)
                self.assertEqual(result["identity"]["country_code"], "SK")

    def test_romanian_axn_white_keeps_audited_tvg_id(self):
        result = self.registry.resolve({
            "url": "https://t.freetv.fun/live/axn-white.m3u8",
        })
        self.assertIsNotNone(result)
        self.assertEqual(result["canonical_id"], "ro:axn-white")
        self.assertEqual(result["identity"]["tvg_id"], "AXNWhite.us@SD")
        self.assertEqual(result["identity"]["country_code"], "RO")

    def test_targeted_aliases_are_explicit_and_country_specific(self):
        expected = {
            "FolklorikaTV.sk": "Folklorika.TV.HD.sk",
            "JOJSvet.sk": "JOJ.Svet.HD.sk",
            "Ocko.sk": "Óčko.HD.sk",
            "TVRiK.sk": "TV.RiK.HD.sk",
            "AXNWhite.us@SD": "AXN.White.ro",
        }
        for tvg_id, external_id in expected.items():
            with self.subTest(tvg_id=tvg_id):
                self.assertEqual(self.aliases[tvg_id], external_id)

    def test_kanal_d2_targets_primary_ro1_identity(self):
        # RO1 already contains Kanal D2. The RO2 fallback entry is intentionally
        # filtered as a duplicate display name, so an alias to the RO2 ID can
        # never resolve in the combined guide.
        self.assertEqual(
            self.aliases["KanalD2.ro@SD"],
            "Kanal.D2.ro",
        )
        self.assertNotEqual(
            self.aliases["KanalD2.ro@SD"],
            "Kanal.D2.(HD).ro",
        )


if __name__ == "__main__":
    unittest.main()
