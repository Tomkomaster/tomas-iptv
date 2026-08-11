import csv
import json
import tempfile
import unittest

from pathlib import Path

import migrate_audit


class AuditMigrationTests(unittest.TestCase):
    def write_current(self, path: Path, rows: list[dict]):
        fieldnames = [
            "channel",
            "tvg_id",
            "stream_url",
            "protocol",
        ]
        with path.open(
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=fieldnames,
            )
            writer.writeheader()
            writer.writerows(rows)

    def test_unique_legacy_row_is_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = root / "audit.json"
            current = root / "audit.csv"

            audit.write_text(
                json.dumps({
                    "channels": [{
                        "channel": "Duna",
                        "vlc": "works",
                        "samsung": "works",
                    }]
                }),
                encoding="utf-8",
            )

            self.write_current(
                current,
                [{
                    "channel": "Duna",
                    "tvg_id": "Duna.hu@SD",
                    "stream_url": "https://example.test/duna.m3u8",
                    "protocol": "HLS",
                }],
            )

            summary = migrate_audit.migrate(
                audit,
                current,
                write=True,
            )

            payload = json.loads(
                audit.read_text(encoding="utf-8")
            )
            item = payload["channels"][0]

            self.assertEqual(
                item["stream_url"],
                "https://example.test/duna.m3u8",
            )
            self.assertEqual(
                item["tvg_id"],
                "Duna.hu@SD",
            )
            self.assertEqual(
                item["protocol"],
                "HLS",
            )
            self.assertEqual(
                summary["migrated"],
                1,
            )

    def test_ambiguous_legacy_row_is_not_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = root / "audit.json"
            current = root / "audit.csv"

            original = {
                "channels": [{
                    "channel": "Example TV",
                    "vlc": "works",
                }]
            }
            audit.write_text(
                json.dumps(original),
                encoding="utf-8",
            )

            self.write_current(
                current,
                [
                    {
                        "channel": "Example TV",
                        "tvg_id": "ExampleTV.hu@SD",
                        "stream_url": "https://example.test/one.m3u8",
                        "protocol": "HLS",
                    },
                    {
                        "channel": "Example TV",
                        "tvg_id": "ExampleTV.hu@HD",
                        "stream_url": "https://example.test/two.m3u8",
                        "protocol": "HLS",
                    },
                ],
            )

            summary = migrate_audit.migrate(
                audit,
                current,
                write=True,
            )

            payload = json.loads(
                audit.read_text(encoding="utf-8")
            )

            self.assertNotIn(
                "stream_url",
                payload["channels"][0],
            )
            self.assertEqual(
                summary["ambiguous"],
                1,
            )

    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = root / "audit.json"
            current = root / "audit.csv"

            original_text = json.dumps({
                "channels": [{
                    "channel": "Duna"
                }]
            })
            audit.write_text(
                original_text,
                encoding="utf-8",
            )

            self.write_current(
                current,
                [{
                    "channel": "Duna",
                    "tvg_id": "Duna.hu@SD",
                    "stream_url": "https://example.test/duna.m3u8",
                    "protocol": "HLS",
                }],
            )

            summary = migrate_audit.migrate(
                audit,
                current,
                write=False,
            )

            self.assertEqual(
                audit.read_text(encoding="utf-8"),
                original_text,
            )
            self.assertEqual(
                summary["migrated"],
                1,
            )


if __name__ == "__main__":
    unittest.main()
