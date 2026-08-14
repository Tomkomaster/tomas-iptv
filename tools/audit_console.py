#!/usr/bin/env python3
"""Local-only browser console for manual Tomas IPTV playback audits."""
from __future__ import annotations

import argparse
import html
import json
import os
import secrets
import shutil
import tempfile
import threading
import webbrowser
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from country_language import normalize_country_code, normalize_language_codes
from iptv.audit_storage import compact_manual_audit_payload
from iptv.channel_identity import canonical_stream_url
from iptv.playback_status import normalize_test_status

ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
PORT = 8765

PLAYBACK = (
    ("works", "Works"),
    ("works_with_warning", "Works with warning"),
    ("loads", "Just loads"),
    ("mrl_error", "MRL error"),
    ("format_error", "Unsupported format"),
    ("generic_error", "Generic error"),
    ("wrong_language", "Wrong language"),
    ("needs_review", "Needs review"),
    ("not_tested", "Not tested"),
)
SOURCE_TYPES = (
    "Official broadcaster",
    "Broadcaster CDN",
    "Provider relay",
    "Unknown",
)


class ConsoleError(RuntimeError):
    pass


def _json(path: Path):
    if not path.is_file():
        raise ConsoleError(f"Required file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConsoleError(f"Invalid JSON in {path}: {exc}") from exc


def load_report_rows(path: Path) -> list[dict]:
    data = _json(path)
    rows = ((data.get("audit") or {}).get("channels") or []) if isinstance(data, dict) else []
    if not isinstance(rows, list):
        raise ConsoleError("report.json audit.channels must be a list")
    return [
        dict(row)
        for row in rows
        if isinstance(row, dict)
        and row.get("stream_url")
        and row.get("in_playlist") is not False
    ]


def load_audit(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": 2, "storage": "manual_only", "channels": []}
    return compact_manual_audit_payload(_json(path))


def exact_index(payload: dict) -> dict[str, tuple[int, dict]]:
    result = {}
    for i, raw in enumerate(payload.get("channels") or []):
        if not isinstance(raw, dict) or not raw.get("stream_url"):
            continue
        key = canonical_stream_url(str(raw["stream_url"]))
        if key in result:
            raise ConsoleError(f"Duplicate exact audit URL: {raw['stream_url']}")
        result[key] = (i, dict(raw))
    return result


def pending_reasons(manual: dict | None) -> list[str]:
    if manual is None:
        return ["No exact-URL audit"]
    reasons = []
    if normalize_test_status(str(manual.get("vlc") or "")) == "not_tested":
        reasons.append("VLC not tested")
    if normalize_test_status(str(manual.get("samsung") or "")) == "not_tested":
        reasons.append("Samsung not tested")
    if not normalize_language_codes(manual.get("observed_language_codes")):
        reasons.append("Language not confirmed")
    return reasons


def build_queue(rows: list[dict], payload: dict, mode="pending", country="") -> list[dict]:
    idx = exact_index(payload)
    country = normalize_country_code(country)
    mode = mode if mode in {"pending", "needs_review", "all"} else "pending"
    out = []
    for row in rows:
        key = canonical_stream_url(str(row.get("stream_url") or ""))
        manual = idx.get(key, (None, None))[1]
        item = dict(row)
        if manual:
            item.update(manual)
        row_country = normalize_country_code(
            str(item.get("playlist_country_code") or item.get("country_code") or "")
        )
        if country and row_country != country:
            continue
        reasons = pending_reasons(manual)
        if mode == "pending" and not reasons:
            continue
        if mode == "needs_review" and row.get("decision") != "Needs review":
            continue
        item["_key"] = key
        item["_pending"] = reasons
        out.append(item)
    return sorted(out, key=lambda x: (
        normalize_country_code(str(x.get("playlist_country_code") or x.get("country_code") or "")),
        str(x.get("channel") or "").casefold(),
        int(x.get("feed_index") or 1),
    ))


def _first(form: dict[str, list[str]], name: str, default="") -> str:
    values = form.get(name) or []
    return str(values[0] if values else default).strip()


def save_result(payload: dict, row: dict, form: dict[str, list[str]], tested_on=None) -> dict:
    url = str(row.get("stream_url") or "").strip()
    channel = str(row.get("channel") or "").strip()
    if not url or not channel:
        raise ConsoleError("Current report row has no channel or URL")

    idx = exact_index(payload)
    key = canonical_stream_url(url)
    position, old = idx.get(key, (None, None))
    item = dict(old or {})
    item.update({"channel": channel, "stream_url": url})

    tvg_id = str(row.get("tvg_id") or item.get("tvg_id") or "").strip()
    if tvg_id:
        item["tvg_id"] = tvg_id
    country = normalize_country_code(str(
        item.get("playlist_country_code")
        or row.get("playlist_country_code")
        or row.get("country_code")
        or ""
    ))
    if country:
        item["playlist_country_code"] = country
    expected = normalize_language_codes(
        item.get("expected_language_codes")
        or row.get("expected_language_codes")
        or row.get("language_codes")
    )
    if expected:
        item["expected_language_codes"] = expected

    item["vlc"] = normalize_test_status(_first(form, "vlc", item.get("vlc", "not_tested")))
    item["samsung"] = normalize_test_status(_first(form, "samsung", item.get("samsung", "not_tested")))

    observed = list(form.get("language") or [])
    observed += [x.strip() for x in _first(form, "other_languages").replace(";", ",").split(",") if x.strip()]
    observed = normalize_language_codes(observed)
    if observed:
        item["observed_language_codes"] = observed
    else:
        item.pop("observed_language_codes", None)

    for field in ("vlc_note", "samsung_note", "notes"):
        value = _first(form, field)
        if value:
            item[field] = value
        else:
            item.pop(field, None)

    # Source type cannot be learned from a playback test. "Unknown" therefore
    # means "do not change provenance", not "replace useful discovery evidence
    # with the word Unknown". Only a positive separately researched source type
    # is allowed to replace provenance from this optional advanced control.
    source_type = _first(form, "source_type", "Unknown")
    if source_type in SOURCE_TYPES[:-1]:
        item["provenance"] = source_type
    elif not item.get("provenance") and row.get("provenance"):
        item["provenance"] = row["provenance"]

    if not item.get("discovery"):
        discovery = str(row.get("discovery") or row.get("source") or "").strip()
        if discovery:
            item["discovery"] = discovery

    if item.get("vlc") != "not_tested" or item.get("samsung") != "not_tested" or observed:
        item["tested_on"] = tested_on or date.today().isoformat()

    channels = list(payload.get("channels") or [])
    if position is None:
        channels.append(item)
    else:
        channels[position] = item
    updated = dict(payload)
    updated["channels"] = channels
    return compact_manual_audit_payload(updated)


def write_audit(path: Path, payload: dict) -> None:
    payload = compact_manual_audit_payload(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def language_choices(config: Path) -> list[tuple[str, str]]:
    data = _json(config)
    names = data.get("language_names") or {}
    out = []
    if isinstance(names, dict):
        for raw_code, raw_name in names.items():
            codes = normalize_language_codes([raw_code])
            if codes:
                out.append((codes[0], str(raw_name or codes[0])))
    return out


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def radio(name: str, current: str) -> str:
    return " ".join(
        f'<label><input type="radio" name="{name}" value="{value}"'
        f'{" checked" if current == value else ""}> {esc(label)}</label>'
        for value, label in PLAYBACK
    )


def render(rows, payload, languages, token, mode, country, focus="", saved=False) -> str:
    queue = build_queue(rows, payload, mode, country)
    current = next((x for x in queue if x.get("_key") == canonical_stream_url(focus)), None) if focus else None
    current = current or (queue[0] if queue else None)
    countries = sorted({normalize_country_code(str(x.get("playlist_country_code") or x.get("country_code") or "")) for x in rows} - {""})

    country_options = ['<option value="">All countries</option>'] + [
        f'<option value="{c}"{" selected" if c == normalize_country_code(country) else ""}>{c}</option>' for c in countries
    ]
    mode_options = [
        f'<option value="{value}"{" selected" if value == mode else ""}>{label}</option>'
        for value, label in (("pending", "Pending tests"), ("needs_review", "Build: needs review"), ("all", "All current"))
    ]

    jump_options = ['<option value="">Jump to channel…</option>']
    seen_channels: set[tuple[str, str]] = set()
    for item in queue:
        item_country = normalize_country_code(
            str(item.get("playlist_country_code") or item.get("country_code") or "")
        )
        item_channel = str(item.get("channel") or "Unnamed channel").strip()
        channel_key = (item_country, item_channel.casefold())
        if channel_key in seen_channels:
            continue
        seen_channels.add(channel_key)
        feed_count = max(int(item.get("feed_count") or 1), 1)
        label = f"{item_channel} — {item_country or '??'}"
        if feed_count > 1:
            label += f" — {feed_count} feeds"
        selected = False
        if current:
            current_country = normalize_country_code(
                str(current.get("playlist_country_code") or current.get("country_code") or "")
            )
            current_channel = str(current.get("channel") or "").strip().casefold()
            selected = current_country == item_country and current_channel == item_channel.casefold()
        jump_options.append(
            f'<option value="{esc(item.get("_key"))}"{" selected" if selected else ""}>{esc(label)}</option>'
        )

    if not current:
        card = '<section><h2>Queue complete</h2><p>No streams match this filter.</p></section>'
    else:
        pos = queue.index(current)
        nxt = queue[(pos + 1) % len(queue)] if len(queue) > 1 else current
        observed = normalize_language_codes(current.get("observed_language_codes"))
        known = {code for code, _ in languages}
        lang_html = " ".join(
            f'<label><input type="checkbox" name="language" value="{code}"{" checked" if code in observed else ""}> {esc(label)} ({code})</label>'
            for code, label in languages
        )
        provenance = str(current.get("provenance") or "").strip()
        source_type = provenance if provenance in SOURCE_TYPES[:-1] else "Unknown"
        source_type_html = " ".join(
            f'<label><input type="radio" name="source_type" value="{esc(value)}"{" checked" if source_type == value else ""}> {esc(value)}</label>'
            for value in SOURCE_TYPES
        )
        stream_url = str(current.get("stream_url") or "").strip()
        host = urlparse(stream_url).hostname or "Unknown"
        discovery = str(current.get("discovery") or current.get("source") or "Unknown").strip()
        other_lang = ", ".join(code for code in observed if code not in known)
        prefix = normalize_country_code(str(current.get("playlist_country_code") or current.get("country_code") or ""))
        reasons = " · ".join(current.get("_pending") or [])
        card = f'''
<section>
<h2>[{esc(prefix)}] {esc(current.get("channel"))}</h2>
<p class="muted">{esc(current.get("feed_label") or "Single")} · {esc(reasons)}</p>
<p><strong>URL:</strong> <code>{esc(stream_url)}</code></p>
<p><strong>Candidate source:</strong> {esc(current.get("source"))} · <strong>Expected:</strong> {esc(", ".join(normalize_language_codes(current.get("expected_language_codes"))) or "Unknown")}</p>
<form method="post" action="/save">
<input type="hidden" name="token" value="{esc(token)}">
<input type="hidden" name="stream_url" value="{esc(stream_url)}">
<input type="hidden" name="next_focus" value="{esc(nxt.get("_key"))}">
<input type="hidden" name="mode" value="{esc(mode)}"><input type="hidden" name="country" value="{esc(country)}">
<fieldset><legend>VLC</legend>{radio("vlc", normalize_test_status(str(current.get("vlc") or "")))}<input name="vlc_note" placeholder="VLC note" value="{esc(current.get("vlc_note"))}"></fieldset>
<fieldset><legend>Samsung</legend>{radio("samsung", normalize_test_status(str(current.get("samsung") or "")))}<input name="samsung_note" placeholder="Samsung note" value="{esc(current.get("samsung_note"))}"></fieldset>
<fieldset><legend>Observed language</legend>{lang_html}<input name="other_languages" placeholder="Other codes: deu, srp" value="{esc(other_lang)}"></fieldset>
<fieldset><legend>Notes</legend><textarea name="notes" rows="4">{esc(current.get("notes"))}</textarea></fieldset>
<details>
<summary>More details <span class="muted">(optional source information)</span></summary>
<div class="details-body">
<p><strong>Discovered from:</strong> {esc(discovery)}</p>
<p><strong>URL host:</strong> <code>{esc(host)}</code></p>
<p><strong>Saved provenance:</strong> {esc(provenance or "Unknown")}</p>
<fieldset><legend>Known source type</legend>
<p class="muted">Playback testing cannot determine this. Leave <strong>Unknown</strong> unless the source was separately researched and confirmed.</p>
{source_type_html}
</fieldset>
</div>
</details>
<div class="actions"><button type="submit">Save &amp; next</button><a href="/?mode={quote(mode)}&country={quote(country)}&focus={quote(str(nxt.get('_key') or ''))}">Skip</a></div>
</form>
</section>'''

    notice = '<p class="saved">Saved to audit.json.</p>' if saved else ''
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Tomas IPTV Test Queue</title>
<style>body{{font-family:system-ui;max-width:1100px;margin:auto;padding:24px;background:#10131a;color:#eef2f7}}header,section{{background:#171c26;border:1px solid #303849;border-radius:14px;padding:20px;margin-bottom:16px}}.toolbar{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}.toolbar form{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}select,input,textarea,button,a{{font:inherit}}select,input,textarea{{background:#0f131a;color:#eef2f7;border:1px solid #465064;border-radius:7px;padding:8px}}input[type=radio],input[type=checkbox]{{width:auto}}fieldset{{border:1px solid #394354;border-radius:10px;margin:12px 0;padding:12px}}fieldset label{{display:inline-block;margin:5px 12px 5px 0}}fieldset input[type=text],fieldset input:not([type]){{display:block;width:100%;margin-top:8px}}textarea{{width:100%}}button,a{{display:inline-block;background:#356ed3;color:white;border:0;border-radius:8px;padding:9px 13px;text-decoration:none}}.actions{{display:flex;gap:8px;justify-content:flex-end;margin-top:14px}}code{{overflow-wrap:anywhere}}.muted{{color:#a7b0c0}}.saved{{background:#173c25;padding:10px;border-radius:8px}}details{{border:1px solid #303849;border-radius:10px;margin:12px 0;background:#131822}}summary{{cursor:pointer;padding:12px;font-weight:600}}.details-body{{padding:0 12px 12px}}.jump-select{{min-width:310px;max-width:520px}}</style></head><body>
<header><h1>TOMAS IPTV — TEST QUEUE</h1><p>Local-only audit assistant. Exact-URL results are written to audit.json; the previous file is kept as audit.json.bak.</p>
<div class="toolbar"><strong>{len(queue)} in queue · {len(rows)} current streams · {len(exact_index(payload))} exact audits</strong>
<form method="get"><select name="mode">{''.join(mode_options)}</select><select name="country">{''.join(country_options)}</select><button>Apply</button></form>
<form method="get"><input type="hidden" name="mode" value="{esc(mode)}"><input type="hidden" name="country" value="{esc(country)}"><select class="jump-select" name="focus" title="Select a channel; typing its first letters also jumps within the list">{''.join(jump_options)}</select><button>Jump</button></form></div></header>{notice}{card}</body></html>'''


class App:
    def __init__(self, report: Path, audit: Path, config: Path):
        self.report, self.audit, self.config = report, audit, config
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()

    def rows(self): return load_report_rows(self.report)
    def payload(self): return load_audit(self.audit)
    def languages(self): return language_choices(self.config)

    def row_for_url(self, url):
        key = canonical_stream_url(url)
        for row in self.rows():
            if canonical_stream_url(str(row.get("stream_url") or "")) == key:
                return row
        raise ConsoleError("Stream is no longer in the current report")

    def save(self, row, form):
        with self.lock:
            write_audit(self.audit, save_result(self.payload(), row, form))


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, app):
        super().__init__(address, Handler)
        self.app = app


class Handler(BaseHTTPRequestHandler):
    server: Server
    def log_message(self, fmt, *args): print("[audit-console] " + fmt % args)

    def send_html(self, text, status=HTTPStatus.OK):
        data = text.encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY"); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/": self.send_error(404); return
        q = parse_qs(parsed.query, keep_blank_values=True)
        mode = (q.get("mode") or ["pending"])[0] or "pending"
        country = (q.get("country") or [""])[0]
        focus = (q.get("focus") or [""])[0]
        try:
            self.send_html(render(self.server.app.rows(), self.server.app.payload(), self.server.app.languages(), self.server.app.token, mode, country, focus, (q.get("saved") or [""])[0] == "1"))
        except ConsoleError as exc:
            self.send_html(f"<h1>Console error</h1><pre>{esc(exc)}</pre>", HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        if urlparse(self.path).path != "/save": self.send_error(404); return
        try: length = int(self.headers.get("Content-Length") or 0)
        except ValueError: self.send_error(400); return
        if not 0 < length <= 128 * 1024: self.send_error(400); return
        form = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        if _first(form, "token") != self.server.app.token: self.send_error(403); return
        try:
            self.server.app.save(self.server.app.row_for_url(_first(form, "stream_url")), form)
        except ConsoleError as exc:
            self.send_html(f"<h1>Could not save</h1><pre>{esc(exc)}</pre>", HTTPStatus.BAD_REQUEST); return
        location = f'/?saved=1&mode={quote(_first(form,"mode","pending"))}&country={quote(_first(form,"country"))}&focus={quote(_first(form,"next_focus"))}'
        self.send_response(HTTPStatus.SEE_OTHER); self.send_header("Location", location); self.end_headers()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Run the local Tomas IPTV manual testing console")
    p.add_argument("--root", default=str(ROOT)); p.add_argument("--report", default="public/report.json")
    p.add_argument("--audit", default="audit.json"); p.add_argument("--config", default="config.json")
    p.add_argument("--port", type=int, default=PORT); p.add_argument("--no-browser", action="store_true")
    args = p.parse_args(argv); root = Path(args.root).resolve()
    resolve = lambda value: (Path(value) if Path(value).is_absolute() else root / value).resolve()
    report, audit, config = resolve(args.report), resolve(args.audit), resolve(args.config)
    if not report.is_file(): p.error(f"{report} not found. Run the normal playlist build first (py build.py).")
    if not config.is_file(): p.error(f"{config} not found.")
    server = Server((HOST, args.port), App(report, audit, config)); url = f"http://{HOST}:{server.server_port}/"
    print(f"Tomas IPTV test console: {url}\nAudit file: {audit}\nPress Ctrl+C to stop.")
    if not args.no_browser: threading.Timer(.3, lambda: webbrowser.open(url)).start()
    try: server.serve_forever(.25)
    except KeyboardInterrupt: print("\nStopping.")
    finally: server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
