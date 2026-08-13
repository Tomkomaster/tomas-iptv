#!/usr/bin/env python3
"""Remove build_core implementations already owned by extracted modules."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "iptv" / "build_core.py"
TEST = ROOT / "tests" / "test_core_duplicate_cleanup.py"
DOCS = ROOT / "docs" / "build-structure.md"

REMOVE_FUNCTIONS = {
    "http_get_text",
    "download_m3u",
    "playlist_header",
    "split_extinf",
    "parse_entries",
    "normalize_source_kind",
    "source_spec",
    "write_m3u_playlist",
}
REMOVE_CONSTANTS = {"ATTR_RE", "VALID_SOURCE_KINDS"}


def assigned_names(node: ast.AST) -> set[str]:
    if not isinstance(node, (ast.Assign, ast.AnnAssign)):
        return set()
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return {target.id for target in targets if isinstance(target, ast.Name)}


def main() -> None:
    source = CORE.read_text(encoding="utf-8")
    before = len(source.encode("utf-8"))
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)

    selected: list[ast.AST] = []
    found_functions: set[str] = set()
    found_constants: set[str] = set()
    for node in tree.body:
        constants = assigned_names(node).intersection(REMOVE_CONSTANTS)
        if constants:
            selected.append(node)
            found_constants.update(constants)
            continue
        if isinstance(node, ast.FunctionDef) and node.name in REMOVE_FUNCTIONS:
            selected.append(node)
            found_functions.add(node.name)

    if found_functions != REMOVE_FUNCTIONS:
        raise RuntimeError(f"Function markers changed: {sorted(REMOVE_FUNCTIONS - found_functions)}")
    if found_constants != REMOVE_CONSTANTS:
        raise RuntimeError(f"Constant markers changed: {sorted(REMOVE_CONSTANTS - found_constants)}")

    remove_lines: set[int] = set()
    for node in selected:
        if node.end_lineno is None:
            raise RuntimeError(f"AST node has no end line: {node!r}")
        remove_lines.update(range(node.lineno - 1, node.end_lineno))
    remaining = "".join(line for i, line in enumerate(lines) if i not in remove_lines)

    # Core now imports the canonical implementations instead of carrying stale copies.
    old = "from iptv.source_loader import SOURCE_FLAG_RE\n"
    new = '''from iptv.source_loader import (
    ATTR_RE,
    SOURCE_FLAG_RE,
    VALID_SOURCE_KINDS,
    http_get_text,
    download_m3u,
    split_extinf,
    parse_entries,
    normalize_source_kind,
    source_spec,
)
from iptv.playlist_writer import playlist_header
from iptv.playlist_writer import write_m3u_playlist as _write_m3u_playlist
'''
    if old not in remaining:
        raise RuntimeError("source_loader import marker missing")
    remaining = remaining.replace(old, new, 1)

    # Keep the historical call signature in build_core while delegating the body.
    wrapper = '''\n\ndef write_m3u_playlist(
    path: Path,
    cfg: dict,
    entries: list[dict],
    generated: str,
    playlist_label: str,
    name_style: str = "status",
) -> None:
    """Compatibility wrapper around the extracted playlist writer."""
    return _write_m3u_playlist(
        path,
        cfg,
        entries,
        generated,
        playlist_label,
        name_style=name_style,
        strip_custom_prefix=strip_custom_prefix,
        normalize_country_code=normalize_country_code,
        rewrite_entry_lines=rewrite_entry_lines,
    )
'''
    insertion = "def make_dashboard(\n"
    if insertion not in remaining:
        raise RuntimeError("dashboard insertion marker missing")
    remaining = remaining.replace(insertion, wrapper + "\n" + insertion, 1)

    # urllib.request was only used by the duplicate downloader.
    remaining = remaining.replace("import urllib.request\n", "", 1)
    ast.parse(remaining)
    CORE.write_text(remaining, encoding="utf-8")

    TEST.write_text(
        '''import unittest
from pathlib import Path

import build
from iptv import playlist_writer, source_loader


class CoreDuplicateCleanupTests(unittest.TestCase):
    def test_source_helpers_are_not_redefined_in_core(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        for name in (
            "http_get_text", "download_m3u", "split_extinf", "parse_entries",
            "normalize_source_kind", "source_spec", "playlist_header",
        ):
            self.assertNotIn(f"def {name}(", text, name)

    def test_build_uses_canonical_source_helpers(self):
        self.assertIs(build.http_get_text, source_loader.http_get_text)
        self.assertIs(build.download_m3u, source_loader.download_m3u)
        self.assertIs(build.split_extinf, source_loader.split_extinf)
        self.assertIs(build.parse_entries, source_loader.parse_entries)
        self.assertIs(build.normalize_source_kind, source_loader.normalize_source_kind)
        self.assertIs(build.source_spec, source_loader.source_spec)
        self.assertIs(build.playlist_header, playlist_writer.playlist_header)

    def test_playlist_writer_core_copy_is_only_a_wrapper(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        self.assertEqual(text.count("def write_m3u_playlist("), 1)
        self.assertIn("return _write_m3u_playlist(", text)
        self.assertNotIn("# Tomas IPTV smart builder v19", text)


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )

    docs = DOCS.read_text(encoding="utf-8")
    marker = "- `source_loader.py` — source definitions, remote/local loading and M3U parsing\n"
    replacement = (
        "- `source_loader.py` — source definitions, remote/local loading and M3U parsing; "
        "`build_core.py` no longer carries duplicate parser/downloader implementations\n"
    )
    if marker not in docs:
        raise RuntimeError("docs source_loader marker missing")
    DOCS.write_text(docs.replace(marker, replacement, 1), encoding="utf-8")

    after = CORE.stat().st_size
    print(f"Removed extracted-module duplicates: build_core.py {before:,} -> {after:,} bytes")


if __name__ == "__main__":
    main()
