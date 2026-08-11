import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from local_epg import (
    Programme,
    overlay_local_epg,
    parse_cegled,
    parse_entries,
    parse_tvmustra,
)


class LocalEpgTests(unittest.TestCase):
    def test_parse_entries_handles_alternating_titles_and_midnight_rollover(self):
        programmes = parse_entries(
            [
                "20:00",
                "Evening show",
                "23:30",
                "Late movie",
                "00:45",
                "After midnight",
            ],
            date(2026, 8, 11),
            allow_rollover=True,
        )
        self.assertEqual([item.title for item in programmes], [
            "Evening show",
            "Late movie",
            "After midnight",
        ])
        self.assertEqual(programmes[2].start.date(), date(2026, 8, 12))

    def test_cegled_selects_only_current_weekday(self):
        programmes = parse_cegled(
            [
                "Hétfő",
                "18:00 Monday News",
                "Kedd",
                "0:00 Képújság",
                "18:00 Híradó",
                "18:20 Háttér",
                "Szerda",
                "18:00 Wednesday News",
            ],
            date(2026, 8, 11),
        )
        self.assertEqual(
            [item.title for item in programmes],
            ["Képújság", "Híradó", "Háttér"],
        )

    def test_tvmustra_stops_before_recommendation_times(self):
        programmes = parse_tvmustra(
            [
                "FILMBOX+ One",
                "TV Műsor",
                "20:00",
                "Main movie",
                "23:55",
                "Late movie",
                "01:30",
                "Night movie",
                "Épp most megy",
                "11:45",
                "Unrelated recommendation",
            ],
            date(2026, 8, 11),
        )
        self.assertEqual(len(programmes), 3)
        self.assertEqual(programmes[-1].title, "Night movie")
        self.assertEqual(programmes[-1].start.date(), date(2026, 8, 12))

    def test_overlay_fills_exact_uncovered_id_and_updates_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist = root / "tv.m3u"
            guide = root / "guide.xml"
            coverage = root / "coverage.json"
            report = root / "local.json"

            playlist.write_text(
                '#EXTM3U\n#EXTINF:-1 tvg-id="CeglediVarosiTelevizio.hu",Cegléd\n'
                'https://example.test/live.m3u8\n',
                encoding="utf-8",
            )
            ET.ElementTree(ET.Element("tv")).write(
                guide,
                encoding="utf-8",
                xml_declaration=True,
            )
            coverage.write_text(
                json.dumps({
                    "playlist_tvg_ids": 1,
                    "matched_tvg_ids": 0,
                    "matched": [],
                    "unmatched_tvg_ids": ["CeglediVarosiTelevizio.hu"],
                    "providers": {},
                    "fresh_channels_by_provider": {},
                }),
                encoding="utf-8",
            )

            fixture = [
                "Hétfő",
                "18:00 Monday",
                "Kedd",
                "0:00 Képújság",
                "18:00 Híradó",
                "18:20 Háttér",
                "Szerda",
                "18:00 Wednesday",
            ]

            def fetcher(url, timeout):
                if "ctv.hu" in url:
                    return fixture
                raise OSError("unused source")

            result = overlay_local_epg(
                playlist_path=playlist,
                guide_path=guide,
                coverage_path=coverage,
                report_path=report,
                reference_date=date(2026, 8, 11),
                future_days=7,
                timeout=1,
                fetcher=fetcher,
            )
            self.assertEqual(result["summary"]["filled_channels"], 1)

            data = json.loads(coverage.read_text(encoding="utf-8"))
            self.assertEqual(data["matched_tvg_ids"], 1)
            self.assertEqual(data["unmatched_tvg_ids"], [])
            self.assertEqual(data["matched"][0]["provider"], "ctv.hu")

            tv = ET.parse(guide).getroot()
            self.assertEqual(
                [node.get("id") for node in tv.findall("channel")],
                ["CeglediVarosiTelevizio.hu"],
            )
            self.assertEqual(len(tv.findall("programme")), 3)

    def test_overlay_does_not_replace_already_fresh_guide(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist = root / "tv.m3u"
            guide = root / "guide.xml"
            coverage = root / "coverage.json"
            report = root / "local.json"

            playlist.write_text(
                '#EXTM3U\n#EXTINF:-1 tvg-id="CeglediVarosiTelevizio.hu",Cegléd\n'
                'https://example.test/live.m3u8\n',
                encoding="utf-8",
            )
            tv = ET.Element("tv")
            ET.SubElement(tv, "channel", {"id": "CeglediVarosiTelevizio.hu"})
            program = ET.SubElement(tv, "programme", {
                "channel": "CeglediVarosiTelevizio.hu",
                "start": "20260811180000 +0200",
                "stop": "20260811183000 +0200",
            })
            ET.SubElement(program, "title").text = "Existing"
            ET.ElementTree(tv).write(guide, encoding="utf-8", xml_declaration=True)
            coverage.write_text(
                json.dumps({
                    "playlist_tvg_ids": 1,
                    "matched_tvg_ids": 1,
                    "matched": [{
                        "tvg_id": "CeglediVarosiTelevizio.hu",
                        "provider": "existing.example",
                        "fresh_programmes": 1,
                    }],
                    "unmatched_tvg_ids": [],
                }),
                encoding="utf-8",
            )

            def fetcher(url, timeout):
                raise AssertionError("already-covered source should not be fetched")

            result = overlay_local_epg(
                playlist_path=playlist,
                guide_path=guide,
                coverage_path=coverage,
                report_path=report,
                reference_date=date(2026, 8, 11),
                future_days=7,
                timeout=1,
                fetcher=fetcher,
            )
            self.assertEqual(result["summary"]["filled_channels"], 0)
            data = json.loads(coverage.read_text(encoding="utf-8"))
            self.assertEqual(data["matched"][0]["provider"], "existing.example")


if __name__ == "__main__":
    unittest.main()
