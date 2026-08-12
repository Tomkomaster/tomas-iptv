"""Operational Tomas IPTV command modules.

The command files are being grouped without rewriting every internal import in
one change. Keep the package directory importable under historical sibling
module names while callers migrate to ``tools.<name>``.
"""
from __future__ import annotations

import sys
from pathlib import Path


_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)
