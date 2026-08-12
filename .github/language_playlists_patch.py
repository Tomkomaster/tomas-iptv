from __future__ import annotations

import json
from pathlib import Path

ROOT = Path.cwd()


def replace_once(rel: str, old: str, new: str) -> None:
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one match in {rel}, found {count}: {old[:180]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Configuration: additive language outputs. Existing country/main URLs stay put.
# ---------------------------------------------------------------------------
config_path = ROOT / "config.json"
cfg = json.loads(config_path.read_text(encoding="utf-8"))
cfg["language_names"] = {
    "hun": "Hungarian",
    "slk": "Slovak",
    "ces": "Czech",
}
cfg["language_outputs"] = {
    "hun": "public/by-language/hun.m3u",
    "slk": "public/by-language/slk.m3u",
    "ces": "public/by-language/ces.m3u",
}

# Keep the new keys next to country outputs for readability instead of appending
# them at the end of the JSON object.
ordered_cfg: dict = {}
for key, value in cfg.items():
    ordered_cfg[key] = value
    if key == "country_outputs":
        ordered_cfg["language_names"] = cfg["language_names"]
        ordered_cfg["language_outputs"] = cfg["language_outputs"]
ordered_cfg.pop("language_names", None)
ordered_cfg.pop("language_outputs", None)
# Rebuild once more because pop above removes the inserted values too.
final_cfg: dict = {}
for key, value in cfg.items():
    if key in {"language_names", "language_outputs"}:
        continue
    final_cfg[key] = value
    if key == "country_outputs":
        final_cfg["language_names"] = cfg["language_names"]
        final_cfg["language_outputs"] = cfg["language_outputs"]
config_path.write_text(
    json.dumps(final_cfg, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)


# ---------------------------------------------------------------------------
# Spoken-language support should also be discoverable from language_outputs.
# ---------------------------------------------------------------------------
replace_once(
    "country_language.py",
    '''    def add(values) -> None:\n        for code in normalize_language_codes(values):\n            if code not in result:\n                result.append(code)\n\n    for country in configured_country_codes(cfg):\n''',
    '''    def add(values) -> None:\n        for code in normalize_language_codes(values):\n            if code not in result:\n                result.append(code)\n\n    language_outputs = cfg.get("language_outputs") or {}\n    if isinstance(language_outputs, dict):\n        add(list(language_outputs))\n\n    for country in configured_country_codes(cfg):\n''',
)


# ---------------------------------------------------------------------------
# Build model: keep out-of-country language-source entries in an isolated
# language catalog without letting them alter the existing country/main/test
# candidate universe or URL precedence.
# ---------------------------------------------------------------------------
replace_once(
    "build.py",
    '''    final_entries: list[dict] = []\n    duplicate_rows: list[dict] = []\n''',
    '''    final_entries: list[dict] = []\n    # Country-neutral language sources may contain verified channels from\n    # countries that do not have a country playlist yet. Keep those entries\n    # isolated so they can feed by-language outputs without changing the\n    # existing tv.m3u/test.m3u/per-country publication universe.\n    language_only_entries: list[dict] = []\n    duplicate_rows: list[dict] = []\n''',
)

replace_once(
    "build.py",
    '''            if (\n                country_mode == "tvg_id"\n                and final_entry_country not in supported_country_codes\n            ):\n                out_of_scope_country_entries += 1\n                continue\n\n            key = channel_key(entry)\n''',
    '''            language_only_country_entry = (\n                country_mode == "tvg_id"\n                and final_entry_country not in supported_country_codes\n            )\n            if language_only_country_entry:\n                out_of_scope_country_entries += 1\n\n            key = channel_key(entry)\n''',
)

replace_once(
    "build.py",
    '''            entry[\n                "source_flags"\n            ] = extract_source_flags(\n                entry.get(\n                    "display_name",\n                    "",\n                )\n            )\n\n            if url_key in seen_urls:\n''',
    '''            entry[\n                "source_flags"\n            ] = extract_source_flags(\n                entry.get(\n                    "display_name",\n                    "",\n                )\n            )\n\n            if language_only_country_entry:\n                # Preserve this candidate only for language-centric outputs.\n                # Do not put it into seen_urls/seen_channels: doing so would\n                # change which existing HU/SK/CZ source wins duplicate URL\n                # precedence later in the normal country build.\n                entry["classification"] = "Language-only channel"\n                entry["country_output_enabled"] = False\n                language_only_entries.append(dict(entry))\n                continue\n\n            entry["country_output_enabled"] = True\n\n            if url_key in seen_urls:\n''',
)

# Add reusable helpers immediately before write_m3u_playlist.
replace_once(
    "build.py",
    '''def write_m3u_playlist(\n    path: Path,\n''',
    '''def build_language_catalog_entries(\n    country_entries: list[dict],\n    language_only_entries: list[dict],\n) -> list[dict]:\n    """Build a URL-unique catalog for spoken-language playlists.\n\n    Existing country entries are inserted first and therefore keep authority\n    for an exact URL already published by the country build. A language-only\n    duplicate may still add additional spoken-language metadata, but it cannot\n    steal or rewrite the established country identity.\n    """\n    result: list[dict] = []\n    by_url: dict[str, dict] = {}\n\n    for entry in [*country_entries, *language_only_entries]:\n        url = str(entry.get("url") or "").strip()\n        url_key = canonical_stream_url(url)\n        if not url_key:\n            continue\n\n        languages = normalize_spoken_language_codes(\n            entry.get("language_codes")\n        )\n\n        current = by_url.get(url_key)\n        if current is not None:\n            current["language_codes"] = normalize_spoken_language_codes(\n                [\n                    *(current.get("language_codes") or []),\n                    *languages,\n                ]\n            )\n            continue\n\n        candidate = dict(entry)\n        candidate["language_codes"] = languages\n        by_url[url_key] = candidate\n        result.append(candidate)\n\n    return result\n\n\ndef entries_for_spoken_language(\n    entries: list[dict],\n    language_code: str,\n) -> list[dict]:\n    """Return entries explicitly carrying one normalized spoken language."""\n    code = normalize_spoken_language_code(language_code)\n    if not code:\n        raise ValueError(f"Unsupported spoken language code: {language_code!r}")\n\n    return [\n        entry\n        for entry in entries\n        if code in normalize_spoken_language_codes(\n            entry.get("language_codes")\n        )\n    ]\n\n\ndef write_m3u_playlist(\n    path: Path,\n''',
)

# Build the independent language candidate/audit/stable universe while leaving
# existing audit/report semantics based on final_entries untouched.
replace_once(
    "build.py",
    '''    audit_rows = prepare_audit_rows(\n        audit_items,\n        final_entries,\n        supported_language_codes=(\n            supported_language_codes\n        ),\n        cfg=cfg,\n    )\n    test_candidates = (\n''',
    '''    audit_rows = prepare_audit_rows(\n        audit_items,\n        final_entries,\n        supported_language_codes=(\n            supported_language_codes\n        ),\n        cfg=cfg,\n    )\n\n    language_catalog_entries = build_language_catalog_entries(\n        final_entries,\n        language_only_entries,\n    )\n    language_audit_rows = prepare_audit_rows(\n        audit_items,\n        language_catalog_entries,\n        supported_language_codes=(\n            supported_language_codes\n        ),\n        cfg=cfg,\n    )\n\n    test_candidates = (\n''',
)

replace_once(
    "build.py",
    '''    (\n        stable_candidates,\n        excluded_rows,\n    ) = (\n        select_stable_playlist_candidates(\n            final_entries,\n            audit_rows,\n            cfg,\n        )\n    )\n\n    test_entries = (\n''',
    '''    (\n        stable_candidates,\n        excluded_rows,\n    ) = (\n        select_stable_playlist_candidates(\n            final_entries,\n            audit_rows,\n            cfg,\n        )\n    )\n\n    (\n        language_stable_candidates,\n        _language_excluded_rows,\n    ) = select_stable_playlist_candidates(\n        language_catalog_entries,\n        language_audit_rows,\n        cfg,\n    )\n\n    test_entries = (\n''',
)

replace_once(
    "build.py",
    '''    published_entries = (\n        prepare_published_entries(\n            stable_candidates,\n            cfg,\n        )\n    )\n\n    stable_urls = {\n''',
    '''    published_entries = (\n        prepare_published_entries(\n            stable_candidates,\n            cfg,\n        )\n    )\n\n    language_published_entries = prepare_published_entries(\n        language_stable_candidates,\n        cfg,\n    )\n\n    stable_urls = {\n''',
)

# Generate configured language playlists immediately after per-country outputs.
replace_once(
    "build.py",
    '''        country_playlist_counts[\n            country_code\n        ] = len(\n            country_entries\n        )\n\n    inventory_rows = [\n''',
    '''        country_playlist_counts[\n            country_code\n        ] = len(\n            country_entries\n        )\n\n    # Stable per-spoken-language playlists. These are independent of enabled\n    # country outputs: a verified RS/hun entry can therefore live in hun.m3u\n    # even when there is no public rs.m3u yet. Country prefixes remain visible\n    # inside language playlists so geography is never lost.\n    language_outputs = cfg.get("language_outputs") or {}\n    if not isinstance(language_outputs, dict):\n        raise RuntimeError("language_outputs must be a JSON object.")\n\n    language_names = cfg.get("language_names") or {}\n    if not isinstance(language_names, dict):\n        raise RuntimeError("language_names must be a JSON object.")\n\n    language_playlist_counts: dict[str, int] = {}\n\n    for raw_language_code, relative_path in language_outputs.items():\n        language_code = normalize_spoken_language_code(\n            str(raw_language_code)\n        )\n        if not language_code:\n            raise RuntimeError(\n                f"Invalid language_outputs key: {raw_language_code!r}"\n            )\n\n        raw_path = str(relative_path or "").strip()\n        if not raw_path:\n            raise RuntimeError(\n                f"language_outputs[{raw_language_code!r}] requires a path."\n            )\n\n        language_entries = entries_for_spoken_language(\n            language_published_entries,\n            language_code,\n        )\n\n        language_name = str(\n            language_names.get(language_code)\n            or language_code\n        ).strip()\n\n        write_m3u_playlist(\n            ROOT / raw_path,\n            cfg,\n            language_entries,\n            generated,\n            f"Stable {language_name} spoken-language playlist",\n            name_style="country",\n        )\n\n        language_playlist_counts[language_code] = len(language_entries)\n\n    inventory_rows = [\n''',
)

replace_once(
    "build.py",
    '''            "country_stream_urls": (\n                country_playlist_counts\n            ),\n        },\t\t\n''',
    '''            "country_stream_urls": (\n                country_playlist_counts\n            ),\n            "language_stream_urls": (\n                language_playlist_counts\n            ),\n        },\t\t\n''',
)

replace_once(
    "build.py",
    '''        "schema_version": 22,\n''',
    '''        "schema_version": 23,\n''',
)

# Add a small console summary after the existing per-country stable counts.
replace_once(
    "build.py",
    '''    for (\n        country_code,\n        stream_count,\n    ) in sorted(\n        country_playlist_counts.items()\n    ):\n        print(\n            f"Stable {country_code}:"\n            f"{' ' * max(1, 15 - len(country_code))}"\n            f"{stream_count} streams"\n        )\n\n    print(\n        "Manual audit:          "\n''',
    '''    for (\n        country_code,\n        stream_count,\n    ) in sorted(\n        country_playlist_counts.items()\n    ):\n        print(\n            f"Stable {country_code}:"\n            f"{' ' * max(1, 15 - len(country_code))}"\n            f"{stream_count} streams"\n        )\n\n    for (\n        language_code,\n        stream_count,\n    ) in sorted(\n        language_playlist_counts.items()\n    ):\n        print(\n            f"Language {language_code}:"\n            f"{' ' * max(1, 13 - len(language_code))}"\n            f"{stream_count} streams"\n        )\n\n    print(\n        "Manual audit:          "\n''',
)


# ---------------------------------------------------------------------------
# Documentation.
# ---------------------------------------------------------------------------
replace_once(
    "README.md",
    '''Stable country playlists:\n\n```text\nhttps://tomkomaster.github.io/tomas-iptv/hu.m3u\nhttps://tomkomaster.github.io/tomas-iptv/sk.m3u\nhttps://tomkomaster.github.io/tomas-iptv/cz.m3u\n```\n\nTesting/research playlist:\n''',
    '''Stable country playlists:\n\n```text\nhttps://tomkomaster.github.io/tomas-iptv/hu.m3u\nhttps://tomkomaster.github.io/tomas-iptv/sk.m3u\nhttps://tomkomaster.github.io/tomas-iptv/cz.m3u\n```\n\nStable spoken-language playlists:\n\n```text\nhttps://tomkomaster.github.io/tomas-iptv/by-language/hun.m3u\nhttps://tomkomaster.github.io/tomas-iptv/by-language/slk.m3u\nhttps://tomkomaster.github.io/tomas-iptv/by-language/ces.m3u\n```\n\nLanguage playlists keep geography visible in the channel name. For example, a verified Hungarian-language Serbian station is published as `[RS] ...` inside `by-language/hun.m3u`; it is not moved into `hu.m3u` merely because it speaks Hungarian. This also means future outputs such as `deu.m3u`, `srp.m3u` or `ron.m3u` only require a configured language output plus suitable source/audit data.\n\nTesting/research playlist:\n''',
)

replace_once(
    "README.md",
    '''13. generates the shared stable, testing and per-country playlists;\n14. generates CSV and JSON reports;\n''',
    '''13. generates the shared stable, testing, per-country and per-language playlists;\n14. generates CSV and JSON reports;\n''',
)

replace_once(
    "docs/country-language-model.md",
    '''Derived entries whose country is not currently configured in `country_outputs` are ignored rather than mislabeled. When that country is enabled later, the same language source can contribute it without changing the attribution model.\n''',
    '''Derived entries whose country is not currently configured in `country_outputs` are excluded from the existing shared/country/testing publication universe, but they are retained in an isolated spoken-language catalog. If such an entry is manually verified, it can be published under its real country prefix in a configured `by-language/<iso639-3>.m3u` output without requiring a country playlist first.\n\nFor example, `PannonRTV.rs@SD` with `language_codes=[hun]` can appear as `[RS] Pannon RTV` in `by-language/hun.m3u` while no `rs.m3u` exists. Exact URLs already owned by the established country build keep their current country identity in the language catalog, so adding language outputs cannot silently change existing country URL precedence.\n''',
)


# ---------------------------------------------------------------------------
# Regression tests.
# ---------------------------------------------------------------------------
test_path = ROOT / "tests/test_language_playlists.py"
test_path.write_text(
    '''import json\nimport tempfile\nimport unittest\nfrom pathlib import Path\n\nfrom build import (\n    build_language_catalog_entries,\n    entries_for_spoken_language,\n    write_m3u_playlist,\n)\nfrom country_language import configured_language_codes\n\n\nROOT = Path(__file__).resolve().parents[1]\n\n\nclass LanguagePlaylistTests(unittest.TestCase):\n    def test_config_exposes_three_initial_language_outputs(self):\n        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))\n        self.assertEqual(\n            cfg["language_outputs"],\n            {\n                "hun": "public/by-language/hun.m3u",\n                "slk": "public/by-language/slk.m3u",\n                "ces": "public/by-language/ces.m3u",\n            },\n        )\n        supported = configured_language_codes(cfg)\n        for code in ("hun", "slk", "ces"):\n            self.assertIn(code, supported)\n\n    def test_serbian_hungarian_entry_remains_rs_in_hungarian_catalog(self):\n        country_entry = {\n            "url": "https://example.test/hu.m3u8",\n            "country_code": "HU",\n            "language_code": "HU",\n            "language_codes": ["hun"],\n            "channel_name": "Hungary One",\n            "display_name": "Hungary One",\n            "published_name": "[HU OK] Hungary One",\n            "group_title": "Hungary | General",\n            "lines": [\n                '#EXTINF:-1 tvg-id="HungaryOne.hu@SD" group-title="Hungary | General",[HU OK] Hungary One',\n                "https://example.test/hu.m3u8",\n            ],\n        }\n        serbian_entry = {\n            "url": "https://example.test/rs-hun.m3u8",\n            "country_code": "RS",\n            "language_code": "RS",\n            "language_codes": ["hun"],\n            "channel_name": "Pannon RTV",\n            "display_name": "Pannon RTV",\n            "published_name": "[RS OK] Pannon RTV",\n            "group_title": "Serbia | General",\n            "lines": [\n                '#EXTINF:-1 tvg-id="PannonRTV.rs@SD" group-title="Serbia | General",[RS OK] Pannon RTV',\n                "https://example.test/rs-hun.m3u8",\n            ],\n        }\n\n        catalog = build_language_catalog_entries([country_entry], [serbian_entry])\n        hungarian = entries_for_spoken_language(catalog, "hun")\n        self.assertEqual({e["country_code"] for e in hungarian}, {"HU", "RS"})\n\n        with tempfile.TemporaryDirectory() as tmp:\n            output = Path(tmp) / "hun.m3u"\n            write_m3u_playlist(\n                output,\n                {"epg": {"enabled": False}},\n                hungarian,\n                "2026-08-12 00:00:00 UTC",\n                "Stable Hungarian spoken-language playlist",\n                name_style="country",\n            )\n            text = output.read_text(encoding="utf-8")\n            self.assertIn("[HU] Hungary One", text)\n            self.assertIn("[RS] Pannon RTV", text)\n\n    def test_exact_country_url_keeps_geography_but_merges_language_metadata(self):\n        country_entry = {\n            "url": "https://example.test/shared.m3u8",\n            "country_code": "HU",\n            "language_code": "HU",\n            "language_codes": ["hun"],\n        }\n        derived_duplicate = {\n            "url": "https://example.test/shared.m3u8",\n            "country_code": "RS",\n            "language_code": "RS",\n            "language_codes": ["srp", "hun"],\n        }\n        catalog = build_language_catalog_entries(\n            [country_entry],\n            [derived_duplicate],\n        )\n        self.assertEqual(len(catalog), 1)\n        self.assertEqual(catalog[0]["country_code"], "HU")\n        self.assertEqual(catalog[0]["language_codes"], ["hun", "srp"])\n\n    def test_multilingual_entry_can_appear_in_multiple_language_playlists(self):\n        entry = {\n            "url": "https://example.test/multi.m3u8",\n            "country_code": "RS",\n            "language_codes": ["srp", "hun"],\n        }\n        catalog = build_language_catalog_entries([], [entry])\n        self.assertEqual(len(entries_for_spoken_language(catalog, "hun")), 1)\n        self.assertEqual(len(entries_for_spoken_language(catalog, "srp")), 1)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    encoding="utf-8",
)
