#!/usr/bin/env python3
"""One-off mechanical extraction of channel identity helpers from build_core.py."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "iptv" / "build_core.py"
TARGET_PATH = ROOT / "iptv" / "channel_identity.py"
TEST_PATH = ROOT / "tests" / "test_channel_identity_refactor.py"
DOCS_PATH = ROOT / "docs" / "build-structure.md"

MOVED_CONSTANTS = (
    "QUALITY_SUFFIX_RE",
    "TVG_VARIANT_SUFFIX_RE",
    "CUSTOM_PREFIX_RE",
    "INTERNAL_PROVIDER_TEST_SUFFIX_RE",
)

MOVED_FUNCTIONS = (
    "split_display_annotations",
    "deduplicate_identical_annotations",
    "collapse_duplicate_quality_suffixes",
    "published_display_from_canonical",
    "strip_display_annotations",
    "normalize_text",
    "strip_internal_candidate_annotations",
    "normalized_tvg_id",
    "canonical_stream_url",
    "apply_canonical_identity",
    "channel_key",
    "strip_custom_prefix",
)

IMPORT_NAMES = (*MOVED_CONSTANTS, *MOVED_FUNCTIONS)


def assigned_names(node: ast.AST) -> set[str]:
    if not isinstance(node, (ast.Assign, ast.AnnAssign)):
        return set()
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names: set[str] = set()
    for target in targets:
        if isinstance(target, ast.Name):
            names.add(target.id)
    return names


def extract_nodes(source: str) -> tuple[str, str]:
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    selected: list[ast.AST] = []
    found_constants: set[str] = set()
    found_functions: set[str] = set()

    for node in tree.body:
        names = assigned_names(node)
        matching_constants = names.intersection(MOVED_CONSTANTS)
        if matching_constants:
            selected.append(node)
            found_constants.update(matching_constants)
            continue

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in MOVED_FUNCTIONS:
            selected.append(node)
            found_functions.add(node.name)

    missing_constants = sorted(set(MOVED_CONSTANTS) - found_constants)
    missing_functions = sorted(set(MOVED_FUNCTIONS) - found_functions)
    if missing_constants or missing_functions:
        raise RuntimeError(
            "Refactor markers changed. Missing constants/functions: "
            f"constants={missing_constants}, functions={missing_functions}"
        )

    extracted_parts: list[str] = []
    remove_lines: set[int] = set()
    for node in sorted(selected, key=lambda item: item.lineno):
        if node.end_lineno is None:
            raise RuntimeError(f"AST node has no end line: {node!r}")
        start = node.lineno - 1
        end = node.end_lineno
        extracted_parts.append("".join(lines[start:end]).strip() + "\n")
        remove_lines.update(range(start, end))

    remaining = "".join(
        line for index, line in enumerate(lines) if index not in remove_lines
    )

    # Imports used only by the extracted identity subsystem.
    remaining = remaining.replace("import unicodedata\n", "", 1)
    remaining = remaining.replace(
        "from urllib.parse import urlparse, urlunparse\n",
        "from urllib.parse import urlparse\n",
        1,
    )

    import_block = "from iptv.channel_identity import (\n" + "".join(
        f"    {name},\n" for name in IMPORT_NAMES
    ) + ")\n"
    marker = "from dashboard import copy_dashboard_assets, render_dashboard\n"
    if marker not in remaining:
        raise RuntimeError("Could not find build_core import insertion marker.")
    remaining = remaining.replace(marker, import_block + marker, 1)

    module_header = '''#!/usr/bin/env python3
"""Canonical channel identity and display-name helpers for Tomas IPTV.

This module is intentionally build-state free. It owns logical channel identity,
stream-URL identity normalization, safe display-name cleanup and application of
already-resolved canonical metadata. Selector resolution itself remains in
``identity_overrides.py``.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse, urlunparse

from iptv.source_loader import split_extinf

'''
    extracted = module_header + "\n".join(extracted_parts).rstrip() + "\n"

    # Parse both products before touching the working tree.
    ast.parse(remaining)
    ast.parse(extracted)

    remaining_tree = ast.parse(remaining)
    residual_functions = {
        node.name
        for node in remaining_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in MOVED_FUNCTIONS
    }
    residual_constants: set[str] = set()
    for node in remaining_tree.body:
        residual_constants.update(assigned_names(node).intersection(MOVED_CONSTANTS))
    if residual_functions or residual_constants:
        raise RuntimeError(
            f"Extraction left duplicate definitions: functions={sorted(residual_functions)}, "
            f"constants={sorted(residual_constants)}"
        )

    return remaining, extracted


def write_tests() -> None:
    names_repr = repr(IMPORT_NAMES)
    TEST_PATH.write_text(
        f'''import unittest
from pathlib import Path

import build
from iptv import channel_identity


EXTRACTED_NAMES = {names_repr}


class ChannelIdentityRefactorTests(unittest.TestCase):
    def test_build_reexports_extracted_identity_api(self):
        for name in EXTRACTED_NAMES:
            self.assertIs(getattr(build, name), getattr(channel_identity, name), name)

    def test_build_core_no_longer_defines_identity_helpers(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        for name in {repr(MOVED_FUNCTIONS)}:
            self.assertNotIn(f"def {{name}}(", text, name)
        self.assertLess(Path("iptv/build_core.py").stat().st_size, 142_000)

    def test_stream_and_channel_identity_behavior(self):
        self.assertEqual(
            channel_identity.canonical_stream_url(
                "HTTPS://Example.COM:443/live.m3u8#fragment"
            ),
            "https://example.com/live.m3u8",
        )
        self.assertEqual(channel_identity.normalized_tvg_id("Demo.hu@HD"), "demo.hu")
        self.assertEqual(
            channel_identity.normalized_tvg_id("ducktv.sk@HD"),
            "ducktvhd.sk",
        )
        self.assertEqual(
            channel_identity.channel_key({{"canonical_id": "Demo.Channel"}}),
            "canonical:demo.channel",
        )

    def test_display_cleanup_behavior(self):
        self.assertEqual(
            channel_identity.collapse_duplicate_quality_suffixes(
                "Demo TV (1080p) (1080p)"
            ),
            "Demo TV (1080p)",
        )
        self.assertEqual(
            channel_identity.strip_internal_candidate_annotations(
                "JOJ Šport 2 ANTIK TEST"
            ),
            "JOJ Šport 2",
        )


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )


def update_docs() -> None:
    text = DOCS_PATH.read_text(encoding="utf-8")
    old = (
        "- `build_core.py` — transitional remainder of the historical monolithic builder\n"
        "- `source_loader.py` — source definitions, remote/local loading and M3U parsing\n"
    )
    new = (
        "- `build_core.py` — transitional build orchestration and remaining coupled subsystems\n"
        "- `channel_identity.py` — logical channel identity, canonical stream URLs and safe display-name normalization\n"
        "- `source_loader.py` — source definitions, remote/local loading and M3U parsing\n"
    )
    if old not in text:
        raise RuntimeError("Could not find build-structure module list marker.")
    text = text.replace(old, new, 1)

    old_note = (
        "The large `build_core.py` is not the final architecture. It is a compatibility bridge "
        "that lets responsibilities be extracted one tested unit at a time instead of rewriting "
        "the builder in one risky change."
    )
    new_note = (
        "The large `build_core.py` is not the final architecture. It is a compatibility bridge "
        "that lets responsibilities be extracted one tested unit at a time instead of rewriting "
        "the builder in one risky change. Channel identity/name normalization is now one of those "
        "extracted units; audit, routing and stable selection remain the larger coupled blocks."
    )
    if old_note not in text:
        raise RuntimeError("Could not find build-structure extraction note.")
    DOCS_PATH.write_text(text.replace(old_note, new_note, 1), encoding="utf-8")


def main() -> None:
    if TARGET_PATH.exists():
        raise RuntimeError(f"Target already exists: {TARGET_PATH}")

    source = CORE_PATH.read_text(encoding="utf-8")
    original_size = len(source.encode("utf-8"))
    remaining, extracted = extract_nodes(source)
    new_size = len(remaining.encode("utf-8"))

    if new_size >= original_size:
        raise RuntimeError(
            f"build_core.py did not shrink: before={original_size}, after={new_size}"
        )

    CORE_PATH.write_text(remaining, encoding="utf-8")
    TARGET_PATH.write_text(extracted, encoding="utf-8")
    write_tests()
    update_docs()

    print(
        "Extracted channel identity subsystem: "
        f"build_core.py {original_size:,} -> {new_size:,} bytes; "
        f"new module {len(extracted.encode('utf-8')):,} bytes."
    )


if __name__ == "__main__":
    main()
