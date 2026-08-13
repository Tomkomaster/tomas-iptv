#!/usr/bin/env python3
"""Move the remaining country/language routing helpers out of build_core.py."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "iptv" / "build_core.py"
TARGET = ROOT / "iptv" / "language_routing.py"
TEST = ROOT / "tests" / "test_language_routing_completion.py"
DOCS = ROOT / "docs" / "build-structure.md"

NAMES = (
    "country_name_for_code",
    "country_name_for_language",
    "route_candidates_to_verified_countries",
    "route_candidates_to_verified_languages",
    "build_language_catalog_entries",
    "entries_for_spoken_language",
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
        raise RuntimeError(f"Language routing markers changed: {sorted(set(NAMES) - set(nodes))}")

    remove_lines: set[int] = set()
    parts: list[str] = []
    for name in NAMES:
        node = nodes[name]
        if node.end_lineno is None:
            raise RuntimeError(f"No end line for {name}")
        parts.append("".join(lines[node.lineno - 1:node.end_lineno]).strip() + "\n")
        remove_lines.update(range(node.lineno - 1, node.end_lineno))
    remaining = "".join(line for i, line in enumerate(lines) if i not in remove_lines)

    # Re-export the moved helpers through the historical build API.
    marker = "from iptv.language_routing import (\n"
    if marker not in remaining:
        raise RuntimeError("language_routing import block missing")
    additions = "".join(f"    {name},\n" for name in NAMES)
    remaining = remaining.replace(marker, marker + additions, 1)

    target = TARGET.read_text(encoding="utf-8")
    if "normalize_language_code as normalize_spoken_language_code" not in target:
        country_import_marker = "    configured_language_codes,\n"
        if country_import_marker not in target:
            raise RuntimeError("country_language import marker missing")
        target = target.replace(
            country_import_marker,
            country_import_marker + "    normalize_language_code as normalize_spoken_language_code,\n",
            1,
        )
    if "from iptv.channel_identity import canonical_stream_url" not in target:
        import_marker = "from iptv.playback_status import normalize_test_status\n"
        if import_marker not in target:
            raise RuntimeError("language_routing import marker missing")
        target = target.replace(
            import_marker,
            "from iptv.channel_identity import canonical_stream_url\n" + import_marker,
            1,
        )
    target = target.rstrip() + "\n\n\n" + "\n".join(parts).rstrip() + "\n"

    ast.parse(remaining)
    ast.parse(target)
    CORE.write_text(remaining, encoding="utf-8")
    TARGET.write_text(target, encoding="utf-8")

    TEST.write_text(
        f'''import unittest
from pathlib import Path

import build
from iptv import language_routing

MOVED = {NAMES!r}


class LanguageRoutingCompletionTests(unittest.TestCase):
    def test_build_reexports_remaining_routing_helpers(self):
        for name in MOVED:
            self.assertIs(getattr(build, name), getattr(language_routing, name), name)

    def test_core_no_longer_defines_remaining_routing_helpers(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        for name in MOVED:
            self.assertNotIn(f"def {{name}}(", text, name)

    def test_language_catalog_keeps_country_authority_and_merges_languages(self):
        country = [{{"url": "https://example.test/a.m3u8", "country_code": "RS", "language_codes": ["srp"]}}]
        language = [{{"url": "https://example.test/a.m3u8", "country_code": "HU", "language_codes": ["hun"]}}]
        result = language_routing.build_language_catalog_entries(country, language)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["country_code"], "RS")
        self.assertEqual(result[0]["language_codes"], ["srp", "hun"])

    def test_country_name_uses_configured_name(self):
        cfg = {{"country_names": {{"CZ": "Czechia"}}}}
        self.assertEqual(language_routing.country_name_for_code(cfg, "CZ"), "Czechia")


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )

    docs = DOCS.read_text(encoding="utf-8")
    marker = "- `language_routing.py` — spoken-language interpretation and explicit publication-country routing\n"
    replacement = (
        "- `language_routing.py` — spoken-language interpretation, publication-country routing, "
        "country naming and language-catalog assembly\n"
    )
    if marker not in docs:
        raise RuntimeError("docs language routing marker missing")
    DOCS.write_text(docs.replace(marker, replacement, 1), encoding="utf-8")

    print(f"Finished language routing extraction: build_core.py {before:,} -> {CORE.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
