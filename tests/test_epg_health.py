import json
import tempfile
import unittest

from pathlib import Path

import epg_health


class EpgHealthTests(unittest.TestCase):
    def test_reports_actual_programme_coverage_and_provider_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coverage = root / "coverage.json"
            guide = root / "guide.xml"
            grab_log = root / "grab.log"
            output = root / "health.json"

            coverage.write_text(
                json.dumps({
                    "playlist_tvg_ids": 3,
                    "matched": [
                        {
                            "tvg_id": "Duna.hu@SD",
                            "provider": "mediaklikk.hu",
                        },
                        {
                            "tvg_id": "RTL.hu@SD",
                            "provider": "musor.tv",
                        },
                    ],
                }),
                encoding="utf-8",
            )

            guide.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <channel id="Duna.hu@SD"><display-name>Duna</display-name></channel>
  <channel id="RTL.hu@SD"><display-name>RTL</display-name></channel>
  <programme channel="Duna.hu@SD" start="20260811080000 +0200" stop="20260811090000 +0200"><title>Morning</title></programme>
  <programme channel="Duna.hu@SD" start="20260811090000 +0200" stop="20260811100000 +0200"><title>News</title></programme>
</tv>
""",
                encoding="utf-8",
            )

            grab_log.write_text(
                "\n".join([
                    "[1/4] mediaklikk.hu (hu) - Duna.hu@SD - Aug 11, 2026 (2 programs)",
                    "[2/4] musor.tv (hu) - RTL.hu@SD - Aug 11, 2026 (0 programs)",
                    "ERR: Request failed with status code 403",
                ]),
                encoding="utf-8",
            )

            report = epg_health.analyse_epg_health(
                coverage_path=coverage,
                guide_path=guide,
                output_path=output,
                grab_log_path=grab_log,
            )

            self.assertEqual(
                report["status"],
                "degraded",
            )
            self.assertEqual(
                report["mapped_tvg_ids"],
                2,
            )
            self.assertEqual(
                report["channels_with_programmes"],
                1,
            )
            self.assertEqual(
                report["actual_programme_coverage_percent"],
                33.3,
            )
            self.assertEqual(
                report["mapped_channels_effective_percent"],
                50.0,
            )
            self.assertEqual(
                report["providers"]["musor.tv"]["http_errors"],
                {"403": 1},
            )
            self.assertEqual(
                report["providers"]["mediaklikk.hu"]["channels_with_programmes"],
                1,
            )
            self.assertTrue(output.is_file())

    def test_healthy_when_every_mapping_has_programmes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coverage = root / "coverage.json"
            guide = root / "guide.xml"
            output = root / "health.json"

            coverage.write_text(
                json.dumps({
                    "playlist_tvg_ids": 1,
                    "matched": [{
                        "tvg_id": "M1.hu@HD",
                        "provider": "mediaklikk.hu",
                    }],
                }),
                encoding="utf-8",
            )

            guide.write_text(
                """<tv><channel id="M1.hu@HD"/><programme channel="M1.hu@HD" start="20260811080000 +0200" stop="20260811090000 +0200"><title>News</title></programme></tv>""",
                encoding="utf-8",
            )

            report = epg_health.analyse_epg_health(
                coverage_path=coverage,
                guide_path=guide,
                output_path=output,
            )

            self.assertEqual(
                report["status"],
                "healthy",
            )
            self.assertEqual(
                report["actual_programme_coverage_percent"],
                100.0,
            )


if __name__ == "__main__":
    unittest.main()
