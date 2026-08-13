#!/usr/bin/env python3
"""One-off mechanical extraction of playback-status helpers from build_core.py."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "iptv" / "build_core.py"
TARGET_PATH = ROOT / "iptv" / "playback_status.py"
TEST_PATH = ROOT / "tests" / "test_playback_status_refactor.py"
DOCS_PATH = ROOT / "docs" / "build-structure.md"

MOVED_FUNCTIONS = (
    "normalize_test_status",
    "is_tested_status",
)


def extract_functions(source: str) -> tuple[str, str]:
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    selected: list[ast.AST] = []
    found: set[str] = set()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in MOVED_FUNCTIONS:
            selected.append(node)
            found.add(node.name)

    missing = sorted(set(MOVED_FUNCTIONS) - found)
    if missing:
        raise RuntimeError(f"Refactor markers changed. Missing functions: {missing}")

    extracted_parts: list[str] = []
    remove_lines: set[int] = set()
    for node in sorted(selected, key=lambda item: item.lineno):
        if node.end_lineno is None:
            raise RuntimeError(f"AST node has no end line: {node!r}")
        start = node.lineno - 1
        end = node.end_lineno
        extracted_parts.append("".join(lines[start:end]).strip() + "\n")
        remove_lines.update(range(start, end))

    remaining = "".join(line for index, line in enumerate(lines) if index not in remove_lines)
    import_block = "from iptv.playback_status import (\n" + "".join(
        f"    {name},\n" for name in MOVED_FUNCTIONS
    ) + ")\n"
    marker = "from iptv.reports import (\n"
    if marker not in remaining:
        raise RuntimeError("Could not find playback-status import insertion marker.")
    remaining = remaining.replace(marker, import_block + marker, 1)

    module_header = '''#!/usr/bin/env python3
"""Shared VLC/Samsung playback-status normalization for Tomas IPTV.

This deliberately tiny module prevents language-routing and audit code from
having to import each other just to interpret manual playback test values.
"""
from __future__ import annotations

'''
    extracted = module_header + "\n".join(extracted_parts).rstrip() + "\n"
    ast.parse(remaining)
    ast.parse(extracted)

    remaining_tree = ast.parse(remaining)
    residual = {
        node.name
        for node in remaining_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in MOVED_FUNCTIONS
    }
    if residual:
        raise RuntimeError(f"Extraction left duplicate definitions: {sorted(residual)}")
    return remaining, extracted


def write_tests() -> None:
    TEST_PATH.write_text(
        f'''import unittest
from pathlib import Path

import build
from iptv import playback_status


EXTRACTED_NAMES = {repr(MOVED_FUNCTIONS)}


class PlaybackStatusRefactorTests(unittest.TestCase):
    def test_build_reexports_status_api(self):
        for name in EXTRACTED_NAMES:
            self.assertIs(getattr(build, name), getattr(playback_status, name), name)

    def test_build_core_no_longer_defines_status_helpers(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        for name in EXTRACTED_NAMES:
            self.assertNotIn(f"def {{name}}(", text, name)

    def test_normalization_and_tested_state_match_existing_contract(self):
        self.assertEqual(playback_status.normalize_test_status("Works with warning"), "works_with_warning")
        self.assertEqual(playback_status.normalize_test_status("MRL error"), "mrl_error")
        self.assertTrue(playback_status.is_tested_status("works"))
        self.assertTrue(playback_status.is_tested_status("format_error"))
        self.assertFalse(playback_status.is_tested_status("not_tested"))
        self.assertFalse(playback_status.is_tested_status(""))


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )


def update_docs() -> None:
    text = DOCS_PATH.read_text(encoding="utf-8")
    marker = "- `reports.py` — country/language build summaries and CSV export helpers\n"
    addition = marker + "- `playback_status.py` — shared VLC/Samsung manual-test status normalization\n"
    if marker not in text:
        raise RuntimeError("Could not find build-structure playback-status marker.")
    DOCS_PATH.write_text(text.replace(marker, addition, 1), encoding="utf-8")


def main() -> None:
    if TARGET_PATH.exists():
        raise RuntimeError(f"Target already exists: {TARGET_PATH}")
    source = CORE_PATH.read_text(encoding="utf-8")
    original_size = len(source.encode("utf-8"))
    remaining, extracted = extract_functions(source)
    new_size = len(remaining.encode("utf-8"))
    CORE_PATH.write_text(remaining, encoding="utf-8")
    TARGET_PATH.write_text(extracted, encoding="utf-8")
    write_tests()
    update_docs()
    print(
        "Extracted playback status subsystem: "
        f"build_core.py {original_size:,} -> {new_size:,} bytes; "
        f"new module {len(extracted.encode('utf-8')):,} bytes."
    )


if __name__ == "__main__":
    main()
