import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import epg_country_prepare


class CountryEpgPrepareTests(unittest.TestCase):
    def test_each_country_uses_its_own_provider_priority_and_reports_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public = root / "public"
            public.mkdir()

            playlists = {
                "HU": ("hu.m3u", "M1.hu@HD", "M1"),
                "SK": ("sk.m3u", "ArenaSport1.sk@SD", "Arena Sport 1"),
                "CZ": ("cz.m3u", "Ocko.cz@SD", "Óčko"),
            }
            for code, (filename, tvg_id, name) in playlists.items():
                (public / filename).write_text(
                    "\n".join([
                        "#EXTM3U",
                        f'#EXTINF:-1 tvg-id="{tvg_id}",{name}',
                        f"https://example.test/{code.lower()}",
                        "",
                    ]),
                    encoding="utf-8",
                )

            cfg = {
                "country_outputs": {
                    "HU": "public/hu.m3u",
                    "SK": "public/sk.m3u",
                    "CZ": "public/cz.m3u",
                },
                "epg": {
                    "countries": {
                        "HU": {"sites": ["hu.test", "shared.test"]},
                        "SK": {"sites": ["sk.test", "shared.test"]},
                        "CZ": {"sites": ["cz.test", "shared.test"]},
                    }
                },
            }
            config_path = root / "config.json"
            config_path.write_text(json.dumps(cfg), encoding="utf-8")

            epg_root = root / "epg"
            provider_rows = {
                "hu.test": '<channel site="hu.test" lang="hu" xmltv_id="M1.hu@SD" site_id="hu-m1">M1 HU</channel>',
                "sk.test": '<channel site="sk.test" lang="sk" xmltv_id="ArenaSport1.sk@SD" site_id="sk-arena">Arena SK</channel>',
                "cz.test": '<channel site="cz.test" lang="cs" xmltv_id="Ocko.cz@SD" site_id="cz-ocko">Óčko CZ</channel>',
                "shared.test": "\n".join([
                    '<channel site="shared.test" lang="hu" xmltv_id="M1.hu@SD" site_id="shared-m1">M1 shared</channel>',
                    '<channel site="shared.test" lang="sk" xmltv_id="ArenaSport1.sk@SD" site_id="shared-arena">Arena shared</channel>',
                    '<channel site="shared.test" lang="cs" xmltv_id="Ocko.cz@SD" site_id="shared-ocko">Óčko shared</channel>',
                ]),
            }
            for site, rows in provider_rows.items():
                site_dir = epg_root / "sites" / site
                site_dir.mkdir(parents=True)
                (site_dir / f"{site}.channels.xml").write_text(
                    f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<channels>\n{rows}\n</channels>\n",
                    encoding="utf-8",
                )

            output = root / "channels.xml"
            report_path = root / "coverage.json"
            report = epg_country_prepare.prepare_country_epg(
                config_path=config_path,
                epg_root=epg_root,
                output_path=output,
                report_path=report_path,
            )

            channels = ET.parse(output).getroot().findall("channel")
            self.assertEqual(
                [channel.get("site") for channel in channels],
                ["hu.test", "sk.test", "cz.test"],
            )
            self.assertEqual(report["playlist_tvg_ids"], 3)
            self.assertEqual(report["matched_tvg_ids"], 3)
            self.assertEqual(report["mapping_coverage_percent"], 100.0)
            self.assertEqual(
                report["tvg_id_countries"],
                {
                    "M1.hu@HD": "HU",
                    "ArenaSport1.sk@SD": "SK",
                    "Ocko.cz@SD": "CZ",
                },
            )
            self.assertEqual(report["countries"]["HU"]["matched_tvg_ids"], 1)
            self.assertEqual(report["countries"]["SK"]["matched_tvg_ids"], 1)
            self.assertEqual(report["countries"]["CZ"]["matched_tvg_ids"], 1)
            self.assertTrue(report_path.is_file())

    def test_external_only_country_can_continue_with_zero_iptv_org_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public = root / "public"
            public.mkdir()
            (public / "ro.m3u").write_text(
                "\n".join([
                    "#EXTM3U",
                    '#EXTINF:-1 tvg-id="TVR1.ro@SD",TVR 1',
                    "https://example.test/tvr1",
                    "",
                ]),
                encoding="utf-8",
            )

            cfg = {
                "country_outputs": {"RO": "public/ro.m3u"},
                "epg": {
                    "countries": {
                        "RO": {
                            "sites": ["external-only.test"],
                            "external": {
                                "provider": "epgshare01.online",
                                "url": "https://example.test/ro.xml.gz",
                            },
                        }
                    }
                },
            }
            config_path = root / "config.json"
            config_path.write_text(json.dumps(cfg), encoding="utf-8")

            site_dir = root / "epg" / "sites" / "external-only.test"
            site_dir.mkdir(parents=True)
            (site_dir / "external-only.test.channels.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<channels>
  <channel site="external-only.test" lang="ro" xmltv_id="" site_id="RO1#TVR1.ro">TVR 1</channel>
</channels>
""",
                encoding="utf-8",
            )

            output = root / "channels.xml"
            report_path = root / "coverage.json"
            report = epg_country_prepare.prepare_country_epg(
                config_path=config_path,
                epg_root=root / "epg",
                output_path=output,
                report_path=report_path,
            )

            self.assertEqual(report["playlist_tvg_ids"], 1)
            self.assertEqual(report["matched_tvg_ids"], 0)
            self.assertEqual(report["unmatched_tvg_ids"], ["TVR1.ro@SD"])
            self.assertEqual(report["tvg_id_countries"], {"TVR1.ro@SD": "RO"})
            self.assertEqual(report["countries"]["RO"]["mapping_coverage_percent"], 0.0)
            self.assertEqual(ET.parse(output).getroot().findall("channel"), [])
            self.assertTrue(report_path.is_file())

    def test_zero_matches_without_external_epg_still_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public = root / "public"
            public.mkdir()
            (public / "ro.m3u").write_text(
                "\n".join([
                    "#EXTM3U",
                    '#EXTINF:-1 tvg-id="TVR1.ro@SD",TVR 1',
                    "https://example.test/tvr1",
                    "",
                ]),
                encoding="utf-8",
            )

            cfg = {
                "country_outputs": {"RO": "public/ro.m3u"},
                "epg": {
                    "countries": {
                        "RO": {"sites": ["no-match.test"]},
                    }
                },
            }
            config_path = root / "config.json"
            config_path.write_text(json.dumps(cfg), encoding="utf-8")

            site_dir = root / "epg" / "sites" / "no-match.test"
            site_dir.mkdir(parents=True)
            (site_dir / "no-match.test.channels.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<channels>
  <channel site="no-match.test" lang="ro" xmltv_id="" site_id="1">TVR 1</channel>
</channels>
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                RuntimeError,
                "No playlist tvg-id values matched the configured EPG sites",
            ):
                epg_country_prepare.prepare_country_epg(
                    config_path=config_path,
                    epg_root=root / "epg",
                    output_path=root / "channels.xml",
                    report_path=root / "coverage.json",
                )


if __name__ == "__main__":
    unittest.main()
