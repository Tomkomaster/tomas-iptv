import csv
import json
import tempfile
import unittest
from pathlib import Path

import build


class LanguageScopingRegressionTests(unittest.TestCase):
    def test_same_channel_identity_in_hu_and_sk_survives_both_playlists(self):
        hu_url = "https://example.test/shared-hu.m3u8"
        sk_url = "https://example.test/shared-sk.m3u8"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            (root / "audit.json").write_text(
                json.dumps({
                    "channels": [
                        {
                            "channel": "Shared TV",
                            "stream_url": hu_url,
                            "vlc": "works",
                            "samsung": "works",
                            "decision": "auto",
                        },
                        {
                            "channel": "Shared TV",
                            "stream_url": sk_url,
                            "vlc": "works",
                            "samsung": "works",
                            "decision": "auto",
                        },
                    ]
                }),
                encoding="utf-8",
            )

            (root / "hu-source.m3u").write_text(
                '#EXTM3U\n'
                '#EXTINF:-1 tvg-id="SharedTV.example@HD" '
                'tvg-name="Shared TV",Shared TV\n'
                f'{hu_url}\n',
                encoding="utf-8",
            )

            (root / "sk-source.m3u").write_text(
                '#EXTM3U\n'
                '#EXTINF:-1 tvg-id="SharedTV.example@SD" '
                'tvg-name="Shared TV",Shared TV\n'
                f'{sk_url}\n',
                encoding="utf-8",
            )

            (root / "config.json").write_text(
                json.dumps({
                    "site_title": "Test",
                    "default_language_code": "HU",
                    "country_names": {
                        "HU": "Hungary",
                        "SK": "Slovakia",
                    },
                    "output": "public/tv.m3u",
                    "test_output": "public/test.m3u",
                    "country_outputs": {
                        "HU": "public/hu.m3u",
                        "SK": "public/sk.m3u",
                    },
                    "audit_path": "audit.json",
                    "sources": [
                        {
                            "name": "Hungary",
                            "kind": "base",
                            "language_code": "HU",
                            "path": "hu-source.m3u",
                        },
                        {
                            "name": "Slovakia",
                            "kind": "base",
                            "language_code": "SK",
                            "path": "sk-source.m3u",
                        },
                    ],
                    "extras": [],
                }),
                encoding="utf-8",
            )

            old_root = build.ROOT
            try:
                build.ROOT = root
                build.main()
            finally:
                build.ROOT = old_root

            hu_playlist = (root / "public" / "hu.m3u").read_text(
                encoding="utf-8"
            )
            sk_playlist = (root / "public" / "sk.m3u").read_text(
                encoding="utf-8"
            )

            self.assertIn(hu_url, hu_playlist)
            self.assertNotIn(sk_url, hu_playlist)
            self.assertIn(sk_url, sk_playlist)
            self.assertNotIn(hu_url, sk_playlist)

            with (root / "public" / "channels.csv").open(
                encoding="utf-8-sig",
                newline="",
            ) as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(len(rows), 2)
            self.assertEqual(
                {row["classification"] for row in rows},
                {"Base channel"},
            )

            report = json.loads(
                (root / "public" / "report.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(report["summary"]["unique_channels"], 2)


class AuditBooleanRegressionTests(unittest.TestCase):
    def test_string_false_exclude_is_rejected(self):
        audit = [{
            "channel": "Demo TV",
            "stream_url": "https://example.test/demo.m3u8",
            "exclude_from_playlist": "false",
        }]

        with self.assertRaisesRegex(
            RuntimeError,
            "exclude_from_playlist must be true or false",
        ):
            build.validate_audit_items(audit, [])

    def test_real_false_does_not_exclude_verified_stream(self):
        decision, _ = build.calculate_audit_decision({
            "vlc": "works",
            "samsung": "works",
            "decision": "auto",
            "exclude_from_playlist": False,
        })

        self.assertEqual(decision, "Verified")


if __name__ == "__main__":
    unittest.main()
