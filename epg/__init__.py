"""Tomas IPTV EPG preparation, merging, policy and health helpers.

The EPG subsystem is now grouped under one package. During the gradual import
migration, expose this directory on ``sys.path`` so the existing sibling imports
inside tested EPG modules continue to resolve exactly as before.
"""
from __future__ import annotations

import sys
from pathlib import Path


_EPG_DIR = str(Path(__file__).resolve().parent)
if _EPG_DIR not in sys.path:
    sys.path.insert(0, _EPG_DIR)
