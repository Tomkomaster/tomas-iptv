from pathlib import Path
import json


ROOT = Path(__file__).resolve().parent


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# epg_merge.py: explicit audited external aliases, higher priority than
# generated name/quality matching. There is deliberately no fuzzy runtime
# matching.
# ---------------------------------------------------------------------------
path = ROOT / "epg_merge.py"
text = path.read_text(encoding="utf-8")

text = replace_once(
    text,
    'METHOD_RANK = {\n    "external_exact_id": 3,\n    "external_quality_id": 2,\n    "external_unique_name": 1,\n}',
    'METHOD_RANK = {\n    "external_explicit_alias": 4,\n    "external_exact_id": 3,\n    "external_quality_id": 2,\n    "external_unique_name": 1,\n}',
    "method rank",
)

text = replace_once(
    text,
    'def build_external_mapping(\n    playlist_rows: list[tuple[str, str]],\n    external_root: ET.Element,\n) -> tuple[',
    'def build_external_mapping(\n    playlist_rows: list[tuple[str, str]],\n    external_root: ET.Element,\n    explicit_aliases: dict[str, str] | None = None,\n) -> tuple[',
    "mapping signature",
)

needle = '''    proposals: dict[\n        str,\n        list[dict[str, str]],\n    ] = defaultdict(list)\n\n    for channel in external_root.findall(\n        "channel"\n    ):\n'''
replacement = '''    proposals: dict[\n        str,\n        list[dict[str, str]],\n    ] = defaultdict(list)\n\n    playlist_id_set = {\n        tvg_id\n        for tvg_id, _\n        in playlist_rows\n    }\n    external_id_set = {\n        (channel.get("id") or "").strip()\n        for channel\n        in external_root.findall("channel")\n        if (channel.get("id") or "").strip()\n    }\n\n    # Explicit aliases are hand-audited identities. They intentionally outrank\n    # all generated matching methods. Missing historical aliases are ignored\n    # safely when either side is not present in the current inputs.\n    for target, external_id in (explicit_aliases or {}).items():\n        target = str(target or "").strip()\n        external_id = str(external_id or "").strip()\n        if (\n            not target\n            or not external_id\n            or target not in playlist_id_set\n            or external_id not in external_id_set\n        ):\n            continue\n        proposals[target].append({\n            "external_id": external_id,\n            "method": "external_explicit_alias",\n        })\n\n    for channel in external_root.findall(\n        "channel"\n    ):\n'''
text = replace_once(text, needle, replacement, "explicit alias proposals")

text = replace_once(
    text,
    '    future_days: int = 7,\n) -> dict:',
    '    future_days: int = 7,\n    external_aliases: dict[str, str] | None = None,\n) -> dict:',
    "merge signature",
)

text = replace_once(
    text,
    '''            ) = build_external_mapping(\n                playlist_rows,\n                external_root,\n            )''',
    '''            ) = build_external_mapping(\n                playlist_rows,\n                external_root,\n                explicit_aliases=external_aliases,\n            )''',
    "mapping call",
)

text = replace_once(
    text,
    '            "mapped_candidates": len(\n                {\n                    info["tvg_id"]\n                    for info\n                    in external_mapping.values()\n                }\n            ),',
    '            "mapped_candidates": len(\n                {\n                    info["tvg_id"]\n                    for info\n                    in external_mapping.values()\n                }\n            ),\n            "explicit_aliases_configured": len(\n                external_aliases or {}\n            ),',
    "report alias count",
)

main_marker = '\n\ndef main() -> None:\n'
loader = '''\n\ndef load_external_aliases(\n    path: Path | None,\n    external_provider: str,\n) -> dict[str, str]:\n    if path is None or not path.is_file():\n        return {}\n\n    data = json.loads(\n        path.read_text(encoding="utf-8")\n    )\n    if not isinstance(data, dict):\n        raise RuntimeError(\n            "EPG alias file must contain a JSON object."\n        )\n\n    provider = str(\n        data.get("provider") or ""\n    ).strip()\n    if (\n        provider\n        and provider != external_provider\n    ):\n        raise RuntimeError(\n            "EPG alias provider mismatch: "\n            f"{provider!r} != {external_provider!r}"\n        )\n\n    raw_aliases = data.get("aliases") or {}\n    if not isinstance(raw_aliases, dict):\n        raise RuntimeError(\n            "EPG alias file 'aliases' must be a JSON object."\n        )\n\n    aliases: dict[str, str] = {}\n    for raw_target, raw_external in raw_aliases.items():\n        target = str(raw_target or "").strip()\n        external_id = str(raw_external or "").strip()\n        if not target or not external_id:\n            raise RuntimeError(\n                "EPG aliases may not contain blank IDs."\n            )\n        if target in aliases:\n            raise RuntimeError(\n                f"Duplicate EPG alias target: {target}"\n            )\n        aliases[target] = external_id\n\n    return aliases\n'''
text = replace_once(text, main_marker, loader + main_marker, "alias loader")

text = replace_once(
    text,
    '''    parser.add_argument(\n        "--external-provider",\n        default="epgshare01.online",\n    )''',
    '''    parser.add_argument(\n        "--external-provider",\n        default="epgshare01.online",\n    )\n    parser.add_argument(\n        "--aliases",\n        type=Path,\n        default=Path("epg_aliases.json"),\n        help=(\n            "Optional explicit external-ID alias file. "\n            "Defaults to epg_aliases.json when present."\n        ),\n    )''',
    "aliases cli",
)

text = replace_once(
    text,
    '''    merge_guides(\n        playlist_path=args.playlist,''',
    '''    external_aliases = load_external_aliases(\n        args.aliases,\n        args.external_provider,\n    )\n\n    merge_guides(\n        playlist_path=args.playlist,''',
    "load aliases main",
)

text = replace_once(
    text,
    '''        future_days=max(\n            args.future_days,\n            0,\n        ),\n        output_path=args.output,''',
    '''        future_days=max(\n            args.future_days,\n            0,\n        ),\n        external_aliases=external_aliases,\n        output_path=args.output,''',
    "pass aliases main",
)

path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# extras/hu.m3u: add only identities backed by current IPTV-org database / API
# evidence. Do not invent IDs for Classics TV, Oxygen Music, Play Music TV, or
# the Marosvasarhely visual-radio feed.
# ---------------------------------------------------------------------------
path = ROOT / "extras" / "hu.m3u"
text = path.read_text(encoding="utf-8")
replacements = {
    '#EXTINF:-1 tvg-name="Nyíregyházi Televízió",Nyíregyházi Televízió (1080p)':
        '#EXTINF:-1 tvg-id="NYTV.hu" tvg-name="Nyíregyházi Televízió",Nyíregyházi Televízió (1080p)',
    '#EXTINF:-1 tvg-name="Halom TV",Halom TV (540p)':
        '#EXTINF:-1 tvg-id="HalomTV.hu" tvg-name="Halom TV",Halom TV (540p)',
    '#EXTINF:-1 tvg-name="Debrecen Televízió",Debrecen Televízió (720p)':
        '#EXTINF:-1 tvg-id="DTV.hu" tvg-name="DTV",DTV / Debrecen Televízió (720p)',
    '#EXTINF:-1 tvg-name="Cegléd Városi TV",Cegléd Városi TV (360p)':
        '#EXTINF:-1 tvg-id="CeglediVarosiTelevizio.hu" tvg-name="Cegléd Városi TV",Cegléd Városi TV (360p)',
    '#EXTINF:-1 tvg-name="TV13",TV13 (720p)':
        '#EXTINF:-1 tvg-id="TV13.hu" tvg-name="TV13",TV13 (720p)',
    '#EXTINF:-1 tvg-name="Ózdi Városi TV",Ózdi Városi TV [HTTPS alternate] (720p)':
        '#EXTINF:-1 tvg-id="OzdiVarosiTV.hu" tvg-name="Ózdi Városi TV",Ózdi Városi TV [HTTPS alternate] (720p)',
}
for old, new in replacements.items():
    text = replace_once(text, old, new, f"extras identity {old}")

# The stream2 endpoint is a distinct current IPTV-org identity: TV Panon.
old = '#EXTINF:-1 tvg-name="Pannon RTV",Pannon RTV [stream2 alternate] (648p)'
new = '#EXTINF:-1 tvg-id="TVPanon.rs" tvg-name="TV Panon",TV Panon (648p)'
text = replace_once(text, old, new, "TV Panon identity")
path.write_text(text, encoding="utf-8")


# Keep the URL-specific manual audit attached to the corrected TV Panon name.
audit_path = ROOT / "audit.json"
audit = json.loads(audit_path.read_text(encoding="utf-8"))
changed = 0
for item in audit.get("channels", []):
    if str(item.get("stream_url") or "").strip() == "https://stream2.nmih.hu:4102/live.m3u8":
        item["channel"] = "TV Panon"
        item["tvg_id"] = "TVPanon.rs"
        note = str(item.get("notes") or "").strip()
        identity_note = "Identity corrected from Pannon RTV alternate to current IPTV-org TV Panon for this exact stream URL."
        if identity_note not in note:
            item["notes"] = " — ".join(part for part in (note, identity_note) if part)
        changed += 1
if changed != 1:
    raise RuntimeError(f"TV Panon audit: expected one URL-specific row, found {changed}")
audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests: explicit aliases work, outrank normalized-name candidates, and alias
# file validation is strict.
# ---------------------------------------------------------------------------
test_path = ROOT / "tests" / "test_epg_aliases.py"
test_path.write_text(r'''import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from epg_merge import (
    build_external_mapping,
    load_external_aliases,
    merge_guides,
)


class EpgAliasTests(unittest.TestCase):
    def test_explicit_alias_outranks_generated_name_mapping(self):
        playlist_rows = [
            ("Legacy.hu@SD", "Same Name"),
        ]
        external = ET.fromstring("""
        <tv>
          <channel id="Wrong.hu"><display-name>Same Name</display-name></channel>
          <channel id="Right.hu"><display-name>Different Name</display-name></channel>
        </tv>
        """)

        mapping, ambiguous = build_external_mapping(
            playlist_rows,
            external,
            explicit_aliases={"Legacy.hu@SD": "Right.hu"},
        )

        self.assertEqual(ambiguous, [])
        self.assertEqual(
            mapping["Right.hu"],
            {
                "tvg_id": "Legacy.hu@SD",
                "method": "external_explicit_alias",
            },
        )
        self.assertNotIn("Wrong.hu", mapping)

    def test_missing_historical_alias_is_ignored_safely(self):
        external = ET.fromstring(
            '<tv><channel id="Present.hu"><display-name>Present</display-name></channel></tv>'
        )
        mapping, ambiguous = build_external_mapping(
            [("PresentTarget.hu@SD", "Present")],
            external,
            explicit_aliases={
                "OldTarget.hu@SD": "Gone.hu",
            },
        )
        self.assertEqual(ambiguous, [])
        self.assertEqual(
            mapping["Present.hu"]["tvg_id"],
            "PresentTarget.hu@SD",
        )

    def test_alias_file_provider_must_match(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "aliases.json"
            path.write_text(
                json.dumps({
                    "provider": "wrong.example",
                    "aliases": {"A.hu": "B.hu"},
                }),
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                load_external_aliases(
                    path,
                    "epgshare01.online",
                )

    def test_alias_can_supply_fresh_programmes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            playlist = root / "tv.m3u"
            iptv = root / "iptv.xml"
            coverage = root / "iptv.json"
            external = root / "external.xml"
            output = root / "guide.xml"
            report = root / "coverage.json"

            playlist.write_text(
                '#EXTM3U\n#EXTINF:-1 tvg-id="FilmCafe.hu@Hungary",Film Cafe\nhttps://example.test/film.m3u8\n',
                encoding="utf-8",
            )
            iptv.write_text('<tv></tv>', encoding="utf-8")
            coverage.write_text(
                json.dumps({"matched": []}),
                encoding="utf-8",
            )
            external.write_text(
                '''<tv>
                <channel id="Film.Café.hu"><display-name>Film Café</display-name></channel>
                <programme start="20260811100000 +0200" stop="20260811110000 +0200" channel="Film.Café.hu"><title>Film</title></programme>
                </tv>''',
                encoding="utf-8",
            )

            result = merge_guides(
                playlist_path=playlist,
                iptv_guide_path=iptv,
                iptv_coverage_path=coverage,
                external_path=external,
                external_aliases={
                    "FilmCafe.hu@Hungary": "Film.Café.hu",
                },
                output_path=output,
                report_path=report,
                reference_date=date(2026, 8, 11),
            )

            match = result["matched"][0]
            self.assertEqual(
                match["match_type"],
                "external_explicit_alias",
            )
            self.assertEqual(match["fresh_programmes"], 1)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

print("Patched explicit EPG aliases, safe canonical IDs, audit identity, and tests.")
