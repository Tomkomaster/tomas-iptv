#!/usr/bin/env python3
"""Run the Tomas IPTV unittest suite with organized subsystem paths available."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
for path in (ROOT, ROOT / "tools", ROOT / "epg"):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
