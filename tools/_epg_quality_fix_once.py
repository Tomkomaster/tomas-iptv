#!/usr/bin/env python3
from pathlib import Path

path = Path('templates/dashboard.html')
text = path.read_text(encoding='utf-8')
old = '<h3>EPG completeness by country</h3>'
new = '<h3>EPG coverage by country</h3>'
if text.count(old) != 1:
    raise SystemExit(f'Expected one EPG completeness heading, found {text.count(old)}')
path.write_text(text.replace(old, new), encoding='utf-8')
