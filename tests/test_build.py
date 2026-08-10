import csv
import json
import tempfile
import unittest
from pathlib import Path

import build


def make_entry(
    url: str,
    name: str = "Demo TV",
    tvg_id: str = "DemoTV.hu@SD",
    source: str = "Source A",
    language_code: str = "HU",
) -> dict:
    entry = {
        "lines": [
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}",{name}',
            url,
        ],
        "url": url,
        "display_name": name,
        "tvg_id": tvg_id,
        "tvg_name": name,
        "logo": "",
        "group_title": "",
        "channel_name": name,
        "source": source,
        "source_kind": "base",
        "language_code": language_code,
        "source_flags": [],
        "classification": "Base channel",
    }
    entry["channel_key"] = build.channel_key(entry)
    return entry


class AuditTests(unittest.TestCase):

    def test_source_kind_normalization(self):
        self.assertEqual(
            build.normalize_source_kind(
                "base"
            ),
            "base",
        )

        self.assertEqual(
            build.normalize_source_kind(
                "Base"
            ),
            "base",
        )

        self.assertEqual(
            build.normalize_source_kind(
                "alternative"
            ),
            "alternatives",
        )

        self.assertEqual(
            build.normalize_source_kind(
                "alternatives"
            ),
            "alternatives",
        )

        self.assertEqual(
            build.normalize_source_kind(
                "extra"
            ),
            "extras",
        )

        self.assertEqual(
            build.normalize_source_kind(
                "extras"
            ),
            "extras",
        )

        self.assertEqual(
            build.normalize_source_kind(
                "source"
            ),
            "source",
        )

    def test_invalid_source_kind_is_rejected(self):
        with self.assertRaisesRegex(
            RuntimeError,
            "Unsupported source kind",
        ):
            build.normalize_source_kind(
                "banana"
            )
			
    def test_country_name_for_language(self):
        cfg = {
            "country_names": {
                "HU": "Hungary",
                "SK": "Slovakia",
                "CZ": "Czechia",
            }
        }

        self.assertEqual(
            build.country_name_for_language(
                cfg,
                "HU",
            ),
            "Hungary",
        )

        self.assertEqual(
            build.country_name_for_language(
                cfg,
                "SK",
            ),
            "Slovakia",
        )

        self.assertEqual(
            build.country_name_for_language(
                cfg,
                "CZ",
            ),
            "Czechia",
        )
		
    def test_content_group_preserves_source_category(self):
        self.assertEqual(
            build.normalize_content_group(
                "Music",
                country_name="Hungary",
                language_code="HU",
            ),
            "Music",
        )

        self.assertEqual(
            build.normalize_content_group(
                "Sports",
                country_name="Hungary",
                language_code="HU",
            ),
            "Sports",
        )

        self.assertEqual(
            build.normalize_content_group(
                "Culture;General",
                country_name="Hungary",
                language_code="HU",
            ),
            "Culture;General",
        )
		
    def test_content_group_undefined_becomes_general(self):
        for value in (
            "",
            "Undefined",
            "Unknown",
            "Uncategorized",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    build.normalize_content_group(
                        value,
                        country_name="Hungary",
                        language_code="HU",
                    ),
                    "General",
                )
				
    def test_old_status_group_becomes_general(self):
        for value in (
            "HU | Verified",
            "HU | TV verified",
            "HU | PC only",
            "HU | Needs review",
            "HU | Rejected",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    build.normalize_content_group(
                        value,
                        country_name="Hungary",
                        language_code="HU",
                    ),
                    "General",
                )

    def test_new_country_group_is_idempotent(self):
        self.assertEqual(
            build.normalize_content_group(
                "Hungary | News",
                country_name="Hungary",
                language_code="HU",
            ),
            "News",
        )
		
    def test_canonical_stream_url_normalizes_safe_equivalents(self):
        self.assertEqual(
            build.canonical_stream_url(
                "HTTPS://CITYTV.HU:443/playlist.m3u8#player"
            ),
            "https://citytv.hu/playlist.m3u8",
        )

        self.assertEqual(
            build.canonical_stream_url(
                "http://EXAMPLE.TEST:80"
            ),
            "http://example.test/",
        )

        self.assertEqual(
            build.canonical_stream_url(
                "https://EXAMPLE.TEST:8443/live.m3u8?Token=AbC#player"
            ),
            "https://example.test:8443/live.m3u8?Token=AbC",
        )

    def test_canonical_stream_url_preserves_query_difference(self):
        first = build.canonical_stream_url(
            "https://example.test/live.m3u8?token=AAA"
        )
        second = build.canonical_stream_url(
            "https://example.test/live.m3u8?token=BBB"
        )

        self.assertNotEqual(first, second)

    def test_canonical_equivalent_audit_url_matches_stream(self):
        stream_url = "https://citytv.hu/playlist.m3u8"
        audit_url = "HTTPS://CITYTV.HU:443/playlist.m3u8#player"

        entries = [
            make_entry(
                stream_url,
                name="City TV",
                tvg_id="CityTV.hu",
            )
        ]

        audit = [{
            "channel": "City TV",
            "tvg_id": "CityTV.hu",
            "stream_url": audit_url,
            "vlc": "works",
            "samsung": "works",
            "decision": "auto",
        }]

        build.validate_audit_items(audit, entries)

        rows = build.prepare_audit_rows(audit, entries)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decision"], "Verified")

        selected, _ = build.select_playlist_candidates(entries, rows)

        self.assertEqual(len(selected), 1)

        # The real playlist URL remains untouched.
        self.assertEqual(selected[0]["url"], stream_url)
		
    def test_tvg_sd_hd_variants_collapse(self):
        sd = make_entry("https://example.test/sd.m3u8", tvg_id="DemoTV.hu@SD")
        hd = make_entry("https://example.test/hd.m3u8", tvg_id="DemoTV.hu@HD")
        self.assertEqual(build.channel_key(sd), build.channel_key(hd))

    def test_two_feeds_get_feed_numbers(self):
        entries = [
            make_entry("https://example.test/a.m3u8"),
            make_entry("https://example.test/b.m3u8", source="Source B"),
        ]
        rows = build.prepare_audit_rows([], entries)
        self.assertEqual([row["feed_count"] for row in rows], [2, 2])
        self.assertEqual([row["feed_label"] for row in rows], ["Feed 1/2", "Feed 2/2"])

    def test_legacy_single_feed_still_applies(self):
        entries = [
            make_entry(
                "https://example.test/a.m3u8"
            )
        ]

        audit = [{
            "channel": "Demo TV",
            "vlc": "works",
            "samsung": "works",
            "decision": "auto",
        }]

        warnings, ambiguity_warnings = (
            build.validate_audit_items(
                audit,
                entries,
            )
        )

        self.assertEqual(len(warnings), 1)
        self.assertEqual(
            ambiguity_warnings,
            [],
        )

        rows = build.prepare_audit_rows(
            audit,
            entries,
        )

        self.assertEqual(
            rows[0]["decision"],
            "Verified",
        )

    def test_legacy_multi_feed_warns_and_is_not_applied(self):
        url1 = "https://example.test/a.m3u8"
        url2 = "https://example.test/b.m3u8"

        entries = [
            make_entry(url1),
            make_entry(
                url2,
                source="Source B",
            ),
        ]

        audit = [{
            "channel": "Demo TV",
            "vlc": "works",
            "samsung": "works",
            "decision": "auto",
            "notes": "Previously verified.",
        }]

        warnings, ambiguity_warnings = (
            build.validate_audit_items(
                audit,
                entries,
            )
        )

        self.assertTrue(warnings)
        self.assertEqual(
            len(ambiguity_warnings),
            1,
        )

        self.assertIn(
            "became ambiguous after 2 feeds",
            ambiguity_warnings[0],
        )

        rows = build.prepare_audit_rows(
            audit,
            entries,
        )

        current_rows = [
            row
            for row in rows
            if row["in_playlist"]
        ]

        historical_rows = [
            row
            for row in rows
            if not row["in_playlist"]
        ]

        # Both current feeds must be treated as completely untested.
        self.assertEqual(
            len(current_rows),
            2,
        )

        self.assertEqual(
            [row["decision"] for row in current_rows],
            [
                "Needs review",
                "Needs review",
            ],
        )

        self.assertEqual(
            [row["vlc"] for row in current_rows],
            [
                "not_tested",
                "not_tested",
            ],
        )

        self.assertEqual(
            [row["samsung"] for row in current_rows],
            [
                "not_tested",
                "not_tested",
            ],
        )

        # The old Verified result must still exist as history.
        self.assertEqual(
            len(historical_rows),
            1,
        )

        legacy = historical_rows[0]

        self.assertEqual(
            legacy["feed_label"],
            "Legacy audit",
        )

        self.assertEqual(
            legacy["decision"],
            "Verified",
        )

        self.assertFalse(
            legacy["in_playlist"]
        )

        self.assertIn(
            "Historical channel-level audit only",
            legacy["notes"],
        )

        # Since neither current feed is Verified yet, both remain visible
        # until we test them individually.
        selected, _ = (
            build.select_playlist_candidates(
                entries,
                rows,
            )
        )

        self.assertEqual(
            {entry["url"] for entry in selected},
            {url1, url2},
        )


    def test_legacy_multi_feed_is_rejected_in_strict_mode(self):
        entries = [
            make_entry(
                "https://example.test/a.m3u8"
            ),
            make_entry(
                "https://example.test/b.m3u8",
                source="Source B",
            ),
        ]

        audit = [{
            "channel": "Demo TV",
            "vlc": "works",
            "samsung": "works",
            "decision": "auto",
        }]

        with self.assertRaisesRegex(
            RuntimeError,
            "became ambiguous after 2 feeds",
        ):
            build.validate_audit_items(
                audit,
                entries,
                strict=True,
            )

    def test_dashboard_shows_ambiguous_legacy_warning(self):
        entries = [
            make_entry(
                "https://example.test/a.m3u8"
            ),
            make_entry(
                "https://example.test/b.m3u8",
                source="Source B",
            ),
        ]

        audit = [{
            "channel": "Demo TV",
            "vlc": "works",
            "samsung": "works",
            "decision": "auto",
        }]

        _warnings, ambiguity_warnings = (
            build.validate_audit_items(
                audit,
                entries,
            )
        )

        rows = build.prepare_audit_rows(
            audit,
            entries,
        )

        dashboard = build.make_dashboard(
            cfg={
                "site_title": "Test",
            },
            generated="2026-08-10 12:00:00 UTC",
            final_entries=entries,
            unique_channels=[],
            source_stats=[],
            language_stats=[],
            duplicate_rows=[],
            changes={},
            audit_rows=rows,
            audit_ambiguity_warnings=(
                ambiguity_warnings
            ),
        )

        self.assertIn(
            "Audit warnings",
            dashboard,
        )

        self.assertIn(
            "became ambiguous after 2 feeds",
            dashboard,
        )
		
    def test_exact_url_overrides_legacy_single_feed(self):
        url = "https://example.test/a.m3u8"
        entries = [make_entry(url)]
        audit = [
            {
                "channel": "Demo TV",
                "vlc": "loads",
                "samsung": "format_error",
                "decision": "auto",
            },
            {
                "channel": "Demo TV",
                "stream_url": url,
                "vlc": "works",
                "samsung": "works",
                "decision": "auto",
            },
        ]
        build.validate_audit_items(audit, entries)
        rows = build.prepare_audit_rows(audit, entries)
        self.assertEqual(rows[0]["decision"], "Verified")
        self.assertEqual(rows[0]["vlc"], "works")

    def test_failed_first_feed_working_second_feed_selects_second(self):
        url1 = "https://example.test/a.m3u8"
        url2 = "https://example.test/b.m3u8"
        entries = [
            make_entry(url1),
            make_entry(url2, source="Source B"),
        ]
        audit = [
            {
                "channel": "Demo TV",
                "stream_url": url1,
                "vlc": "loads",
                "samsung": "format_error",
                "decision": "auto",
                "exclude_from_playlist": True,
            },
            {
                "channel": "Demo TV",
                "stream_url": url2,
                "vlc": "works",
                "samsung": "works",
                "decision": "auto",
            },
        ]
        build.validate_audit_items(audit, entries)
        rows = build.prepare_audit_rows(audit, entries)
        selected, excluded = build.select_playlist_candidates(entries, rows)

        self.assertEqual([e["url"] for e in selected], [url2])
        self.assertIn(url1, {e["stream_url"] for e in excluded})

    def test_both_verified_prefers_clean_vlc_feed(self):
        warning_url = "https://example.test/warning.m3u8"
        clean_url = "https://example.test/clean.m3u8"
        entries = [
            make_entry(warning_url),
            make_entry(clean_url, source="Source B"),
        ]
        audit = [
            {
                "channel": "Demo TV",
                "stream_url": warning_url,
                "vlc": "works_with_warning",
                "samsung": "works",
                "decision": "auto",
            },
            {
                "channel": "Demo TV",
                "stream_url": clean_url,
                "vlc": "works",
                "samsung": "works",
                "decision": "auto",
            },
        ]
        build.validate_audit_items(audit, entries)
        rows = build.prepare_audit_rows(audit, entries)
        selected, _ = build.select_playlist_candidates(entries, rows)
        self.assertEqual([e["url"] for e in selected], [clean_url])

    def test_wrong_language_is_rejected(self):
        decision, _ = build.calculate_audit_decision({
            "vlc": "wrong_language",
            "samsung": "wrong_language",
            "language": "Czech",
            "decision": "auto",
        })
        self.assertEqual(decision, "Rejected")

    def test_hu_playlist_rejects_observed_slovak(self):
        decision, reason = (
            build.calculate_audit_decision({
                "vlc": "works",
                "samsung": "works",
                "expected_language_codes": ["HU"],
                "observed_language_codes": ["SK"],
                "decision": "auto",
            })
        )

        self.assertEqual(
            decision,
            "Rejected",
        )

        self.assertIn(
            "SK",
            reason,
        )

        self.assertIn(
            "HU",
            reason,
        )

    def test_cz_playlist_accepts_observed_czech(self):
        decision, _ = (
            build.calculate_audit_decision({
                "vlc": "works",
                "samsung": "works",
                "expected_language_codes": ["CZ"],
                "observed_language_codes": ["CZ"],
                "decision": "auto",
            })
        )

        self.assertEqual(
            decision,
            "Verified",
        )

    def test_expected_language_inside_multilingual_feed_is_accepted(self):
        item = {
            "vlc": "works",
            "samsung": "works",
            "expected_language_codes": ["HU"],
            "observed_language_codes": [
                "HU",
                "SR",
            ],
            "decision": "auto",
        }

        (
            expected,
            observed,
            language_match,
        ) = build.resolve_language_info(item)

        self.assertEqual(
            expected,
            ["HU"],
        )

        self.assertEqual(
            observed,
            ["HU", "SR"],
        )

        self.assertEqual(
            language_match,
            "multilingual",
        )

        decision, _ = (
            build.calculate_audit_decision(item)
        )

        self.assertEqual(
            decision,
            "Verified",
        )

    def test_multilingual_feed_without_expected_language_is_rejected(self):
        item = {
            "vlc": "works",
            "samsung": "works",
            "expected_language_codes": ["HU"],
            "observed_language_codes": [
                "SK",
                "CZ",
            ],
            "decision": "auto",
        }

        (
            _expected,
            _observed,
            language_match,
        ) = build.resolve_language_info(item)

        self.assertEqual(
            language_match,
            "no",
        )

        decision, _ = (
            build.calculate_audit_decision(item)
        )

        self.assertEqual(
            decision,
            "Rejected",
        )

    def test_legacy_slovak_language_is_rejected_for_hu_source(self):
        url = "https://example.test/slovak.m3u8"

        entries = [
            make_entry(
                url,
                language_code="HU",
            )
        ]

        audit = [{
            "channel": "Demo TV",
            "stream_url": url,
            "vlc": "works",
            "samsung": "works",

            # Old audit format:
            "language": "Slovak",
            "language_code": "SK",

            "decision": "auto",
        }]

        build.validate_audit_items(
            audit,
            entries,
        )

        rows = build.prepare_audit_rows(
            audit,
            entries,
        )

        self.assertEqual(
            rows[0]["expected_language_codes"],
            ["HU"],
        )

        self.assertEqual(
            rows[0]["observed_language_codes"],
            ["SK"],
        )

        self.assertEqual(
            rows[0]["language_match"],
            "no",
        )

        self.assertEqual(
            rows[0]["decision"],
            "Rejected",
        )

    def test_legacy_czech_language_is_valid_for_cz_source(self):
        url = "https://example.test/czech.m3u8"

        entries = [
            make_entry(
                url,
                language_code="CZ",
            )
        ]

        audit = [{
            "channel": "Demo TV",
            "stream_url": url,
            "vlc": "works",
            "samsung": "works",
            "language": "Czech",
            "language_code": "CZ",
            "decision": "auto",
        }]

        build.validate_audit_items(
            audit,
            entries,
        )

        rows = build.prepare_audit_rows(
            audit,
            entries,
        )

        self.assertEqual(
            rows[0]["expected_language_codes"],
            ["CZ"],
        )

        self.assertEqual(
            rows[0]["observed_language_codes"],
            ["CZ"],
        )

        self.assertEqual(
            rows[0]["language_match"],
            "yes",
        )

        self.assertEqual(
            rows[0]["decision"],
            "Verified",
        )

    def test_explicit_language_match_no_rejects_stream(self):
        decision, _ = (
            build.calculate_audit_decision({
                "vlc": "works",
                "samsung": "works",
                "expected_language_codes": ["HU"],
                "observed_language_codes": ["SK"],
                "language_match": "no",
                "decision": "auto",
            })
        )

        self.assertEqual(
            decision,
            "Rejected",
        )
		
    def test_not_24_7_flag_does_not_auto_reject_working_stream(self):
        flags = build.extract_source_flags("Demo TV (720p) [Not 24/7]")
        self.assertEqual(flags, ["Not 24/7"])

        decision, _ = build.calculate_audit_decision({
            "vlc": "works",
            "samsung": "works",
            "language": "Hungarian",
            "source_flags": flags,
            "decision": "auto",
        })
        self.assertEqual(decision, "Verified")

    def test_source_order_change_does_not_move_exact_url_audit(self):
        bad_url = "https://example.test/bad.m3u8"
        good_url = "https://example.test/good.m3u8"
        audit = [
            {
                "channel": "Demo TV",
                "stream_url": bad_url,
                "vlc": "loads",
                "samsung": "format_error",
                "decision": "auto",
                "exclude_from_playlist": True,
            },
            {
                "channel": "Demo TV",
                "stream_url": good_url,
                "vlc": "works",
                "samsung": "works",
                "decision": "auto",
            },
        ]

        winners = []
        for entries in (
            [make_entry(bad_url), make_entry(good_url, source="Source B")],
            [make_entry(good_url, source="Source B"), make_entry(bad_url)],
        ):
            build.validate_audit_items(audit, entries)
            rows = build.prepare_audit_rows(audit, entries)
            selected, _ = build.select_playlist_candidates(entries, rows)
            winners.append([e["url"] for e in selected])

        self.assertEqual(winners, [[good_url], [good_url]])

    def test_disappearing_url_stays_in_history_and_reattaches(self):
        url = "https://example.test/a.m3u8"
        audit = [{
            "channel": "Demo TV",
            "tvg_id": "DemoTV.hu@SD",
            "stream_url": url,
            "vlc": "works",
            "samsung": "works",
            "decision": "auto",
        }]

        gone = build.prepare_audit_rows(audit, [])
        self.assertEqual(len(gone), 1)
        self.assertFalse(gone[0]["in_playlist"])
        self.assertEqual(gone[0]["feed_label"], "Candidate")

        returned = build.prepare_audit_rows(audit, [make_entry(url)])
        self.assertEqual(len(returned), 1)
        self.assertTrue(returned[0]["in_playlist"])
        self.assertEqual(returned[0]["decision"], "Verified")

    def test_validator_rejects_bad_audit_data(self):
        cases = [
            (
                [{"channel": "Bad", "stream_url": "not a url"}],
                "malformed stream_url",
            ),
            (
                [{"channel": "", "stream_url": "https://example.test/a.m3u8"}],
                "missing channel name",
            ),
            (
                [{
                    "channel": "Bad",
                    "stream_url": "https://example.test/a.m3u8",
                    "vlc": "wroks",
                }],
                "invalid vlc status",
            ),
            (
                [{
                    "channel": "Bad",
                    "stream_url": "https://example.test/a.m3u8",
                    "decision": "keep_it",
                }],
                "invalid decision",
            ),
            (
                [{
                    "channel": "Bad",
                    "stream_url": "https://example.test/a.m3u8",
                    "vlc": "works",
                    "samsung": "format_error",
                    "decision": "verified",
                }],
                "decision Verified contradicts",
            ),
            (
                [{
                    "channel": "Bad",
                    "stream_url": "https://example.test/a.m3u8",
                    "vlc": "works",
                    "samsung": "works",
                    "decision": "verified",
                    "exclude_from_playlist": True,
                }],
                "exclude_from_playlist=true conflicts",
            ),
            (
                [{
                    "channel": "Bad",
                    "stream_url": "https://example.test/a.m3u8",
                    "expected_language_codes": "HU",
                }],
                "expected_language_codes must be a JSON list",
            ),
            (
                [{
                    "channel": "Bad",
                    "stream_url": "https://example.test/a.m3u8",
                    "observed_language_codes": ["Hungarian"],
                }],
                "invalid language code",
            ),
            (
                [{
                    "channel": "Bad",
                    "stream_url": "https://example.test/a.m3u8",
                    "language_match": "probably",
                }],
                "invalid language_match",
            ),
            (
                [{
                    "channel": "Bad",
                    "stream_url": "https://example.test/a.m3u8",
                    "expected_language_codes": ["HU"],
                    "observed_language_codes": ["HU"],
                    "language_match": "no",
                }],
                "language_match",
            ),
        ]

        for audit, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(RuntimeError, message):
                    build.validate_audit_items(audit, [])

    def test_validator_rejects_duplicate_stream_url(self):
        url = "https://example.test/a.m3u8"
        audit = [
            {"channel": "One", "stream_url": url},
            {"channel": "Two", "stream_url": url},
        ]
        with self.assertRaisesRegex(RuntimeError, "duplicate stream_url"):
            build.validate_audit_items(audit, [])

    def test_validator_rejects_canonical_duplicate_stream_url(self):
        audit = [
            {
                "channel": "City TV",
                "stream_url": "https://citytv.hu/playlist.m3u8",
            },
            {
                "channel": "City TV duplicate",
                "stream_url": "HTTPS://CITYTV.HU:443/playlist.m3u8#player",
            },
        ]

        with self.assertRaisesRegex(RuntimeError, "duplicate stream_url"):
            build.validate_audit_items(audit, [])
			
    def test_validator_rejects_duplicate_legacy_key(self):
        audit = [
            {"channel": "Demo TV", "vlc": "works"},
            {"channel": "Demo TV", "vlc": "loads"},
        ]
        with self.assertRaisesRegex(RuntimeError, "duplicate channel-level audit key"):
            build.validate_audit_items(audit, [])

    def test_duplicate_url_is_written_only_once(self):
        url = "https://example.test/shared.m3u8"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "audit.json").write_text('{"channels": []}\n', encoding="utf-8")

            (root / "one.m3u").write_text(
                '#EXTM3U\n'
                '#EXTINF:-1 tvg-id="DemoTV.hu@SD",Demo TV\n'
                f'{url}\n',
                encoding="utf-8",
            )
            (root / "two.m3u").write_text(
                '#EXTM3U\n'
                '#EXTINF:-1 tvg-id="DemoTV.hu@SD",Demo TV duplicate\n'
                f'{url}\n',
                encoding="utf-8",
            )
            (root / "config.json").write_text(
                json.dumps({
                    "site_title": "Test",
                    "default_language_code": "HU",
                    "output": "public/tv.m3u",
                    "audit_path": "audit.json",
                    "sources": [
                        {"name": "One", "path": "one.m3u"},
                        {"name": "Two", "path": "two.m3u"},
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

            playlist = (root / "public" / "tv.m3u").read_text(encoding="utf-8")
            self.assertEqual(playlist.count(url), 1)

            with (root / "public" / "duplicates.csv").open(
                encoding="utf-8-sig",
                newline="",
            ) as f:
                duplicates = list(csv.DictReader(f))

            self.assertEqual(len(duplicates), 1)
            self.assertEqual(duplicates[0]["stream_url"], url)

    def test_build_preserves_category_in_final_group_title(self):
        url = "https://example.test/news.m3u8"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            (
                root / "audit.json"
            ).write_text(
                '{"channels": []}\n',
                encoding="utf-8",
            )

            (
                root / "source.m3u"
            ).write_text(
                '#EXTM3U\n'
                '#EXTINF:-1 '
                'tvg-id="DemoNews.hu@SD" '
                'tvg-name="Demo News" '
                'group-title="News",'
                'Demo News\n'
                f'{url}\n',
                encoding="utf-8",
            )

            (
                root / "config.json"
            ).write_text(
                json.dumps({
                    "site_title": "Test",
                    "default_language_code": "HU",

                    "country_names": {
                        "HU": "Hungary",
                        "SK": "Slovakia",
                        "CZ": "Czechia",
                    },

                    "output": "public/tv.m3u",
                    "audit_path": "audit.json",

                    "sources": [
                        {
                            "name": "Hungary",
                            "kind": "base",
                            "language_code": "HU",
                            "path": "source.m3u",
                        }
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

            playlist = (
                root
                / "public"
                / "tv.m3u"
            ).read_text(
                encoding="utf-8"
            )

            self.assertIn(
                'group-title="Hungary | News"',
                playlist,
            )

            self.assertNotIn(
                'group-title="HU | Needs review"',
                playlist,
            )

            # Verification status remains available in the channel name.
            self.assertIn(
                "[HU ?] Demo News",
                playlist,
            )

            with (
                root
                / "public"
                / "channels.csv"
            ).open(
                encoding="utf-8-sig",
                newline="",
            ) as f:
                rows = list(
                    csv.DictReader(f)
                )

            self.assertEqual(
                len(rows),
                1,
            )

            row = rows[0]

            self.assertEqual(
                row["country_name"],
                "Hungary",
            )

            self.assertEqual(
                row["source_group_title"],
                "News",
            )

            self.assertEqual(
                row["content_group"],
                "News",
            )

            self.assertEqual(
                row["group_title"],
                "Hungary | News",
            )

            self.assertEqual(
                row["test_status"],
                "Needs review",
            )

    def test_build_uses_general_when_group_is_missing(self):
        url = "https://example.test/general.m3u8"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            (
                root / "audit.json"
            ).write_text(
                '{"channels": []}\n',
                encoding="utf-8",
            )

            (
                root / "source.m3u"
            ).write_text(
                '#EXTM3U\n'
                '#EXTINF:-1 '
                'tvg-id="DemoTV.hu@SD",'
                'Demo TV\n'
                f'{url}\n',
                encoding="utf-8",
            )

            (
                root / "config.json"
            ).write_text(
                json.dumps({
                    "site_title": "Test",
                    "default_language_code": "HU",

                    "country_names": {
                        "HU": "Hungary",
                    },

                    "output": "public/tv.m3u",
                    "audit_path": "audit.json",

                    "sources": [
                        {
                            "name": "Hungary",
                            "kind": "base",
                            "language_code": "HU",
                            "path": "source.m3u",
                        }
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

            playlist = (
                root
                / "public"
                / "tv.m3u"
            ).read_text(
                encoding="utf-8"
            )

            self.assertIn(
                'group-title="Hungary | General"',
                playlist,
            )
			
    def test_city_tv_default_https_port_is_deduplicated(self):
        base_url = "https://citytv.hu/playlist.m3u8"
        duplicate_url = "https://citytv.hu:443/playlist.m3u8"

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            (root / "audit.json").write_text(
                '{"channels": []}\n',
                encoding="utf-8",
            )

            (root / "one.m3u").write_text(
                '#EXTM3U\n'
                '#EXTINF:-1 tvg-id="CityTV.hu",City TV\n'
                f'{base_url}\n',
                encoding="utf-8",
            )

            (root / "two.m3u").write_text(
                '#EXTM3U\n'
                '#EXTINF:-1 tvg-id="CityTV.hu",City TV duplicate\n'
                f'{duplicate_url}\n',
                encoding="utf-8",
            )

            (root / "config.json").write_text(
                json.dumps({
                    "site_title": "Test",
                    "default_language_code": "HU",
                    "output": "public/tv.m3u",
                    "audit_path": "audit.json",
                    "sources": [
                        {
                            "name": "IPTV-org Hungary",
                            "path": "one.m3u",
                        },
                        {
                            "name": "City TV extra",
                            "path": "two.m3u",
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

            playlist = (
                root / "public" / "tv.m3u"
            ).read_text(encoding="utf-8")

            # The first/original source URL is preserved.
            self.assertEqual(playlist.count(base_url), 1)

            # The canonically equivalent :443 version is not published.
            self.assertNotIn(duplicate_url, playlist)

            with (
                root / "public" / "duplicates.csv"
            ).open(
                encoding="utf-8-sig",
                newline="",
            ) as f:
                duplicates = list(csv.DictReader(f))

            self.assertEqual(len(duplicates), 1)
            self.assertEqual(
                duplicates[0]["stream_url"],
                duplicate_url,
            )

    def test_multiple_base_sources_are_all_base_channels(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            (
                root / "audit.json"
            ).write_text(
                '{"channels": []}\n',
                encoding="utf-8",
            )

            (
                root / "hu.m3u"
            ).write_text(
                '#EXTM3U\n'
                '#EXTINF:-1 '
                'tvg-id="DemoHU.hu",'
                'Hungarian Base TV\n'
                'https://example.test/hu.m3u8\n',
                encoding="utf-8",
            )

            (
                root / "sk.m3u"
            ).write_text(
                '#EXTM3U\n'
                '#EXTINF:-1 '
                'tvg-id="DemoSK.sk",'
                'Slovak Base TV\n'
                'https://example.test/sk.m3u8\n',
                encoding="utf-8",
            )

            (
                root / "hu-alt.m3u"
            ).write_text(
                '#EXTM3U\n'
                '#EXTINF:-1 '
                'tvg-id="DemoExtra.hu",'
                'Hungarian Added TV\n'
                'https://example.test/hu-extra.m3u8\n',
                encoding="utf-8",
            )

            (
                root / "config.json"
            ).write_text(
                json.dumps({
                    "site_title": "Test",
                    "default_language_code": "HU",

                    "country_names": {
                        "HU": "Hungary",
                        "SK": "Slovakia",
                        "CZ": "Czechia",
                    },

                    "output": "public/tv.m3u",
                    "audit_path": "audit.json",

                    "sources": [
                        {
                            "name": "Hungary",
                            "kind": "base",
                            "language_code": "HU",
                            "path": "hu.m3u",
                        },
                        {
                            "name": "Slovakia",
                            "kind": "base",
                            "language_code": "SK",
                            "path": "sk.m3u",
                        },
                        {
                            "name": "Hungarian alternatives",
                            "kind": "alternatives",
                            "language_code": "HU",
                            "path": "hu-alt.m3u",
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

            with (
                root
                / "public"
                / "channels.csv"
            ).open(
                encoding="utf-8-sig",
                newline="",
            ) as f:
                rows = list(
                    csv.DictReader(f)
                )

            classifications = {
                row["channel_name"]:
                row["classification"]
                for row in rows
            }

            self.assertEqual(
                classifications[
                    "Hungarian Base TV"
                ],
                "Base channel",
            )

            # THIS is the regression we care about:
            # second base source must still be Base.
            self.assertEqual(
                classifications[
                    "Slovak Base TV"
                ],
                "Base channel",
            )

            self.assertEqual(
                classifications[
                    "Hungarian Added TV"
                ],
                "Added channel",
            )

            report = json.loads(
                (
                    root
                    / "public"
                    / "report.json"
                ).read_text(
                    encoding="utf-8"
                )
            )

            language_stats = {
                row["language_code"]: row
                for row in report["languages"]
            }

            self.assertEqual(
                language_stats["HU"][
                    "unique_channels"
                ],
                2,
            )

            self.assertEqual(
                language_stats["HU"][
                    "base_channels"
                ],
                1,
            )

            self.assertEqual(
                language_stats["HU"][
                    "added_channels"
                ],
                1,
            )

            self.assertEqual(
                language_stats["SK"][
                    "unique_channels"
                ],
                1,
            )

            self.assertEqual(
                language_stats["SK"][
                    "base_channels"
                ],
                1,
            )

            sources = {
                row["name"]: row
                for row in report["sources"]
            }

            self.assertEqual(
                sources["Hungary"]["kind"],
                "base",
            )

            self.assertEqual(
                sources["Slovakia"]["kind"],
                "base",
            )

            self.assertEqual(
                sources[
                    "Hungarian alternatives"
                ]["kind"],
                "alternatives",
            )

    def test_multiple_sources_without_kind_default_to_base(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            (
                root / "audit.json"
            ).write_text(
                '{"channels": []}\n',
                encoding="utf-8",
            )

            (
                root / "hu.m3u"
            ).write_text(
                '#EXTM3U\n'
                '#EXTINF:-1 '
                'tvg-id="TestHU.hu",HU TV\n'
                'https://example.test/hu.m3u8\n',
                encoding="utf-8",
            )

            (
                root / "sk.m3u"
            ).write_text(
                '#EXTM3U\n'
                '#EXTINF:-1 '
                'tvg-id="TestSK.sk",SK TV\n'
                'https://example.test/sk.m3u8\n',
                encoding="utf-8",
            )

            (
                root / "config.json"
            ).write_text(
                json.dumps({
                    "site_title": "Test",
                    "default_language_code": "HU",
                    "output": "public/tv.m3u",
                    "audit_path": "audit.json",

                    "sources": [
                        {
                            "name": "Hungary",
                            "language_code": "HU",
                            "path": "hu.m3u",
                        },
                        {
                            "name": "Slovakia",
                            "language_code": "SK",
                            "path": "sk.m3u",
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

            with (
                root
                / "public"
                / "channels.csv"
            ).open(
                encoding="utf-8-sig",
                newline="",
            ) as f:
                rows = list(
                    csv.DictReader(f)
                )

            self.assertEqual(
                {
                    row["classification"]
                    for row in rows
                },
                {"Base channel"},
            )
			
if __name__ == "__main__":
    unittest.main()
