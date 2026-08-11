import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from epg_merge import (
    build_external_mapping,
    load_external_aliases,
    merge_guides,
)


class EpgAliasTests(unittest.TestCase):
    def test_explicit_alias_outranks_generated_name_mapping(self):
        playlist_rows = [
            ("Legacy.hu@SD", "Same Name"),
        ]
        external = ET.fromstring("""
        <tv>
          <channel id="Wrong.hu"><display-name>Same Name</display-name></channel>
          <channel id="Right.hu"><display-name>Different Name</display-name></channel>
        </tv>
        """)

        mapping, ambiguous = build_external_mapping(
            playlist_rows,
            external,
            explicit_aliases={"Legacy.hu@SD": "Right.hu"},
        )

        self.assertEqual(ambiguous, [])
        self.assertEqual(
            mapping["Right.hu"],
            {
                "tvg_id": "Legacy.hu@SD",
                "method": "external_explicit_alias",
            },
        )
        self.assertNotIn("Wrong.hu", mapping)

    def test_missing_historical_alias_is_ignored_safely(self):
        external = ET.fromstring(
            '<tv><channel id="Present.hu"><display-name>Present</display-name></channel></tv>'
        )
        mapping, ambiguous = build_external_mapping(
            [("PresentTarget.hu@SD", "Present")],
            external,
            explicit_aliases={
                "OldTarget.hu@SD": "Gone.hu",
            },
        )
        self.assertEqual(ambiguous, [])
        self.assertEqual(
            mapping["Present.hu"]["tvg_id"],
            "PresentTarget.hu@SD",
        )

    def test_alias_file_provider_must_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "aliases.json"
            path.write_text(
                json.dumps({
                    "provider": "wrong.example",
                    "aliases": {"A.hu": "B.hu"},
                }),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                load_external_aliases(
                    path,
                    "epgshare01.online",
                )

    def test_alias_can_supply_fresh_programmes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            playlist = root / "tv.m3u"
            iptv = root / "iptv.xml"
            coverage = root / "iptv.json"
            external = root / "external.xml"
            output = root / "guide.xml"
            report = root / "coverage.json"

            playlist.write_text(
                '#EXTM3U\n#EXTINF:-1 tvg-id="FilmCafe.hu@Hungary",Film Cafe\nhttps://example.test/film.m3u8\n',
                encoding="utf-8",
            )
            iptv.write_text('<tv></tv>', encoding="utf-8")
            coverage.write_text(
                json.dumps({"matched": []}),
                encoding="utf-8",
            )
            external.write_text(
                """<tv>
                <channel id="Film.Café.hu"><display-name>Film Café</display-name></channel>
                <programme start="20260811100000 +0200" stop="20260811110000 +0200" channel="Film.Café.hu"><title>Film</title></programme>
                </tv>""",
                encoding="utf-8",
            )

            result = merge_guides(
                playlist_path=playlist,
                iptv_guide_path=iptv,
                iptv_coverage_path=coverage,
                external_path=external,
                external_aliases={
                    "FilmCafe.hu@Hungary": "Film.Café.hu",
                },
                output_path=output,
                report_path=report,
                reference_date=date(2026, 8, 11),
            )

            match = result["matched"][0]
            self.assertEqual(
                match["match_type"],
                "external_explicit_alias",
            )
            self.assertEqual(match["fresh_programmes"], 1)


if __name__ == "__main__":
    unittest.main()
