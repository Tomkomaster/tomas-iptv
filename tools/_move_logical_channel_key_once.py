#!/usr/bin/env python3
"""One-off move of logical_channel_key into channel_identity.py."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "iptv" / "build_core.py"
IDENTITY = ROOT / "iptv" / "channel_identity.py"
TEST = ROOT / "tests" / "test_channel_identity_logical_key.py"


def main() -> None:
    core = CORE.read_text(encoding="utf-8")
    tree = ast.parse(core)
    lines = core.splitlines(keepends=True)
    node = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "logical_channel_key"),
        None,
    )
    if node is None or node.end_lineno is None:
        raise RuntimeError("logical_channel_key was not found in build_core.py")

    moved = "".join(lines[node.lineno - 1:node.end_lineno]).strip() + "\n"
    remaining = "".join(
        line for index, line in enumerate(lines)
        if not (node.lineno - 1 <= index < node.end_lineno)
    )

    marker = "from iptv.channel_identity import (\n"
    if marker not in remaining:
        raise RuntimeError("channel_identity import block was not found")
    remaining = remaining.replace(
        marker,
        "from iptv.channel_identity import logical_channel_key\n" + marker,
        1,
    )

    identity = IDENTITY.read_text(encoding="utf-8")
    if "from country_language import normalize_country_code" not in identity:
        import_marker = "from iptv.source_loader import split_extinf\n"
        if import_marker not in identity:
            raise RuntimeError("channel_identity import marker was not found")
        identity = identity.replace(
            import_marker,
            "from country_language import normalize_country_code\n" + import_marker,
            1,
        )
    if "def logical_channel_key(" in identity:
        raise RuntimeError("logical_channel_key already exists in channel_identity.py")
    identity = identity.rstrip() + "\n\n\n" + moved

    ast.parse(remaining)
    ast.parse(identity)
    CORE.write_text(remaining, encoding="utf-8")
    IDENTITY.write_text(identity, encoding="utf-8")

    TEST.write_text(
        '''import unittest
from pathlib import Path

import build
from iptv import channel_identity


class LogicalChannelKeyRefactorTests(unittest.TestCase):
    def test_logical_key_is_owned_by_channel_identity(self):
        self.assertIs(build.logical_channel_key, channel_identity.logical_channel_key)
        core = Path("iptv/build_core.py").read_text(encoding="utf-8")
        self.assertNotIn("def logical_channel_key(", core)

    def test_country_scopes_same_channel_identity(self):
        entry = {"country_code": "SK", "canonical_id": "Demo.Channel"}
        self.assertEqual(
            channel_identity.logical_channel_key(entry),
            "SK:canonical:demo.channel",
        )


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )
    print(
        f"Moved logical_channel_key; build_core.py is now {CORE.stat().st_size:,} bytes."
    )


if __name__ == "__main__":
    main()
