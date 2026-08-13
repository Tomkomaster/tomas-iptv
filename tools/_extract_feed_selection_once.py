#!/usr/bin/env python3
from __future__ import annotations
import ast
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CORE=ROOT/'iptv'/'build_core.py'
TARGET=ROOT/'iptv'/'feed_selection.py'
TEST=ROOT/'tests'/'test_feed_selection_refactor.py'
DOCS=ROOT/'docs'/'build-structure.md'
NAMES=('select_playlist_candidates','make_test_playlist_candidates')

def main():
    source=CORE.read_text(encoding='utf-8'); tree=ast.parse(source); lines=source.splitlines(keepends=True)
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in NAMES]
    if {n.name for n in nodes} != set(NAMES): raise RuntimeError('feed selection markers changed')
    remove=set(); parts=[]
    for n in sorted(nodes,key=lambda x:x.lineno):
        parts.append(''.join(lines[n.lineno-1:n.end_lineno]).strip()+'\n'); remove.update(range(n.lineno-1,n.end_lineno))
    remaining=''.join(line for i,line in enumerate(lines) if i not in remove)
    marker='from iptv.audit import (\n'
    block='from iptv.feed_selection import (\n    select_playlist_candidates,\n    make_test_playlist_candidates,\n)\n'
    if marker not in remaining: raise RuntimeError('audit import marker missing')
    remaining=remaining.replace(marker,block+marker,1)
    module='''#!/usr/bin/env python3
"""Current-feed and test-playlist candidate selection."""
from __future__ import annotations

from iptv.audit import audit_excluded, audit_rows_by_stream_url
from iptv.channel_identity import canonical_stream_url, logical_channel_key
from iptv.playback_status import normalize_test_status

'''+"\n".join(parts).rstrip()+"\n"
    ast.parse(remaining); ast.parse(module)
    CORE.write_text(remaining,encoding='utf-8'); TARGET.write_text(module,encoding='utf-8')
    TEST.write_text('''import unittest
from pathlib import Path
import build
from iptv import feed_selection

class FeedSelectionRefactorTests(unittest.TestCase):
    def test_build_reexports_feed_selection(self):
        self.assertIs(build.select_playlist_candidates, feed_selection.select_playlist_candidates)
        self.assertIs(build.make_test_playlist_candidates, feed_selection.make_test_playlist_candidates)
    def test_core_no_longer_defines_selection(self):
        text=Path("iptv/build_core.py").read_text(encoding="utf-8")
        self.assertNotIn("def select_playlist_candidates(",text)
        self.assertNotIn("def make_test_playlist_candidates(",text)
    def test_test_candidates_keep_all_current_streams(self):
        rows=[{"stream_url":"https://example.test/a.m3u8","decision":"Rejected","exclude_from_playlist":True}]
        entries=[{"url":"https://example.test/a.m3u8","channel_name":"A"}]
        out=feed_selection.make_test_playlist_candidates(entries,rows)
        self.assertEqual(len(out),1)
        self.assertEqual(out[0]["_decision"],"Rejected")

if __name__ == "__main__": unittest.main()
''',encoding='utf-8')
    docs=DOCS.read_text(encoding='utf-8'); marker='- `audit.py` — manual playback audit validation, decisions and stream-history preparation\n'
    if marker not in docs: raise RuntimeError('docs marker missing')
    DOCS.write_text(docs.replace(marker,marker+'- `feed_selection.py` — current-feed suppression and complete test-playlist candidate selection\n',1),encoding='utf-8')
    print(f'build_core.py after feed selection extraction: {CORE.stat().st_size:,} bytes')

if __name__=='__main__': main()
