import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from epg_merge import merge_guides
from local_epg import recalculate_coverage


class CountryEpgHandoffTests(unittest.TestCase):
    def test_merge_preserves_country_metadata_and_recalculates_final_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist = root / "tv.m3u"
            iptv_guide = root / "iptv.xml"
            iptv_coverage = root / "iptv-coverage.json"
            output = root / "guide.xml"
            report_path = root / "coverage.json"

            playlist.write_text(
                "#EXTM3U\n"
                '#EXTINF:-1 tvg-id="One.hu",[HU] One\nhttps://example.test/hu\n'
                '#EXTINF:-1 tvg-id="One.sk",[SK] One\nhttps://example.test/sk\n',
                encoding="utf-8",
            )
            iptv_guide.write_text(
                """<tv>
<channel id="One.hu"><display-name>One HU</display-name></channel>
<programme start="20260812080000 +0200" stop="20260812090000 +0200" channel="One.hu"><title>HU programme</title></programme>
</tv>""",
                encoding="utf-8",
            )
            iptv_coverage.write_text(
                json.dumps({
                    "playlist_tvg_ids": 2,
                    "matched_tvg_ids": 1,
                    "countries": {
                        "HU": {"playlist_tvg_ids": 1, "sites": ["hu.test"]},
                        "SK": {"playlist_tvg_ids": 1, "sites": ["sk.test"]},
                    },
                    "tvg_id_countries": {
                        "One.hu": "HU",
                        "One.sk": "SK",
                    },
                    "matched": [
                        {
                            "tvg_id": "One.hu",
                            "provider": "hu.test",
                            "provider_xmltv_id": "One.hu",
                            "match_type": "exact",
                        }
                    ],
                }),
                encoding="utf-8",
            )

            report = merge_guides(
                playlist_path=playlist,
                iptv_guide_path=iptv_guide,
                iptv_coverage_path=iptv_coverage,
                output_path=output,
                report_path=report_path,
                reference_date=date(2026, 8, 12),
            )

            self.assertEqual(
                report["tvg_id_countries"],
                {"One.hu": "HU", "One.sk": "SK"},
            )
            self.assertEqual(report["countries"]["HU"]["playlist_tvg_ids"], 1)
            self.assertEqual(report["countries"]["HU"]["matched_tvg_ids"], 1)
            self.assertEqual(report["countries"]["HU"]["mapping_coverage_percent"], 100.0)
            self.assertEqual(report["countries"]["SK"]["playlist_tvg_ids"], 1)
            self.assertEqual(report["countries"]["SK"]["matched_tvg_ids"], 0)
            self.assertEqual(report["countries"]["SK"]["mapping_coverage_percent"], 0.0)

    def test_local_overlay_recalculation_keeps_country_totals_current(self):
        coverage = {
            "countries": {
                "HU": {"playlist_tvg_ids": 1, "sites": ["hu.test"]},
                "SK": {"playlist_tvg_ids": 1, "sites": ["sk.test"]},
            },
            "tvg_id_countries": {
                "One.hu": "HU",
                "One.sk": "SK",
            },
            "matched": [
                {"tvg_id": "One.hu", "provider": "hu.test", "fresh_programmes": 1},
                {"tvg_id": "One.sk", "provider": "local.test", "fresh_programmes": 2},
            ],
        }

        recalculate_coverage(coverage, ["One.hu", "One.sk"])

        self.assertEqual(coverage["countries"]["HU"]["matched_tvg_ids"], 1)
        self.assertEqual(coverage["countries"]["SK"]["matched_tvg_ids"], 1)
        self.assertEqual(coverage["countries"]["HU"]["mapping_coverage_percent"], 100.0)
        self.assertEqual(coverage["countries"]["SK"]["mapping_coverage_percent"], 100.0)


if __name__ == "__main__":
    unittest.main()
