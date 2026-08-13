import tempfile
import unittest
from pathlib import Path

from iptv.playlist_writer import vlc_safe_extinf_display, write_m3u_playlist


class VlcSafePlaylistNamesTests(unittest.TestCase):
    def test_only_visible_extinf_name_uses_vlc_safe_separator(self):
        line = (
            '#EXTINF:-1 tvg-id="psp.cz" '
            'tvg-name="Poslanecká sněmovna ČR - Stream 3" '
            'group-title="Czechia | Government",'
            '[CZ ?] Poslanecká sněmovna ČR - Stream 3'
        )

        result = vlc_safe_extinf_display(line)

        self.assertIn(
            'tvg-name="Poslanecká sněmovna ČR - Stream 3"',
            result,
        )
        self.assertTrue(
            result.endswith('[CZ ?] Poslanecká sněmovna ČR — Stream 3')
        )

    def test_writer_applies_vlc_safe_name_to_status_playlist(self):
        entry = {
            "lines": [
                '#EXTINF:-1 tvg-name="Frýdek-Místek - Zámecké náměstí",'
                '[CZ OK] Frýdek-Místek - Zámecké náměstí',
                "https://example.test/frydek.m3u8",
            ],
            "published_name": "[CZ OK] Frýdek-Místek - Zámecké náměstí",
            "display_name": "Frýdek-Místek - Zámecké náměstí",
            "country_code": "CZ",
            "group_title": "Czechia | Local",
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.m3u"
            write_m3u_playlist(
                path,
                {},
                [entry],
                "2026-08-13 00:00:00 UTC",
                "test",
                strip_custom_prefix=lambda value: value,
                normalize_country_code=lambda value: value,
                rewrite_entry_lines=lambda lines, name, group: lines,
            )
            text = path.read_text(encoding="utf-8")

        self.assertIn(
            'tvg-name="Frýdek-Místek - Zámecké náměstí"',
            text,
        )
        self.assertIn(
            ',[CZ OK] Frýdek-Místek — Zámecké náměstí',
            text,
        )
        self.assertNotIn(
            ',[CZ OK] Frýdek-Místek - Zámecké náměstí',
            text,
        )


if __name__ == "__main__":
    unittest.main()
