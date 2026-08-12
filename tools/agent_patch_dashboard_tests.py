#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected test text not found in {path}: {old!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "tests/test_dashboard_attention.py",
    "import unittest\n",
    "import unittest\nfrom pathlib import Path\n",
)
replace_once(
    "tests/test_dashboard_attention.py",
    '        self.assertIn("fetch(\'attention.json\'", page)\n',
    '        script = Path("static/dashboard.js").read_text(encoding="utf-8")\n'
    '        self.assertIn("fetch(\'attention.json\'", script)\n',
)

replace_once(
    "tests/test_dashboard_health.py",
    "import unittest\n",
    "import unittest\nfrom pathlib import Path\n",
)
replace_once(
    "tests/test_dashboard_health.py",
    '        self.assertIn("fetch(\'health.json\'", page)\n',
    '        script = Path("static/dashboard.js").read_text(encoding="utf-8")\n'
    '        self.assertIn("fetch(\'health.json\'", script)\n',
)

replace_once(
    "tests/test_non_24_7_health.py",
    '        self.assertIn("Event-based inactive", page)\n'
    '        self.assertIn("data-health-actionable", page)\n',
    '        script = Path("static/dashboard.js").read_text(encoding="utf-8")\n'
    '        self.assertIn("Event-based inactive", script)\n'
    '        self.assertIn("data-health-actionable", script)\n',
)
