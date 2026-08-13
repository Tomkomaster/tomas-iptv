#!/usr/bin/env python3
"""One-off mechanical extraction of publication/name rewriting from build_core.py."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "iptv" / "build_core.py"
TARGET = ROOT / "iptv" / "publication.py"
TEST = ROOT / "tests" / "test_publication_refactor.py"
DOCS = ROOT / "docs" / "build-structure.md"

NAMES = (
    "normalize_content_group",
    "rewrite_extinf_line",
    "rewrite_entry_lines",
    "playlist_status_suffix",
    "prepare_published_entries",
)


def main() -> None:
    source = CORE.read_text(encoding="utf-8")
    before = len(source.encode("utf-8"))
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    nodes = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in NAMES
    }
    if set(nodes) != set(NAMES):
        raise RuntimeError(f"Publication markers changed: {sorted(set(NAMES) - set(nodes))}")

    remove_lines: set[int] = set()
    parts: list[str] = []
    for name in NAMES:
        node = nodes[name]
        if node.end_lineno is None:
            raise RuntimeError(f"No end line for {name}")
        parts.append("".join(lines[node.lineno - 1:node.end_lineno]).strip() + "\n")
        remove_lines.update(range(node.lineno - 1, node.end_lineno))
    remaining = "".join(line for i, line in enumerate(lines) if i not in remove_lines)

    import_block = "from iptv.publication import (\n" + "".join(
        f"    {name},\n" for name in NAMES
    ) + ")\n"
    marker = "from iptv.stable_selection import stable_block_reason\n"
    if marker not in remaining:
        raise RuntimeError("stable selection import marker missing")
    remaining = remaining.replace(marker, import_block + marker, 1)

    module_header = '''#!/usr/bin/env python3
"""Published channel names, group titles and EXTINF rewriting.

Selection decides which streams survive; this module turns those already-selected
entries into final presentation metadata without owning filesystem/build state.
"""
from __future__ import annotations

import re

from country_language import normalize_country_code
from iptv.channel_identity import (
    logical_channel_key,
    normalize_text,
    published_display_from_canonical,
    strip_custom_prefix,
    strip_display_annotations,
    strip_internal_candidate_annotations,
)
from iptv.language_routing import country_name_for_code
from iptv.source_loader import split_extinf

'''
    module = module_header + "\n".join(parts).rstrip() + "\n"
    ast.parse(remaining)
    ast.parse(module)

    CORE.write_text(remaining, encoding="utf-8")
    TARGET.write_text(module, encoding="utf-8")

    TEST.write_text(
        f'''import unittest
from pathlib import Path

import build
from iptv import publication

MOVED = {NAMES!r}


class PublicationRefactorTests(unittest.TestCase):
    def test_build_reexports_publication_api(self):
        for name in MOVED:
            self.assertIs(getattr(build, name), getattr(publication, name), name)

    def test_core_no_longer_defines_publication_logic(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        for name in MOVED:
            self.assertNotIn(f"def {{name}}(", text, name)

    def test_group_normalization_stays_idempotent(self):
        self.assertEqual(
            publication.normalize_content_group(
                "Hungary | News", country_name="Hungary", language_code="HU"
            ),
            "News",
        )
        self.assertEqual(
            publication.normalize_content_group(
                "HU | Verified", country_name="Hungary", language_code="HU"
            ),
            "General",
        )

    def test_extinf_rewrite_cleans_internal_tvg_name(self):
        line = '#EXTINF:-1 tvg-name="JOJ Sport ANTIK TEST" group-title="Sports",JOJ Sport ANTIK TEST'
        result = publication.rewrite_extinf_line(line, "[SK OK] JOJ Sport", "Slovakia | Sports")
        self.assertIn('tvg-name="JOJ Sport"', result)
        self.assertIn('group-title="Slovakia | Sports"', result)
        self.assertTrue(result.endswith(",[SK OK] JOJ Sport"))

    def test_prepare_published_entries_numbers_alternative_feeds(self):
        entries = [
            {{
                "url": "https://example.test/a1.m3u8",
                "country_code": "HU",
                "country_name": "Hungary",
                "canonical_id": "demo",
                "channel_name": "Demo TV",
                "display_name": "Demo TV",
                "source_group_title": "News",
                "lines": ['#EXTINF:-1 group-title="News",Demo TV', "https://example.test/a1.m3u8"],
                "_decision": "Verified",
                "_source_order": 0,
            }},
            {{
                "url": "https://example.test/a2.m3u8",
                "country_code": "HU",
                "country_name": "Hungary",
                "canonical_id": "demo",
                "channel_name": "Demo TV",
                "display_name": "Demo TV",
                "source_group_title": "News",
                "lines": ['#EXTINF:-1 group-title="News",Demo TV', "https://example.test/a2.m3u8"],
                "_decision": "Verified",
                "_source_order": 1,
            }},
        ]
        out = publication.prepare_published_entries(entries, {{"country_names": {{"HU": "Hungary"}}}})
        self.assertEqual([item["published_name"] for item in out], ["[HU OK] Demo TV", "[HU OK] Demo TV Feed 2"])


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )

    docs = DOCS.read_text(encoding="utf-8")
    marker = "- `playlist_writer.py` — generated M3U headers and playlist writing\n"
    addition = marker + "- `publication.py` — published names, content groups and EXTINF metadata rewriting\n"
    if marker not in docs:
        raise RuntimeError("docs publication marker missing")
    DOCS.write_text(docs.replace(marker, addition, 1), encoding="utf-8")

    print(f"Extracted publication subsystem: build_core.py {before:,} -> {CORE.stat().st_size:,} bytes")
    print(f"publication.py: {TARGET.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
