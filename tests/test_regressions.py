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


    def test_exact_url_audit_does_not_cross_explicit_language_scope(self):
        url = "https://dash.antik.sk/live/test_upnetwork/playlist.m3u8"

        entry = {
            "lines": [
                '#EXTINF:-1 tvg-id="UpNetwork.cz@SD" tvg-name="Up Network",Up Network',
                url,
            ],
            "url": url,
            "display_name": "Up Network",
            "tvg_id": "UpNetwork.cz@SD",
            "tvg_name": "Up Network",
            "logo": "",
            "group_title": "",
            "channel_name": "Up Network",
            "source": "IPTV-org Czechia",
            "source_kind": "base",
            "language_code": "CZ",
            "source_flags": [],
            "classification": "Base channel",
        }
        entry["channel_key"] = build.channel_key(entry)

        audit = [{
            "channel": "Kanal1",
            "stream_url": url,
            "vlc": "works",
            "samsung": "works",
            "decision": "auto",
            "playlist_language_code": "SK",
            "expected_language_codes": ["SK"],
            "observed_language_codes": ["SK"],
            "language": "Slovak",
            "language_code": "SK",
        }]

        warnings, ambiguity_warnings = build.validate_audit_items(
            audit,
            [entry],
            strict=True,
        )

        self.assertEqual(ambiguity_warnings, [])
        self.assertTrue(
            any(
                "saved audit belongs to SK playlist scope" in warning
                for warning in warnings
            )
        )

        rows = build.prepare_audit_rows(audit, [entry])
        current = [row for row in rows if row["in_playlist"]]
        historical = [row for row in rows if not row["in_playlist"]]

        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["channel"], "Up Network")
        self.assertEqual(current[0]["expected_language_codes"], ["CZ"])
        self.assertEqual(current[0]["decision"], "Needs review")
        self.assertEqual(current[0]["vlc"], "not_tested")
        self.assertEqual(current[0]["samsung"], "not_tested")

        self.assertEqual(len(historical), 1)
        self.assertEqual(historical[0]["channel"], "Kanal1")
        self.assertEqual(historical[0]["expected_language_codes"], ["SK"])
        self.assertEqual(historical[0]["decision"], "Verified")
        self.assertIn(
            "Historical exact-URL audit only",
            historical[0]["notes"],
        )

        test_candidates = build.make_test_playlist_candidates(
            [entry],
            rows,
        )
        self.assertEqual(len(test_candidates), 1)
        self.assertEqual(
            test_candidates[0]["_decision"],
            "Needs review",
        )

        stable, _excluded = build.select_stable_playlist_candidates(
            [entry],
            rows,
            {
                "stable_playlist": {
                    "allowed_decisions": [
                        "Verified",
                        "TV verified",
                    ]
                }
            },
        )
        self.assertEqual(stable, [])


    def test_supported_cross_language_moves_to_observed_language_bucket_once(self):
        url = "https://example.test/cross-language.m3u8"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            (root / "audit.json").write_text(
                json.dumps({
                    "channels": [{
                        "channel": "Cross Language TV",
                        "stream_url": url,
                        "playlist_language_code": "SK",
                        "expected_language_codes": ["SK"],
                        "observed_language_codes": ["CZ"],
                        "language": "Czech",
                        "language_code": "CZ",
                        "vlc": "wrong_language",
                        "samsung": "wrong_language",
                        "decision": "auto",
                        "exclude_from_playlist": False,
                    }]
                }),
                encoding="utf-8",
            )

            for filename, tvg_id in (
                ("sk-source.m3u", "CrossLanguage.cz@SD"),
                ("cz-source.m3u", "CrossLanguage.cz@SD"),
            ):
                (root / filename).write_text(
                    "#EXTM3U\n"
                    f'#EXTINF:-1 tvg-id="{tvg_id}" '
                    'tvg-name="Cross Language TV",Cross Language TV\n'
                    f"{url}\n",
                    encoding="utf-8",
                )

            (root / "config.json").write_text(
                json.dumps({
                    "site_title": "Test",
                    "default_language_code": "SK",
                    "country_names": {
                        "SK": "Slovakia",
                        "CZ": "Czechia",
                    },
                    "output": "public/tv.m3u",
                    "test_output": "public/test.m3u",
                    "country_outputs": {
                        "SK": "public/sk.m3u",
                        "CZ": "public/cz.m3u",
                    },
                    "audit_path": "audit.json",
                    "sources": [
                        {
                            "name": "Slovakia",
                            "kind": "base",
                            "language_code": "SK",
                            "path": "sk-source.m3u",
                        },
                        {
                            "name": "Czechia",
                            "kind": "base",
                            "language_code": "CZ",
                            "path": "cz-source.m3u",
                        },
                    ],
                    "extras": [],
                }),
                encoding="utf-8",
            )

            old_root = build.ROOT
            try:
                build.ROOT = root
                build.main(strict=True)
            finally:
                build.ROOT = old_root

            stable = (root / "public" / "tv.m3u").read_text(
                encoding="utf-8"
            )
            sk_playlist = (root / "public" / "sk.m3u").read_text(
                encoding="utf-8"
            )
            cz_playlist = (root / "public" / "cz.m3u").read_text(
                encoding="utf-8"
            )

            self.assertEqual(stable.count(url), 1)
            self.assertNotIn(url, sk_playlist)
            self.assertIn("[CZ OK] Cross Language TV", cz_playlist)
            self.assertEqual(cz_playlist.count(url), 1)

            with (root / "public" / "audit.csv").open(
                encoding="utf-8-sig",
                newline="",
            ) as f:
                audit_rows = list(csv.DictReader(f))

            current = [
                row
                for row in audit_rows
                if row["in_playlist"] == "True"
            ]
            self.assertEqual(len(current), 1)
            self.assertEqual(current[0]["playlist_language_code"], "SK")
            self.assertEqual(current[0]["output_language_code"], "CZ")
            self.assertEqual(current[0]["observed_language_codes"], "CZ")
            self.assertEqual(
                current[0]["language_acceptance"],
                "supported_cross_language",
            )
            self.assertEqual(current[0]["decision"], "Verified")

    def test_rerouted_channel_still_has_only_one_best_stable_feed(self):
        sk_url = "https://example.test/from-sk.m3u8"
        cz_url = "https://example.test/from-cz.m3u8"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            (root / "audit.json").write_text(
                json.dumps({
                    "channels": [
                        {
                            "channel": "Shared Czech TV",
                            "stream_url": sk_url,
                            "playlist_language_code": "SK",
                            "expected_language_codes": ["SK"],
                            "observed_language_codes": ["CZ"],
                            "language": "Czech",
                            "language_code": "CZ",
                            "vlc": "wrong_language",
                            "samsung": "wrong_language",
                            "decision": "auto",
                            "exclude_from_playlist": False,
                        },
                        {
                            "channel": "Shared Czech TV",
                            "stream_url": cz_url,
                            "playlist_language_code": "CZ",
                            "expected_language_codes": ["CZ"],
                            "observed_language_codes": ["CZ"],
                            "language": "Czech",
                            "language_code": "CZ",
                            "vlc": "works",
                            "samsung": "works",
                            "decision": "auto",
                            "exclude_from_playlist": False,
                        },
                    ]
                }),
                encoding="utf-8",
            )

            (root / "sk-source.m3u").write_text(
                "#EXTM3U\n"
                '#EXTINF:-1 tvg-id="SharedCzechTV.cz@SD" '
                'tvg-name="Shared Czech TV",Shared Czech TV\n'
                f"{sk_url}\n",
                encoding="utf-8",
            )
            (root / "cz-source.m3u").write_text(
                "#EXTM3U\n"
                '#EXTINF:-1 tvg-id="SharedCzechTV.cz@HD" '
                'tvg-name="Shared Czech TV",Shared Czech TV\n'
                f"{cz_url}\n",
                encoding="utf-8",
            )

            (root / "config.json").write_text(
                json.dumps({
                    "site_title": "Test",
                    "default_language_code": "SK",
                    "country_names": {
                        "SK": "Slovakia",
                        "CZ": "Czechia",
                    },
                    "output": "public/tv.m3u",
                    "test_output": "public/test.m3u",
                    "country_outputs": {
                        "SK": "public/sk.m3u",
                        "CZ": "public/cz.m3u",
                    },
                    "audit_path": "audit.json",
                    "sources": [
                        {
                            "name": "Slovakia",
                            "kind": "base",
                            "language_code": "SK",
                            "path": "sk-source.m3u",
                        },
                        {
                            "name": "Czechia",
                            "kind": "base",
                            "language_code": "CZ",
                            "path": "cz-source.m3u",
                        },
                    ],
                    "extras": [],
                }),
                encoding="utf-8",
            )

            old_root = build.ROOT
            try:
                build.ROOT = root
                build.main(strict=True)
            finally:
                build.ROOT = old_root

            stable = (root / "public" / "tv.m3u").read_text(
                encoding="utf-8"
            )
            sk_playlist = (root / "public" / "sk.m3u").read_text(
                encoding="utf-8"
            )
            cz_playlist = (root / "public" / "cz.m3u").read_text(
                encoding="utf-8"
            )

            self.assertNotIn(sk_url, sk_playlist)
            self.assertNotIn(cz_url, sk_playlist)
            self.assertEqual(
                int(sk_url in stable) + int(cz_url in stable),
                1,
            )
            self.assertEqual(
                int(sk_url in cz_playlist) + int(cz_url in cz_playlist),
                1,
            )
            self.assertIn("[CZ OK] Shared Czech TV", cz_playlist)

    def test_unsupported_cross_language_remains_rejected(self):
        decision, _reason = build.calculate_audit_decision(
            {
                "playlist_language_code": "HU",
                "expected_language_codes": ["HU"],
                "observed_language_codes": ["RU"],
                "vlc": "wrong_language",
                "samsung": "wrong_language",
                "decision": "auto",
                "exclude_from_playlist": False,
            },
            supported_language_codes=[
                "HU",
                "SK",
                "CZ",
            ],
        )

        self.assertEqual(
            decision,
            "Rejected",
        )


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
