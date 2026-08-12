import json
import tempfile
import unittest
from pathlib import Path

import epg_health


class CountryEpgHealthTests(unittest.TestCase):
    def test_reports_actual_programme_coverage_per_country(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coverage = root / "coverage.json"
            guide = root / "guide.xml"
            output = root / "health.json"

            coverage.write_text(
                json.dumps({
                    "playlist_tvg_ids": 4,
                    "countries": {
                        "HU": {"playlist_tvg_ids": 2},
                        "SK": {"playlist_tvg_ids": 1},
                        "CZ": {"playlist_tvg_ids": 1},
                    },
                    "tvg_id_countries": {
                        "One.hu": "HU",
                        "Two.hu": "HU",
                        "One.sk": "SK",
                        "One.cz": "CZ",
                    },
                    "matched": [
                        {"tvg_id": "One.hu", "provider": "hu.test"},
                        {"tvg_id": "Two.hu", "provider": "hu.test"},
                        {"tvg_id": "One.sk", "provider": "sk.test"},
                    ],
                }),
                encoding="utf-8",
            )
            guide.write_text(
                """<tv>
<channel id="One.hu"/><channel id="Two.hu"/><channel id="One.sk"/>
<programme channel="One.hu" start="20260812080000 +0200"><title>A</title></programme>
<programme channel="One.sk" start="20260812080000 +0200"><title>B</title></programme>
</tv>""",
                encoding="utf-8",
            )

            report = epg_health.analyse_epg_health(
                coverage_path=coverage,
                guide_path=guide,
                output_path=output,
            )

            self.assertEqual(report["countries"]["HU"]["mapped_tvg_ids"], 2)
            self.assertEqual(report["countries"]["HU"]["channels_with_programmes"], 1)
            self.assertEqual(report["countries"]["HU"]["actual_programme_coverage_percent"], 50.0)
            self.assertEqual(report["countries"]["SK"]["actual_programme_coverage_percent"], 100.0)
            self.assertEqual(report["countries"]["CZ"]["mapped_tvg_ids"], 0)
            self.assertEqual(report["countries"]["CZ"]["actual_programme_coverage_percent"], 0.0)


if __name__ == "__main__":
    unittest.main()
