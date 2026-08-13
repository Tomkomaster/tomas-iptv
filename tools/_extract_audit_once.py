#!/usr/bin/env python3
"""One-off mechanical extraction of audit logic from build_core.py."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "iptv" / "build_core.py"
AUDIT_PATH = ROOT / "iptv" / "audit.py"
SOURCE_LOADER_PATH = ROOT / "iptv" / "source_loader.py"
TEST_PATH = ROOT / "tests" / "test_audit_refactor.py"
DOCS_PATH = ROOT / "docs" / "build-structure.md"

EXPLICIT_FUNCTIONS = {
    "calculate_audit_decision",
    "infer_protocol",
    "canonical_audit_name",
    "normalize_audit_decision_token",
    "exact_url_audit_matches_entry",
    "validate_audit_items",
    "prepare_audit_rows",
}


def assigned_names(node: ast.AST) -> set[str]:
    if not isinstance(node, (ast.Assign, ast.AnnAssign)):
        return set()
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return {target.id for target in targets if isinstance(target, ast.Name)}


def main() -> None:
    core = CORE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(core)
    lines = core.splitlines(keepends=True)

    moved_functions: list[str] = []
    selected: list[ast.AST] = []
    source_flag_node: ast.AST | None = None

    for node in tree.body:
        if "SOURCE_FLAG_RE" in assigned_names(node):
            source_flag_node = node
            continue
        if isinstance(node, ast.FunctionDef):
            if node.name in EXPLICIT_FUNCTIONS or node.name.startswith("audit_"):
                selected.append(node)
                moved_functions.append(node.name)

    required = EXPLICIT_FUNCTIONS | {
        "audit_status_is_recognized",
        "audit_excluded",
        "audit_match_key",
        "audit_rows_by_stream_url",
    }
    missing = sorted(required - set(moved_functions))
    if missing:
        raise RuntimeError(f"Audit extraction markers changed; missing: {missing}")
    if source_flag_node is None or source_flag_node.end_lineno is None:
        raise RuntimeError("SOURCE_FLAG_RE was not found")

    remove_lines: set[int] = set()
    extracted_parts: list[str] = []
    for node in sorted(selected, key=lambda item: item.lineno):
        if node.end_lineno is None:
            raise RuntimeError(f"AST node has no end line: {node!r}")
        start = node.lineno - 1
        end = node.end_lineno
        extracted_parts.append("".join(lines[start:end]).strip() + "\n")
        remove_lines.update(range(start, end))

    # Move SOURCE_FLAG_RE into source_loader so both audit and any remaining
    # build logic can depend on the low-level source metadata module.
    flag_source = "".join(
        lines[source_flag_node.lineno - 1:source_flag_node.end_lineno]
    ).strip()
    remove_lines.update(range(source_flag_node.lineno - 1, source_flag_node.end_lineno))

    remaining = "".join(
        line for index, line in enumerate(lines) if index not in remove_lines
    )

    source_loader = SOURCE_LOADER_PATH.read_text(encoding="utf-8")
    if "SOURCE_FLAG_RE =" in source_loader:
        raise RuntimeError("SOURCE_FLAG_RE already exists in source_loader.py")
    attr_marker = "ATTR_RE = re.compile(r'([A-Za-z0-9_-]+)=\"([^\"]*)\"')\n"
    if attr_marker not in source_loader:
        raise RuntimeError("source_loader ATTR_RE marker was not found")
    source_loader = source_loader.replace(
        attr_marker,
        attr_marker + flag_source + "\n",
        1,
    )

    audit_import = "from iptv.audit import (\n" + "".join(
        f"    {name},\n" for name in moved_functions
    ) + ")\n"
    marker = "from iptv.language_routing import (\n"
    if marker not in remaining:
        raise RuntimeError("build_core audit import insertion marker was not found")
    remaining = remaining.replace(marker, audit_import + marker, 1)

    # Preserve SOURCE_FLAG_RE as part of the historical build API if anything
    # external imports it, while changing ownership to source_loader.py.
    remaining = remaining.replace(
        "from iptv.playback_status import (\n",
        "from iptv.source_loader import SOURCE_FLAG_RE\nfrom iptv.playback_status import (\n",
        1,
    )

    audit_header = '''#!/usr/bin/env python3
"""Manual playback audit validation, decisions and history preparation.

This module owns the policy that turns saved VLC/Samsung tests into audit
states and attaches that history to current stream identities. Filesystem
loading remains in build_core so this subsystem stays independent of build
root/path state.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from country_language import (
    configured_country_codes,
    normalize_country_code,
    normalize_language_codes as normalize_spoken_language_codes,
)
from iptv.channel_identity import (
    canonical_stream_url,
    logical_channel_key,
    normalize_text,
    normalized_tvg_id,
    strip_display_annotations,
)
from iptv.language_routing import (
    audit_playlist_country_code,
    audit_playlist_scope_code,
    derive_language_match,
    format_language_codes,
    language_acceptance_state,
    language_mismatch_reason,
    normalize_language_codes,
    normalize_language_match,
    resolve_language_info,
    verified_output_country_code,
    verified_output_language_code,
)
from iptv.playback_status import normalize_test_status
from iptv.source_loader import SOURCE_FLAG_RE

'''
    audit_module = audit_header + "\n".join(extracted_parts).rstrip() + "\n"

    ast.parse(remaining)
    ast.parse(source_loader)
    ast.parse(audit_module)

    # Ensure no moved audit definitions remain in the core.
    remaining_tree = ast.parse(remaining)
    duplicates = [
        node.name for node in remaining_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in moved_functions
    ]
    if duplicates:
        raise RuntimeError(f"Audit definitions remained in core: {duplicates}")

    CORE_PATH.write_text(remaining, encoding="utf-8")
    SOURCE_LOADER_PATH.write_text(source_loader, encoding="utf-8")
    AUDIT_PATH.write_text(audit_module, encoding="utf-8")

    TEST_PATH.write_text(
        f'''import unittest
from pathlib import Path

import build
from iptv import audit


MOVED_FUNCTIONS = {tuple(moved_functions)!r}


class AuditRefactorTests(unittest.TestCase):
    def test_build_reexports_audit_api(self):
        for name in MOVED_FUNCTIONS:
            self.assertIs(getattr(build, name), getattr(audit, name), name)

    def test_build_core_no_longer_defines_audit_logic(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        for name in MOVED_FUNCTIONS:
            self.assertNotIn(f"def {{name}}(", text, name)
        self.assertLess(Path("iptv/build_core.py").stat().st_size, 95_000)

    def test_audit_decision_contract(self):
        verified = {{
            "vlc": "works",
            "samsung": "works",
            "expected_language_codes": ["hun"],
            "observed_language_codes": ["hun"],
            "decision": "auto",
        }}
        decision, reason = audit.calculate_audit_decision(verified, ["hun"])
        self.assertEqual(decision, "Verified")
        self.assertEqual(reason, "")

        pc_only = dict(verified, samsung="format_error")
        decision, _ = audit.calculate_audit_decision(pc_only, ["hun"])
        self.assertEqual(decision, "PC only")

    def test_exclude_flag_requires_real_boolean(self):
        self.assertTrue(audit.audit_excluded({{"exclude_from_playlist": True}}))
        self.assertFalse(audit.audit_excluded({{"exclude_from_playlist": "true"}}))


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )

    docs = DOCS_PATH.read_text(encoding="utf-8")
    docs_marker = "- `language_routing.py` — spoken-language interpretation and explicit publication-country routing\n"
    if docs_marker not in docs:
        raise RuntimeError("build-structure audit marker was not found")
    DOCS_PATH.write_text(
        docs.replace(
            docs_marker,
            docs_marker + "- `audit.py` — manual playback audit validation, decisions and stream-history preparation\n",
            1,
        ),
        encoding="utf-8",
    )

    print("Moved audit functions:", ", ".join(moved_functions))
    print(f"build_core.py after audit extraction: {CORE_PATH.stat().st_size:,} bytes")
    print(f"audit.py: {AUDIT_PATH.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
