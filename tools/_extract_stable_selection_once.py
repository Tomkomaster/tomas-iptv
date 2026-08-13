#!/usr/bin/env python3
from __future__ import annotations
import ast
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CORE=ROOT/'iptv'/'build_core.py'
TARGET=ROOT/'iptv'/'stable_selection.py'
TEST=ROOT/'tests'/'test_stable_selection_refactor.py'
DOCS=ROOT/'docs'/'build-structure.md'
NAMES=('stable_block_reason','select_stable_playlist_candidates')

def main():
    source=CORE.read_text(encoding='utf-8'); tree=ast.parse(source); lines=source.splitlines(keepends=True)
    nodes={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in NAMES}
    if set(nodes)!=set(NAMES): raise RuntimeError('stable selection markers changed')
    remove=set(); parts={}
    for name in NAMES:
        n=nodes[name]; parts[name]=''.join(lines[n.lineno-1:n.end_lineno]).strip()+'\n'; remove.update(range(n.lineno-1,n.end_lineno))
    remaining=''.join(line for i,line in enumerate(lines) if i not in remove)

    stable=parts['select_stable_playlist_candidates']
    old='''def select_stable_playlist_candidates(\n    final_entries: list[dict],\n    audit_rows: list[dict],\n    cfg: dict,\n) -> tuple[\n'''
    new='''def select_stable_playlist_candidates(\n    final_entries: list[dict],\n    audit_rows: list[dict],\n    cfg: dict,\n    *,\n    make_test_candidates,\n    route_candidates,\n    build_quality_context,\n    score_quality,\n) -> tuple[\n'''
    if old not in stable: raise RuntimeError('stable signature marker changed')
    stable=stable.replace(old,new,1)
    stable=stable.replace('build_feed_quality_context(', 'build_quality_context(')
    stable=stable.replace('route_candidates_to_verified_countries(', 'route_candidates(')
    stable=stable.replace('make_test_playlist_candidates(', 'make_test_candidates(')
    stable=stable.replace('score_feed_quality(', 'score_quality(')

    module='''#!/usr/bin/env python3
"""Stable family-playlist filtering and best-feed choice.

The scorer, quality-context builder and routing/candidate functions are injected
by build_core at call time. That deliberately preserves the historical runtime
monkeypatch contract used by same-build verified-feed failover.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from iptv.audit import audit_excluded
from iptv.channel_identity import logical_channel_key

'''+parts['stable_block_reason']+'\n'+stable
    ast.parse(module)

    marker='from iptv.feed_selection import (\n'
    imports='from iptv.stable_selection import stable_block_reason\nfrom iptv.stable_selection import select_stable_playlist_candidates as _select_stable_playlist_candidates\n'
    if marker not in remaining: raise RuntimeError('feed selection import marker missing')
    remaining=remaining.replace(marker,imports+marker,1)

    wrapper='''\n\ndef select_stable_playlist_candidates(\n    final_entries: list[dict],\n    audit_rows: list[dict],\n    cfg: dict,\n):\n    """Compatibility wrapper that keeps live build globals injectable."""\n    return _select_stable_playlist_candidates(\n        final_entries,\n        audit_rows,\n        cfg,\n        make_test_candidates=make_test_playlist_candidates,\n        route_candidates=route_candidates_to_verified_countries,\n        build_quality_context=build_feed_quality_context,\n        score_quality=score_feed_quality,\n    )\n'''
    insertion='def prepare_published_entries(\n'
    if insertion not in remaining: raise RuntimeError('publication marker missing')
    remaining=remaining.replace(insertion,wrapper+'\n'+insertion,1)
    ast.parse(remaining)

    CORE.write_text(remaining,encoding='utf-8'); TARGET.write_text(module,encoding='utf-8')
    TEST.write_text('''import unittest
from pathlib import Path
import build
from iptv import stable_selection

class StableSelectionRefactorTests(unittest.TestCase):
    def test_block_reason_is_owned_by_module(self):
        self.assertIs(build.stable_block_reason, stable_selection.stable_block_reason)
        self.assertNotIn("def stable_block_reason(", Path("iptv/build_core.py").read_text(encoding="utf-8"))

    def test_core_keeps_only_compatibility_wrapper(self):
        text=Path("iptv/build_core.py").read_text(encoding="utf-8")
        self.assertEqual(text.count("def select_stable_playlist_candidates("),1)
        self.assertIn("score_quality=score_feed_quality",text)
        self.assertIn("build_quality_context=build_feed_quality_context",text)

    def test_live_score_monkeypatch_reaches_extracted_selector(self):
        old=build.score_feed_quality
        calls=[]
        def fake(entry,cfg,context=None):
            calls.append(entry.get("url")); return {"score":1,"summary":"fake"}
        try:
            build.score_feed_quality=fake
            rows=[{"stream_url":"https://example.test/a.m3u8","decision":"Verified","exclude_from_playlist":False,"vlc":"works","samsung":"works"}]
            entries=[{"url":"https://example.test/a.m3u8","channel_name":"A","country_code":"HU","channel_key":"HU:id:a","source_flags":[]}]
            cfg={"country_outputs":{"HU":"hu.m3u"},"stable_playlist":{"allowed_decisions":["Verified"]}}
            selected,_=build.select_stable_playlist_candidates(entries,rows,cfg)
            self.assertEqual(len(selected),1)
            self.assertEqual(calls,["https://example.test/a.m3u8"])
        finally:
            build.score_feed_quality=old

if __name__ == "__main__": unittest.main()
''',encoding='utf-8')
    docs=DOCS.read_text(encoding='utf-8'); marker='- `feed_selection.py` — current-feed suppression and complete test-playlist candidate selection\n'
    if marker not in docs: raise RuntimeError('docs marker missing')
    DOCS.write_text(docs.replace(marker,marker+'- `stable_selection.py` — stable-family filtering and callback-driven best-feed ranking\n',1),encoding='utf-8')
    print(f'build_core.py after stable selection extraction: {CORE.stat().st_size:,} bytes')
    print(f'stable_selection.py: {TARGET.stat().st_size:,} bytes')

if __name__=='__main__': main()
