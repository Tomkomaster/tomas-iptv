from __future__ import annotations

from pathlib import Path

path = Path('.github/language_playlists_patch.py')
source = path.read_text(encoding='utf-8')
start_marker = '# Add a small console summary after the existing per-country stable counts.\n'
end_marker = '\n\n# ---------------------------------------------------------------------------\n# Documentation.\n# ---------------------------------------------------------------------------\n'
start = source.index(start_marker)
end = source.index(end_marker, start)
source = source[:start] + source[end:]
exec(compile(source, str(path), 'exec'))
