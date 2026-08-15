#!/usr/bin/env python3
"""One-off importer for the manual playback batch supplied on 2026-08-15."""
from __future__ import annotations

import json
from pathlib import Path

from iptv.audit_storage import compact_manual_audit_payload

AUDIT_PATH = Path("audit.json")
TESTED_ON = "2026-08-15"

LANGUAGE_BY_COUNTRY = {
    "CZ": "ces",
    "HU": "hun",
    "RO": "ron",
    "SK": "slk",
}

TESTS = [('CZ', 'Šlágr Originál', 'https://stream-6.mazana.tv/slagr.m3u', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('CZ', 'RTM Plus Feed 2', 'http://www.rtmplus.cz/live/1-playlist.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('CZ', 'RTM Plus', 'https://www.rtmplus.cz/live/1-playlist.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('CZ', 'Šlágr Muzika', 'https://stream-33.mazana.tv/slagr2.m3u', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('CZ', 'TV Noe', 'https://n105.quickmedia.tv/noetv/live/noetv/Ifd4_1_4/chunks_dvr_timeshift-0-7200.m3u8', 'ok', 'ok'),
 ('CZ', 'TV Noe Feed 2', 'https://n105.quickmedia.tv/noe-abr/noe-abr/playlist.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('CZ', 'TV Noe+', 'https://n105.quickmedia.tv/noetvplus/live/noetvplus/Shz3_1_1/chunks_dvr_timeshift-0-7200.m3u8', 'ok', 'ok'),
 ('CZ', 'TV Noe+ Feed 2', 'https://n105.quickmedia.tv/noe-2-abr/noe-2-abr/playlist_dvr.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('CZ', 'CMS TV', 'https://ythls.onrender.com/video/VisH4oT5OI8.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('CZ', 'TVS', 'https://ythls.onrender.com/video/Wr2lfcqVI9U.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('CZ', 'TV Morava', 'https://ythls-v2.onrender.com/channel/UCW33LPZQ1SA7ByUW6GeKRGw.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('HU', 'Hír TV', 'https://onlinestream.live/play.m3u?id=4740&ext=.m3u', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('HU', 'Hír TV Feed 2', 'https://video11.videa.hu/static/live/8.2966061.2530409.1.5.590.590/index.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('HU', 'Óbuda TV', 'https://stream.streaming4u.hu:443/ObudaTV/index.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('HU', 'Daru TV', 'https://5cd03f21c7193.streamlock.net/darutv/darutvlive/playlist.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('HU', 'Daru TV Feed 2', 'https://darutv.medialivecdn.hu:443/darutv/7ca4e13b035b7c1ff5608c2c1e6f71e2.sdp/playlist.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('HU', 'Völgyhíd TV Feed 2', 'https://volgyhidtv.medialivecdn.hu/volgyhidtv/790283f9e4f5b818790551d075c335cf.sdp/playlist.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('HU', 'Völgyhíd TV', 'https://5cd03f21c7193.streamlock.net/volgyhidtv/mediakft/playlist.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('HU', 'Soltvadkerti Televízió', 'http://79.120.178.90:1935/soltvadkerttv/soltvlive/playlist.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('HU', 'Soltvadkerti Televízió Feed 2', 'https://soltvadkert.medialivecdn.hu:443/soltvadkerttv/135f0ef3069df243438549b446f911ab.sdp/playlist.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('HU', 'Gran TV', 'https://stream.medialive.hu/gran/grantvlive/playlist.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('HU', 'Gran TV Feed 2', 'https://grantv.medialivecdn.hu:443/gran/51328567842cc1ba78b4b851ee9c46b4.sdp/playlist.m3u8', 'ok', 'ok'),
 ('HU', 'DSTV', 'http://79.120.178.90:1935/dstv/dstvlive/playlist.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('HU', 'DSTV Feed 2', 'https://dstv.medialivecdn.hu:443/dstv/5b72522f9d6849c5b94ea26bf75c9a24.sdp/playlist.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('HU', 'Mór VTV', 'https://cloudfront44.lexanetwork.com:1344/relay01/HDE041.sdp/playlist.m3u8', 'ok', 'ok'),
 ('HU', 'Jászsági Térségi TV', 'https://cloudfront44.lexanetwork.com:1344/relay01/broadcast007.sdp/playlist.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('HU', 'Jászsági Térségi TV Feed 2', 'https://cloudfront41.lexanetwork.com:1344/relay41_1/livestream001.sdp/playlist.m3u8', 'ok', 'ok'),
 ('RO', 'Antena 1', 'https://live1ag.antenaplay.ro/live_a1ro/live_a1ro.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('RO', 'Antena 3 CNN', 'https://live3vox.antenaplay.ro/a3free/a3free.m3u8', 'Immediately skips to the next channel', 'ok'),
 ('RO', 'România TV', 'https://livestream.romaniatv.net/clients/romaniatv/playlist.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('RO', 'Prima TV', 'https://stream1.1616.ro:1945/prima/livestream/playlist.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('RO', 'PRO TV Feed', 'https://cmero-ott-live.ssl.cdn.cra.cz/channels/cme-roprotv/playlist/rum/live_fullhd.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('RO', 'TRINITAS TV', 'https://ythls.onrender.com/video/9czLiKCZ21Y.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('RO', 'Sens TV', 'https://ythls-v2.onrender.com/channel/UCjNREXQY17npPPiROGeLocA.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('SK', 'TV JOJ Feed 2', 'https://nn.geo.joj.sk/hls/joj-720.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('SK', 'TV JOJ Feed 3', 'https://sktv.mxnticek.eu/new/stream.php?ch=JOJ', 'ok', 'ok'),
 ('SK', 'TV JOJ Feed 4', 'https://st01-1.iptv.joj.sk/101-tv-pc.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('SK', 'JOJ 24 Feed 1', 'https://sktv.mxnticek.eu/new/stream.php?ch=JOJ+24', 'ok', 'ok'),
 ('SK', 'JOJ 24 Feed 2', 'https://st01-1.iptv.joj.sk/111-tv-pc.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('SK', 'TA3', 'https://n13.stv.livebox.sk/ta3/685d9a141bd846e8facf83bc378da26b/1.smil/chunklist_b2691072.m3u8', 'ok, but Neplatny token', 'ok, but Neplatny token'),
 ('SK', 'TA3 Feed 2', 'https://sktv.mxnticek.eu/new/stream.php?ch=TA3', 'ok', 'ok'),
 ('SK', 'TV Raj', 'https://ottst05.flexitv.sk/2827-tv-pc.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('SK', 'TV NRSR', 'https://n11.stv.livebox.sk/stv-tv/stv4.stream/playlist.m3u8', 'ok, but Vysielanie sa prerusilo z dovodu necinnosti, prosim nacitajte stranku znovu', 'ok, but Vysielanie sa prerusilo z dovodu necinnosti, prosim nacitajte stranku znovu'),
 ('SK', 'TV NRSR Feed 2', 'https://live.cdn.joj.sk/live/andromeda/nrsr/live.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('SK', 'TV NRSR Feed 3', 'https://n15.stv.livebox.sk/stv-tv/_definst_/stv7.smil/playlist.m3u8', 'ok, but Vysielanie sa prerusilo z dovodu necinnosti, prosim nacitajte stranku znovu', 'ok, but Vysielanie sa prerusilo z dovodu necinnosti, prosim nacitajte stranku znovu'),
 ('SK', 'RTV Krea Feed 2', 'https://ythls.onrender.com/video/XSP1kSSDjzQ.m3u8', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE'),
 ('SK', 'RTV Krea', 'http://213.81.153.221:8080/galanta', 'Immediately skips to the next channel', 'NOT_SUPPORTED_FILE')]


def status_for(note: str) -> str:
    token = note.strip().casefold()
    if token == "ok":
        return "works"
    if "not_supported_file" in token:
        return "format_error"
    if "immediately skips to the next channel" in token:
        return "generic_error"
    if "neplatny token" in token or "vysielanie sa prerusilo" in token:
        return "works_with_warning"
    raise RuntimeError(f"Unrecognized manual test note: {note!r}")


def main() -> None:
    payload = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("channels"), list):
        raise RuntimeError("audit.json must contain an object with a channels list.")

    channels = payload["channels"]
    by_url = {}
    for item in channels:
        if not isinstance(item, dict):
            continue
        url = str(item.get("stream_url") or "").strip()
        if url:
            if url in by_url:
                raise RuntimeError(f"Existing duplicate stream_url in audit.json: {url}")
            by_url[url] = item

    updated = 0
    added = 0

    for country, channel, url, vlc_note, samsung_note in TESTS:
        language = LANGUAGE_BY_COUNTRY[country]
        item = by_url.get(url)

        if item is None:
            item = {
                "channel": channel,
                "stream_url": url,
                "playlist_country_code": country,
                "output_country_code": country,
                "expected_language_codes": [language],
                "provenance": "User-provided stream (manual playback review)",
                "discovery": "Manual VLC + Samsung test supplied 2026-08-15",
            }
            channels.append(item)
            by_url[url] = item
            added += 1
        else:
            updated += 1
            item["channel"] = channel
            item["playlist_country_code"] = country
            item["output_country_code"] = country
            item["expected_language_codes"] = [language]

        for field in (
            "language_match",
            "decision",
            "exclude_from_playlist",
            "reason",
            "notes",
            "vlc",
            "samsung",
            "vlc_note",
            "samsung_note",
            "tested_on",
        ):
            item.pop(field, None)

        vlc = status_for(vlc_note)
        samsung = status_for(samsung_note)

        item["vlc"] = vlc
        item["samsung"] = samsung
        item["vlc_note"] = vlc_note
        item["samsung_note"] = samsung_note
        item["tested_on"] = TESTED_ON

        if vlc in {"works", "works_with_warning"} or samsung in {"works", "works_with_warning"}:
            item["observed_language_codes"] = [language]

        lower_notes = f"{vlc_note} {samsung_note}".casefold()

        if "neplatny token" in lower_notes:
            item["decision"] = "rejected"
            item["exclude_from_playlist"] = True
            item["reason"] = (
                "The feed opens on both tested devices but displays Neplatny token "
                "instead of the programme."
            )
            item["notes"] = (
                "Retested on VLC and Samsung; both still show Neplatny token. "
                "Reject this exact tokenized URL."
            )
        elif "vysielanie sa prerusilo" in lower_notes:
            item["decision"] = "needs_review"
            item["reason"] = (
                "Both tested devices open the feed but show the broadcaster inactivity/"
                "interruption message instead of confirmed live programming."
            )
            item["notes"] = (
                "Retested on VLC and Samsung; both show: "
                "Vysielanie sa prerusilo z dovodu necinnosti, prosim nacitajte stranku znovu."
            )
        elif vlc == "works" and samsung == "works":
            item["reason"] = (
                "Working on both VLC and Samsung in the 2026-08-15 manual test."
            )
            item["notes"] = "Passed both manual playback tests."
        elif samsung == "works":
            item["decision"] = "tv_verified"
            item["reason"] = (
                "Samsung playback works, while VLC immediately skips to the next channel."
            )
            item["notes"] = (
                f"Mixed manual result. VLC: {vlc_note}. Samsung: {samsung_note}."
            )
        else:
            item["decision"] = "rejected"
            item["exclude_from_playlist"] = True
            item["reason"] = (
                "This exact feed failed on both tested devices in the 2026-08-15 manual test."
            )
            item["notes"] = (
                f"Failed both manual playback tests. VLC: {vlc_note}. "
                f"Samsung: {samsung_note}."
            )

    compact = compact_manual_audit_payload(payload)

    seen = set()
    for item in compact["channels"]:
        url = str(item.get("stream_url") or "").strip()
        if not url:
            continue
        if any(ch.isspace() for ch in url):
            raise RuntimeError(f"Whitespace is not allowed in stream_url: {url!r}")
        if url in seen:
            raise RuntimeError(f"Duplicate stream_url after merge: {url}")
        seen.add(url)

    AUDIT_PATH.write_text(
        json.dumps(compact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    print(f"Manual audit batch applied: {updated} updated, {added} added, {len(TESTS)} tests total.")


if __name__ == "__main__":
    main()
