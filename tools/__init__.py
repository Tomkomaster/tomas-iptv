"""Operational Tomas IPTV command modules.

The command files are being grouped without rewriting every internal import in
one change. Keep the historical sibling module names resolvable while callers
migrate to package-qualified imports.
"""
from __future__ import annotations

import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
for _path in (_ROOT, _ROOT / "tools", _ROOT / "epg"):
    _text = str(_path)
    if _text not in sys.path:
        sys.path.insert(0, _text)
