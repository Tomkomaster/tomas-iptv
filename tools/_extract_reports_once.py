#!/usr/bin/env python3
"""One-off mechanical extraction of pure reporting helpers from build_core.py."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "iptv" / "build_core.py"
TARGET_PATH = ROOT / "iptv" / "reports.py"
TEST_PATH = ROOT / "tests" / "test_reports_refactor.py"
DOCS_PATH = ROOT / "docs" / "build-structure.md"

MOVED_FUNCTIONS = (
    "summarize_country_stats",
    "summarize_language_stats",
    "safe_csv_value",
    "write_csv",
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

    remaining = "".join(
        line for index, line in enumerate(lines) if index not in remove_lines
    )

    import_block = "from iptv.reports import (\n" + "".join(
        f"    {name},\n" for name in MOVED_FUNCTIONS
    ) + ")\n"
    marker = "from iptv.channel_identity import (\n"
    if marker not in remaining:
        raise RuntimeError("Could not find report import insertion marker.")
    remaining = remaining.replace(marker, import_block + marker, 1)

    module_header = '''#!/usr/bin/env python3
"""Build summary and CSV export helpers for Tomas IPTV.

These functions are intentionally free of build orchestration state. They turn
already-prepared entries/source metadata into country/language summaries and
write deterministic CSV exports.
"""
from __future__ import annotations

import csv
from pathlib import Path

from country_language import (
    normalize_country_code,
    normalize_language_codes as normalize_spoken_language_codes,
)

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

    # csv is now owned by reports.py unless another core function still needs it.
    csv_used = any(
        isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == "csv"
        for node in ast.walk(remaining_tree)
    )
    if not csv_used:
        remaining = remaining.replace("import csv\n", "", 1)
        ast.parse(remaining)

    return remaining, extracted


def write_tests() -> None:
    TEST_PATH.write_text(
        f'''import csv
import tempfile
import unittest
from pathlib import Path

import build
from iptv import reports


EXTRACTED_NAMES = {repr(MOVED_FUNCTIONS)}


class ReportsRefactorTests(unittest.TestCase):
    def test_build_reexports_reports_api(self):
        for name in EXTRACTED_NAMES:
            self.assertIs(getattr(build, name), getattr(reports, name), name)

    def test_build_core_no_longer_defines_report_helpers(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        for name in EXTRACTED_NAMES:
            self.assertNotIn(f"def {{name}}(", text, name)

    def test_country_and_language_summaries(self):
        entries = [
            {{
                "country_code": "HU",
                "language_codes": ["hun"],
                "channel_key": "id:alpha.hu",
                "classification": "Base channel",
            }},
            {{
                "country_code": "HU",
                "language_codes": ["hun"],
                "channel_key": "id:beta.hu",
                "classification": "Added channel",
            }},
        ]
        sources = [
            {{"country_code": "HU", "language_codes": ["hun"], "kind": "base"}},
            {{"country_code": "HU", "language_codes": ["hun"], "kind": "extras"}},
        ]
        country = reports.summarize_country_stats(entries, sources)[0]
        language = reports.summarize_language_stats(entries, sources)[0]
        self.assertEqual(country["country_code"], "HU")
        self.assertEqual(country["unique_channels"], 2)
        self.assertEqual(country["base_channels"], 1)
        self.assertEqual(country["added_channels"], 1)
        self.assertEqual(language["language_code"], "hun")
        self.assertEqual(language["unique_channels"], 2)

    def test_write_csv_sanitizes_newlines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            reports.write_csv(path, ["name", "note"], [{{"name": "Demo", "note": "a\\nb"}}])
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        self.assertEqual(rows, [{{"name": "Demo", "note": "a b"}}])


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )


def update_docs() -> None:
    text = DOCS_PATH.read_text(encoding="utf-8")
    marker = "- `playlist_writer.py` — generated M3U headers and playlist writing\n"
    addition = marker + "- `reports.py` — country/language build summaries and CSV export helpers\n"
    if marker not in text:
        raise RuntimeError("Could not find build-structure reports marker.")
    text = text.replace(marker, addition, 1)
    DOCS_PATH.write_text(text, encoding="utf-8")


def main() -> None:
    if TARGET_PATH.exists():
        raise RuntimeError(f"Target already exists: {TARGET_PATH}")

    source = CORE_PATH.read_text(encoding="utf-8")
    original_size = len(source.encode("utf-8"))
    remaining, extracted = extract_functions(source)
    new_size = len(remaining.encode("utf-8"))

    if new_size >= original_size - 3_000:
        raise RuntimeError(
            "build_core.py did not shrink by the expected amount: "
            f"before={original_size}, after={new_size}"
        )

    CORE_PATH.write_text(remaining, encoding="utf-8")
    TARGET_PATH.write_text(extracted, encoding="utf-8")
    write_tests()
    update_docs()

    print(
        "Extracted reports subsystem: "
        f"build_core.py {original_size:,} -> {new_size:,} bytes; "
        f"new module {len(extracted.encode('utf-8')):,} bytes."
    )


if __name__ == "__main__":
    main()
