#!/usr/bin/env python3
"""One-off mechanical extraction of language/country routing helpers."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "iptv" / "build_core.py"
TARGET_PATH = ROOT / "iptv" / "language_routing.py"
TEST_PATH = ROOT / "tests" / "test_language_routing_refactor.py"
DOCS_PATH = ROOT / "docs" / "build-structure.md"

MOVED_CONSTANTS = ("LANGUAGE_NAME_TO_CODE",)
MOVED_FUNCTIONS = (
    "normalize_language_code",
    "normalize_language_codes",
    "normalize_language_match",
    "legacy_language_is_negative",
    "derive_language_match",
    "resolve_language_info",
    "format_language_codes",
    "language_mismatch_reason",
    "configured_playlist_country_codes",
    "configured_playlist_language_codes",
    "configured_spoken_language_codes",
    "audit_playlist_country_code",
    "audit_playlist_scope_code",
    "verified_output_country_code",
    "verified_output_language_code",
    "language_acceptance_state",
)
IMPORT_NAMES = (*MOVED_CONSTANTS, *MOVED_FUNCTIONS)


def assigned_names(node: ast.AST) -> set[str]:
    if not isinstance(node, (ast.Assign, ast.AnnAssign)):
        return set()
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return {target.id for target in targets if isinstance(target, ast.Name)}


def extract_nodes(source: str) -> tuple[str, str]:
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    selected: list[ast.AST] = []
    found_constants: set[str] = set()
    found_functions: set[str] = set()

    for node in tree.body:
        constants = assigned_names(node).intersection(MOVED_CONSTANTS)
        if constants:
            selected.append(node)
            found_constants.update(constants)
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in MOVED_FUNCTIONS:
            selected.append(node)
            found_functions.add(node.name)

    missing_constants = sorted(set(MOVED_CONSTANTS) - found_constants)
    missing_functions = sorted(set(MOVED_FUNCTIONS) - found_functions)
    if missing_constants or missing_functions:
        raise RuntimeError(
            f"Refactor markers changed: constants={missing_constants}, functions={missing_functions}"
        )

    remove_lines: set[int] = set()
    extracted_parts: list[str] = []
    for node in sorted(selected, key=lambda item: item.lineno):
        if node.end_lineno is None:
            raise RuntimeError(f"AST node has no end line: {node!r}")
        start = node.lineno - 1
        end = node.end_lineno
        extracted_parts.append("".join(lines[start:end]).strip() + "\n")
        remove_lines.update(range(start, end))

    remaining = "".join(line for index, line in enumerate(lines) if index not in remove_lines)
    import_block = "from iptv.language_routing import (\n" + "".join(
        f"    {name},\n" for name in IMPORT_NAMES
    ) + ")\n"
    marker = "from iptv.playback_status import (\n"
    if marker not in remaining:
        raise RuntimeError("Could not find language-routing import insertion marker.")
    remaining = remaining.replace(marker, import_block + marker, 1)

    module_header = '''#!/usr/bin/env python3
"""Spoken-language interpretation and explicit publication-country routing.

Country identity and spoken language are intentionally separate. This module
contains the legacy audit-language compatibility layer plus the explicit rules
that can route a verified feed to another publication country.
"""
from __future__ import annotations

import re

from country_language import (
    configured_country_codes,
    configured_language_codes,
    legacy_country_scope_from_language_token,
    normalize_country_code,
    normalize_language_codes as normalize_spoken_language_codes,
    verified_country_route,
)
from iptv.playback_status import normalize_test_status

'''
    extracted = module_header + "\n".join(extracted_parts).rstrip() + "\n"
    ast.parse(remaining)
    ast.parse(extracted)

    remaining_tree = ast.parse(remaining)
    residual_functions = {
        node.name for node in remaining_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in MOVED_FUNCTIONS
    }
    residual_constants: set[str] = set()
    for node in remaining_tree.body:
        residual_constants.update(assigned_names(node).intersection(MOVED_CONSTANTS))
    if residual_functions or residual_constants:
        raise RuntimeError(
            f"Extraction left duplicates: functions={sorted(residual_functions)}, "
            f"constants={sorted(residual_constants)}"
        )
    return remaining, extracted


def write_tests() -> None:
    TEST_PATH.write_text(
        f'''import unittest
from pathlib import Path

import build
from iptv import language_routing


EXTRACTED_NAMES = {repr(IMPORT_NAMES)}
EXTRACTED_FUNCTIONS = {repr(MOVED_FUNCTIONS)}


class LanguageRoutingRefactorTests(unittest.TestCase):
    def test_build_reexports_language_routing_api(self):
        for name in EXTRACTED_NAMES:
            self.assertIs(getattr(build, name), getattr(language_routing, name), name)

    def test_build_core_no_longer_defines_language_helpers(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        for name in EXTRACTED_FUNCTIONS:
            self.assertNotIn(f"def {{name}}(", text, name)
        self.assertNotIn("LANGUAGE_NAME_TO_CODE =", text)

    def test_legacy_language_normalization_contract(self):
        self.assertEqual(language_routing.normalize_language_code("Hungarian"), "HU")
        self.assertEqual(language_routing.normalize_language_code("ces"), "CZ")
        self.assertEqual(language_routing.normalize_language_codes("Hungarian, Czech"), ["HU", "CZ"])
        self.assertEqual(language_routing.normalize_language_match("wrong language"), "no")

    def test_language_acceptance_is_separate_from_country_routing(self):
        item = {{
            "expected_language_codes": ["hun"],
            "observed_language_codes": ["ces"],
            "language_match": "no",
            "vlc": "works",
            "samsung": "works",
        }}
        self.assertEqual(
            language_routing.language_acceptance_state(item, ["hun", "ces"]),
            "supported_cross_language",
        )
        self.assertEqual(
            language_routing.verified_output_country_code(
                {{"decision": "Verified", "output_country_code": "CZ"}},
                "SK",
                {{"country_outputs": {{"SK": "sk.m3u", "CZ": "cz.m3u"}}}},
            ),
            "CZ",
        )

    def test_audit_scope_prefers_explicit_country(self):
        self.assertEqual(
            language_routing.audit_playlist_country_code(
                {{"playlist_country_code": "SK", "expected_language_codes": ["hun"]}}
            ),
            "SK",
        )


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )


def update_docs() -> None:
    text = DOCS_PATH.read_text(encoding="utf-8")
    marker = "- `playback_status.py` — shared VLC/Samsung manual-test status normalization\n"
    addition = marker + "- `language_routing.py` — spoken-language interpretation and explicit publication-country routing\n"
    if marker not in text:
        raise RuntimeError("Could not find build-structure language-routing marker.")
    DOCS_PATH.write_text(text.replace(marker, addition, 1), encoding="utf-8")


def main() -> None:
    if TARGET_PATH.exists():
        raise RuntimeError(f"Target already exists: {TARGET_PATH}")
    source = CORE_PATH.read_text(encoding="utf-8")
    original_size = len(source.encode("utf-8"))
    remaining, extracted = extract_nodes(source)
    new_size = len(remaining.encode("utf-8"))
    if new_size >= original_size - 8_000:
        raise RuntimeError(
            f"build_core.py did not shrink by expected amount: before={original_size}, after={new_size}"
        )
    CORE_PATH.write_text(remaining, encoding="utf-8")
    TARGET_PATH.write_text(extracted, encoding="utf-8")
    write_tests()
    update_docs()
    print(
        "Extracted language routing subsystem: "
        f"build_core.py {original_size:,} -> {new_size:,} bytes; "
        f"new module {len(extracted.encode('utf-8')):,} bytes."
    )


if __name__ == "__main__":
    main()
