#!/usr/bin/env python3
"""One-off extraction of source collection/global URL deduplication from build_core.py."""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "iptv" / "build_core.py"
TARGET = ROOT / "iptv" / "deduplication.py"
TEST = ROOT / "tests" / "test_deduplication_refactor.py"
DOCS = ROOT / "docs" / "build-structure.md"

START_MARKER = "    source_items: list[dict] = []\n"
END_MARKER = "    audit_warnings, audit_ambiguity_warnings = validate_audit_items(\n"


def extract_top_level_function(source: str, name: str) -> tuple[str, str]:
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    node = next(
        (item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name),
        None,
    )
    if node is None or node.end_lineno is None:
        raise RuntimeError(f"Could not find top-level function {name}")
    body = "".join(lines[node.lineno - 1:node.end_lineno]).strip() + "\n"
    remaining = "".join(
        line for index, line in enumerate(lines)
        if not (node.lineno - 1 <= index < node.end_lineno)
    )
    return remaining, body


def main() -> None:
    source = CORE.read_text(encoding="utf-8")
    before = len(source.encode("utf-8"))
    source, flag_function = extract_top_level_function(source, "extract_source_flags")

    start = source.find(START_MARKER)
    end = source.find(END_MARKER)
    if start < 0 or end < 0 or end <= start:
        raise RuntimeError("Source-ingestion block markers changed")

    raw_block = source[start:end]
    block = textwrap.dedent(raw_block)
    block = block.replace("download_m3u(", "remote_loader(")
    block = block.replace("read_local(", "local_loader(")

    call = '''    final_entries, language_only_entries, duplicate_rows, source_stats = collect_source_entries(
        cfg,
        identity_registry,
        supported_country_codes,
        remote_loader=download_m3u,
        local_loader=read_local,
    )

'''
    remaining = source[:start] + call + source[end:]

    import_block = '''from iptv.deduplication import (
    collect_source_entries,
    extract_source_flags,
)
'''
    marker = "from iptv.publication import (\n"
    if marker not in remaining:
        raise RuntimeError("publication import marker missing")
    remaining = remaining.replace(marker, import_block + marker, 1)

    function = '''def collect_source_entries(
    cfg: dict,
    identity_registry,
    supported_country_codes,
    *,
    remote_loader,
    local_loader,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Load configured sources and apply the project's global stream deduplication.

    Returns country-publication entries, language-only entries, ignored duplicate
    rows and per-source contribution statistics. Loaders are injected so build.py
    keeps its historical ROOT override and network monkeypatch behavior.
    """
''' + textwrap.indent(block, "    ") + '''
    return final_entries, language_only_entries, duplicate_rows, source_stats
'''

    module_header = '''#!/usr/bin/env python3
"""Source ingestion, canonical identity application and global URL deduplication."""
from __future__ import annotations

import sys

from country_language import (
    country_code_from_tvg_id,
    normalize_country_code,
    normalize_language_codes as normalize_spoken_language_codes,
    source_country_code,
    source_country_mode,
    source_language_codes,
)
from iptv.channel_identity import (
    apply_canonical_identity,
    canonical_stream_url,
    channel_key,
    logical_channel_key,
    strip_display_annotations,
    strip_internal_candidate_annotations,
)
from iptv.language_routing import country_name_for_code
from iptv.publication import normalize_content_group
from iptv.source_loader import (
    SOURCE_FLAG_RE,
    normalize_source_kind,
    parse_entries,
    source_spec,
)

'''
    module = module_header + flag_function + "\n\n" + function

    ast.parse(remaining)
    ast.parse(module)
    CORE.write_text(remaining, encoding="utf-8")
    TARGET.write_text(module, encoding="utf-8")

    TEST.write_text(
        '''import unittest
from pathlib import Path

import build
from identity_overrides import IdentityRegistry
from iptv import deduplication


class DeduplicationRefactorTests(unittest.TestCase):
    def test_build_reexports_source_flag_helper(self):
        self.assertIs(build.extract_source_flags, deduplication.extract_source_flags)

    def test_core_main_no_longer_owns_seen_url_loop(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        self.assertNotIn("seen_urls: dict[str, dict]", text)
        self.assertNotIn("for source_index, spec in enumerate(", text)
        self.assertIn("collect_source_entries(", text)

    def test_canonical_equivalent_urls_are_globally_deduplicated(self):
        cfg = {
            "country_outputs": {"HU": "public/hu.m3u"},
            "country_names": {"HU": "Hungary"},
            "sources": [
                {"name": "One", "path": "one.m3u", "kind": "base", "country_code": "HU", "language_codes": ["hun"]},
                {"name": "Two", "path": "two.m3u", "kind": "base", "country_code": "HU", "language_codes": ["hun"]},
            ],
        }
        playlists = {
            "one.m3u": """#EXTM3U
#EXTINF:-1 tvg-id="Demo.hu" group-title="News",Demo
https://example.test:443/live.m3u8
""",
            "two.m3u": """#EXTM3U
#EXTINF:-1 tvg-id="Demo.hu" group-title="News",Demo
https://example.test/live.m3u8
""",
        }
        registry = IdentityRegistry({"schema_version": 1, "identities": {}, "selectors": []})
        final_entries, language_only, duplicates, stats = deduplication.collect_source_entries(
            cfg,
            registry,
            {"HU"},
            remote_loader=lambda url: (_ for _ in ()).throw(AssertionError(url)),
            local_loader=lambda path: playlists[path],
        )
        self.assertEqual(len(final_entries), 1)
        self.assertEqual(language_only, [])
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(stats[1]["duplicate_urls_ignored"], 1)

    def test_source_flags_stay_normalized(self):
        self.assertEqual(
            deduplication.extract_source_flags("Demo [Geo-blocked] [Not 24/7]"),
            ["Geo-blocked", "Not 24/7"],
        )


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )

    docs = DOCS.read_text(encoding="utf-8")
    marker = "- `source_loader.py` — source definitions, remote/local loading and M3U parsing; `build_core.py` no longer carries duplicate parser/downloader implementations\n"
    addition = marker + "- `deduplication.py` — source collection, canonical identity application, global URL deduplication and source contribution stats\n"
    if marker not in docs:
        raise RuntimeError("docs source-loader marker missing")
    DOCS.write_text(docs.replace(marker, addition, 1), encoding="utf-8")

    print(f"Extracted source deduplication: build_core.py {before:,} -> {CORE.stat().st_size:,} bytes")
    print(f"deduplication.py: {TARGET.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
