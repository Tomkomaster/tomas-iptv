#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Missing anchor in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) Builder-level guard: provider/research TEST labels are internal metadata,
# never part of a logical channel identity or published channel name.
replace_once(
    "build.py",
    "CUSTOM_PREFIX_RE = re.compile(r'^\\[[A-Z]{2,3}(?:\\s+(?:OK|TV|PC|\\?|X))?\\]\\s*', re.IGNORECASE)\n",
    """CUSTOM_PREFIX_RE = re.compile(r'^\\[[A-Z]{2,3}(?:\\s+(?:OK|TV|PC|\\?|X))?\\]\\s*', re.IGNORECASE)
INTERNAL_PROVIDER_TEST_SUFFIX_RE = re.compile(
    r"""
    (?:\\s*[-–—]\\s*|\\s+)
    (?:
        LEGACY(?:\\s+ANTIK)?
        | ANTIK
        | PANACCESS
        | KABELKO
        | REBIT
        | STREAMLOCK
        | ZSTV\\s+DIRECT
        | JOJ\\s+CDN
    )
    \\s+TEST
    \\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)
""",
)

replace_once(
    "build.py",
    """def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = re.sub(r"[^\\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def normalized_tvg_id(tvg_id: str) -> str:
""",
    """def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = re.sub(r"[^\\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def strip_internal_candidate_annotations(name: str) -> str:
    \"\"\"Remove provider/research TEST labels from a channel name.

    Labels such as ``ANTIK TEST`` and ``PANACCESS TEST`` describe where a
    candidate URL came from. They belong in comments/audit provenance, not in
    the logical channel identity or the name shown to playlist users.
    \"\"\"
    value = " ".join(str(name or "").split()).strip()
    previous = None
    while value and value != previous:
        previous = value
        value = INTERNAL_PROVIDER_TEST_SUFFIX_RE.sub("", value).strip()
    return value or "Unnamed channel"


def normalized_tvg_id(tvg_id: str) -> str:
""",
)

replace_once(
    "build.py",
    """    tvg_name = normalize_text(entry.get("tvg_name", ""))
    if tvg_name:
        return f"name:{tvg_name}"

    return f"name:{normalize_text(strip_display_annotations(entry.get('display_name', '')))}"
""",
    """    tvg_name = normalize_text(
        strip_internal_candidate_annotations(
            entry.get("tvg_name", "")
        )
    )
    if tvg_name:
        return f"name:{tvg_name}"

    display_name = strip_internal_candidate_annotations(
        entry.get("display_name", "")
    )
    return f"name:{normalize_text(strip_display_annotations(display_name))}"
""",
)

replace_once(
    "build.py",
    """    else:
        metadata += f' group-title=\"{safe_group}\"'
    return f"{metadata},{new_name}"
""",
    """    else:
        metadata += f' group-title=\"{safe_group}\"'

    # Some source playlists put research provenance in tvg-name, e.g.
    # \"JOJ Šport 2 ANTIK TEST\". Clean it as well because a number of
    # IPTV clients prefer tvg-name over the visible text after the comma.
    tvg_name_match = re.search(
        r'\\s+tvg-name=\"([^\"]*)\"',
        metadata,
        flags=re.IGNORECASE,
    )
    if tvg_name_match:
        clean_tvg_name = strip_internal_candidate_annotations(
            tvg_name_match.group(1)
        ).replace('"', "'")
        metadata = re.sub(
            r'\\s+tvg-name=\"[^\"]*\"',
            f' tvg-name=\"{clean_tvg_name}\"',
            metadata,
            count=1,
            flags=re.IGNORECASE,
        )

    return f"{metadata},{new_name}"
""",
)

replace_once(
    "build.py",
    """            candidate_name = strip_custom_prefix(
                candidate_name
            )

            candidate_name = strip_display_annotations(
                candidate_name
            )
""",
    """            candidate_name = strip_custom_prefix(
                candidate_name
            )

            candidate_name = strip_internal_candidate_annotations(
                candidate_name
            )

            candidate_name = strip_display_annotations(
                candidate_name
            )
""",
)

replace_once(
    "build.py",
    """                original_display = (
                    strip_custom_prefix(
                        entry.get(
                            "display_name",
                            "",
                        )
                    )
                )
""",
    """                original_display = (
                    strip_internal_candidate_annotations(
                        strip_custom_prefix(
                            entry.get(
                                "display_name",
                                "",
                            )
                        )
                    )
                )
""",
)

replace_once(
    "build.py",
    """            clean_name = strip_display_annotations(entry.get("display_name", ""))
""",
    """            clean_name = strip_display_annotations(
                strip_internal_candidate_annotations(
                    entry.get("display_name", "")
                )
            )
""",
)

# 2) Clean the current Slovak extras at the data source too. Provider identity
# stays in comments and audit.json; M3U name/tvg-name remains the real station.
extras = Path("extras/sk.m3u")
text = extras.read_text(encoding="utf-8")
replacements = {
    'tvg-name="JOJ Šport 2 ANTIK TEST"': 'tvg-name="JOJ Šport 2"',
    'tvg-name="JOJ Šport 2 REBIT TEST"': 'tvg-name="JOJ Šport 2"',
    'tvg-name="JOJ Šport 2 JOJ CDN TEST"': 'tvg-name="JOJ Šport 2"',
    'tvg-name="Jojko JOJ CDN TEST"': 'tvg-name="Jojko"',
    'tvg-name="JOJ Cinema JOJ CDN TEST"': 'tvg-name="JOJ Cinema"',
    'tvg-name="TV NRSR JOJ CDN TEST"': 'tvg-name="TV NRSR"',
    'tvg-name="Mestská TV Košice ANTIK TEST"': 'tvg-name="Mestská TV Košice"',
    ',Bardejovská TV - KABELKO TEST': ',Bardejovská TV',
    ',TV Bratislava - ANTIK TEST': ',TV Bratislava',
    ',TV Reduta - ANTIK TEST': ',TV Reduta',
    ',Televízia ZEMPLÍN - ANTIK TEST': ',Televízia ZEMPLÍN',
    ',Mestská televízia Trnava - ANTIK TEST': ',Mestská televízia Trnava',
    ',TV Kežmarok - ANTIK TEST': ',TV Kežmarok',
    ',TV Bratislava - PANACCESS TEST': ',TV Bratislava',
    ',TV Sen - PANACCESS TEST': ',TV Sen',
    ',Televízia Turiec - PANACCESS TEST': ',Televízia Turiec',
    ',Západoslovenská TV - ZSTV DIRECT TEST': ',Západoslovenská TV',
    ',TV Reduta - STREAMLOCK TEST': ',TV Reduta',
    ',TV Severka - PANACCESS TEST': ',TV Severka',
    ',TV REGION - LEGACY TEST': ',TV REGION',
    ',JOJ +1 - LEGACY ANTIK TEST': ',JOJ +1',
}
for old, new in replacements.items():
    if old not in text:
        raise RuntimeError(f"Missing extras/sk.m3u cleanup target: {old}")
    text = text.replace(old, new)
extras.write_text(text, encoding="utf-8")

# 3) Regression tests.
Path("tests/test_provider_test_channel_names.py").write_text(
    '''import tempfile\nimport unittest\nfrom pathlib import Path\n\nimport build\n\n\nclass ProviderTestChannelNameTests(unittest.TestCase):\n    def test_strips_internal_provider_test_suffixes(self):\n        cases = {\n            "Televízia Turiec - PANACCESS TEST": "Televízia Turiec",\n            "Televízia ZEMPLÍN - ANTIK TEST": "Televízia ZEMPLÍN",\n            "Bardejovská TV - KABELKO TEST": "Bardejovská TV",\n            "TV REGION - LEGACY TEST": "TV REGION",\n            "JOJ +1 - LEGACY ANTIK TEST": "JOJ +1",\n            "JOJ Šport 2 ANTIK TEST": "JOJ Šport 2",\n            "JOJ Cinema JOJ CDN TEST": "JOJ Cinema",\n        }\n        for raw, expected in cases.items():\n            with self.subTest(raw=raw):\n                self.assertEqual(\n                    build.strip_internal_candidate_annotations(raw),\n                    expected,\n                )\n\n    def test_provider_suffix_does_not_create_a_new_logical_identity(self):\n        clean = build.parse_entries(\n            '#EXTM3U\\n#EXTINF:-1 tvg-name="JOJ Šport 2",JOJ Šport 2\\nhttps://example.test/clean.m3u8\\n'\n        )[0]\n        antik = build.parse_entries(\n            '#EXTM3U\\n#EXTINF:-1 tvg-name="JOJ Šport 2 ANTIK TEST",JOJ Šport 2\\nhttps://example.test/antik.m3u8\\n'\n        )[0]\n        rebit = build.parse_entries(\n            '#EXTM3U\\n#EXTINF:-1 tvg-name="JOJ Šport 2 REBIT TEST",JOJ Šport 2\\nhttps://example.test/rebit.m3u8\\n'\n        )[0]\n        self.assertEqual(build.channel_key(clean), build.channel_key(antik))\n        self.assertEqual(build.channel_key(clean), build.channel_key(rebit))\n\n    def test_published_playlist_uses_channel_and_language_not_provider_label(self):\n        source = build.parse_entries(\n            '#EXTM3U\\n'\n            '#EXTINF:-1 tvg-id="TVSen.sk" tvg-name="TV Sen" group-title="Slovakia Test",TV Sen - PANACCESS TEST\\n'\n            'https://cdn.example.test/tvsen/index.m3u8\\n'\n        )[0]\n        source.update({\n            "channel_name": "TV Sen - PANACCESS TEST",\n            "language_code": "SK",\n            "country_name": "Slovakia",\n            "content_group": "General",\n            "source_group_title": "Slovakia Test",\n            "_decision": "Verified",\n            "_source_order": 1,\n        })\n\n        published = build.prepare_published_entries(\n            [source],\n            {"default_language_code": "HU", "country_names": {"SK": "Slovakia"}},\n        )\n        self.assertEqual(len(published), 1)\n        self.assertEqual(published[0]["published_name"], "[SK OK] TV Sen")\n        self.assertNotIn("PANACCESS TEST", published[0]["lines"][0])\n        self.assertIn('tvg-name="TV Sen"', published[0]["lines"][0])\n\n        with tempfile.TemporaryDirectory() as tmp:\n            path = Path(tmp) / "tv.m3u"\n            build.write_m3u_playlist(\n                path,\n                {"default_language_code": "HU", "country_names": {"SK": "Slovakia"}},\n                published,\n                "2026-08-12 00:00:00 UTC",\n                "test",\n                name_style="language",\n            )\n            text = path.read_text(encoding="utf-8")\n            self.assertIn(",[SK] TV Sen", text)\n            self.assertNotIn("PANACCESS TEST", text)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    encoding="utf-8",
)

print("Provider test-channel names cleaned.")
