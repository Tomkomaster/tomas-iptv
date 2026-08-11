#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from epg_prepare import read_playlist_tvg_ids


TZ = ZoneInfo("Europe/Budapest")
USER_AGENT = "Mozilla/5.0 Tomas-IPTV-EPG/1.0"
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\s+(.+))?$")
NUMERIC_DATE_RE = re.compile(r"^\d{4}[.\-]\s*\d{1,2}[.\-]\s*\d{1,2}\.?$")

WEEKDAYS = [
    "Hétfő",
    "Kedd",
    "Szerda",
    "Csütörtök",
    "Péntek",
    "Szombat",
    "Vasárnap",
]
WEEKDAY_ADJECTIVES = [
    "Hétfői műsor",
    "Keddi műsor",
    "Szerdai műsor",
    "Csütörtöki műsor",
    "Pénteki műsor",
    "Szombati műsor",
    "Vasárnapi műsor",
]
PANNON_SLUGS = [
    "hetfo",
    "kedd",
    "szerda",
    "csutortok",
    "pentek",
    "szombat",
    "vasarnap",
]
HU_MONTHS = {
    1: "január",
    2: "február",
    3: "március",
    4: "április",
    5: "május",
    6: "június",
    7: "július",
    8: "augusztus",
    9: "szeptember",
    10: "október",
    11: "november",
    12: "december",
}
HU_MONTHS_SHORT = {
    1: "jan.",
    2: "febr.",
    3: "márc.",
    4: "ápr.",
    5: "máj.",
    6: "jún.",
    7: "júl.",
    8: "aug.",
    9: "szept.",
    10: "okt.",
    11: "nov.",
    12: "dec.",
}


@dataclass(frozen=True)
class Programme:
    start: datetime
    title: str


@dataclass(frozen=True)
class Source:
    tvg_id: str
    name: str
    provider: str
    kind: str
    url: str
    minimum_programmes: int = 3


def folded(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(value.casefold().split())


def clean_title(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"\s+", " ", value).strip(" .\t\r\n")
    return value


def html_lines(raw: str) -> list[str]:
    raw = re.sub(r"(?is)<script\b.*?</script>|<style\b.*?</style>", " ", raw)
    raw = re.sub(
        r"(?i)<br\s*/?>|</(?:p|div|tr|td|th|li|h[1-6]|table|section|article|a|span|option)>",
        "\n",
        raw,
    )
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    lines = [clean_title(line) for line in raw.splitlines()]
    return [line for line in lines if line]


def fetch_lines(url: str, timeout: float = 15.0) -> list[str]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Cache-Control": "no-cache",
        },
    )
    last_error = None
    for attempt in range(2):
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read(750_000)
                charset = response.headers.get_content_charset() or "utf-8"
            return html_lines(raw.decode(charset, errors="replace"))
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt == 0:
                sleep(0.75)
                continue
            raise
    raise RuntimeError(f"unreachable fetch failure: {last_error}")


def time_parts(value: str) -> tuple[int, int, int, str] | None:
    match = TIME_RE.match(clean_title(value))
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3) or 0)
    if hour > 23 or minute > 59 or second > 59:
        return None
    return hour, minute, second, clean_title(match.group(4) or "")


def parse_entries(
    lines: list[str],
    day: date,
    *,
    allow_rollover: bool = False,
    max_entries: int | None = None,
) -> list[Programme]:
    programmes: list[Programme] = []
    seen: set[tuple[datetime, str]] = set()
    day_offset = 0
    previous_clock: time | None = None

    for index, line in enumerate(lines):
        parsed = time_parts(line)
        if parsed is None:
            continue
        hour, minute, second, inline_title = parsed
        clock = time(hour, minute, second)

        if (
            allow_rollover
            and previous_clock is not None
            and clock < previous_clock
            and previous_clock.hour >= 18
            and clock.hour <= 6
        ):
            day_offset += 1

        title = inline_title
        if not title:
            for candidate in lines[index + 1 : index + 6]:
                if time_parts(candidate) is not None:
                    break
                candidate = clean_title(candidate)
                if not candidate or candidate == ".":
                    continue
                if folded(candidate) in {
                    "most",
                    "kovetkezik",
                    "kezdes",
                    "musor",
                    "tv musor",
                }:
                    continue
                title = candidate
                break

        if not title:
            continue

        start = datetime.combine(
            day + timedelta(days=day_offset),
            clock,
            TZ,
        )
        key = (start, title)
        if key in seen:
            continue
        seen.add(key)
        programmes.append(Programme(start=start, title=title))
        previous_clock = clock

        if max_entries is not None and len(programmes) >= max_entries:
            break

    programmes.sort(key=lambda item: item.start)
    return programmes


def find_index(lines: list[str], predicate, start: int = 0) -> int | None:
    for index in range(start, len(lines)):
        if predicate(lines[index]):
            return index
    return None


def slice_section(lines: list[str], start_predicate, end_predicate) -> list[str]:
    start = find_index(lines, start_predicate)
    if start is None:
        return []
    end = find_index(lines, end_predicate, start + 1)
    return lines[start + 1 : end if end is not None else len(lines)]


def best_section(lines: list[str], start_predicate, end_predicate) -> list[str]:
    starts = [index for index, value in enumerate(lines) if start_predicate(value)]
    best: list[str] = []
    best_score = -1
    for start in starts:
        end = find_index(lines, end_predicate, start + 1)
        section = lines[start + 1 : end if end is not None else len(lines)]
        score = sum(1 for value in section if time_parts(value) is not None)
        if score > best_score:
            best = section
            best_score = score
    return best


def current_weekday_section(lines: list[str], reference_date: date, adjective: bool) -> list[str]:
    weekday = reference_date.weekday()
    marker = WEEKDAY_ADJECTIVES[weekday] if adjective else WEEKDAYS[weekday]
    next_marker = WEEKDAY_ADJECTIVES[(weekday + 1) % 7] if adjective else WEEKDAYS[(weekday + 1) % 7]
    marker_key = folded(marker)
    next_key = folded(next_marker)
    return slice_section(
        lines,
        lambda value: folded(value) == marker_key,
        lambda value: folded(value) == next_key,
    )


def hu_long_date_variants(value: date) -> set[str]:
    month = HU_MONTHS[value.month]
    weekday = WEEKDAYS[value.weekday()]
    return {
        folded(f"{weekday}: {value.year}. {month} {value.day}."),
        folded(f"{value.year}. {month} {value.day}. {weekday}"),
        folded(f"{value.year}. {month} {value.day}. {weekday.casefold()}"),
    }


def hu_short_date_variants(value: date) -> set[str]:
    month = HU_MONTHS_SHORT[value.month]
    weekday = WEEKDAYS[value.weekday()]
    return {
        folded(f"{value.year}. {month} {value.day}. {weekday}"),
        folded(f"{value.year}. {month} {value.day}. {weekday.casefold()}"),
    }


def looks_like_hu_dated_heading(value: str) -> bool:
    key = folded(value)
    return bool(re.search(r"\b20\d{2}\b", key)) and any(
        folded(month) in key for month in HU_MONTHS.values()
    )


def parse_nytv(lines: list[str], reference_date: date) -> list[Programme]:
    section = current_weekday_section(lines, reference_date, adjective=True)
    return parse_entries(section, reference_date, max_entries=40)


def parse_cegled(lines: list[str], reference_date: date) -> list[Programme]:
    section = current_weekday_section(lines, reference_date, adjective=False)
    return parse_entries(section, reference_date, max_entries=40)


def parse_halom(lines: list[str], reference_date: date) -> list[Programme]:
    needle = folded(reference_date.strftime("%Y.%m.%d."))
    section = slice_section(
        lines,
        lambda value: folded(value).startswith(needle),
        lambda value: "musorvaltozas jogat" in folded(value),
    )
    return parse_entries(section, reference_date, max_entries=40)


def parse_kanizsa(lines: list[str], reference_date: date) -> list[Programme]:
    start = find_index(lines, lambda value: folded(value) == "mai tv musor")
    if start is None:
        return []
    section = lines[start + 1 : start + 160]
    return parse_entries(section, reference_date, max_entries=45)


def parse_eger(lines: list[str], reference_date: date) -> list[Programme]:
    variants = {value.rstrip(".") for value in hu_long_date_variants(reference_date)}
    section = best_section(
        lines,
        lambda value: folded(value).rstrip(".") in variants,
        looks_like_hu_dated_heading,
    )
    return parse_entries(section, reference_date, max_entries=50)


def parse_keszthely(lines: list[str], reference_date: date) -> list[Programme]:
    variants = hu_short_date_variants(reference_date) | hu_long_date_variants(reference_date)
    section = slice_section(
        lines,
        lambda value: folded(value) in variants,
        looks_like_hu_dated_heading,
    )
    return parse_entries(section, reference_date, max_entries=70)


def parse_pannon(lines: list[str], reference_date: date) -> list[Programme]:
    marker = folded(f"Pannon TV - {WEEKDAYS[reference_date.weekday()]}")
    starts = [index for index, value in enumerate(lines) if folded(value) == marker]
    start = starts[-1] if starts else 0
    return parse_entries(
        lines[start + 1 : start + 260],
        reference_date,
        allow_rollover=True,
        max_entries=45,
    )


def parse_ozd(lines: list[str], reference_date: date) -> list[Programme]:
    needle = folded(reference_date.strftime("%Y. %m. %d.")).rstrip(".")
    section = best_section(
        lines,
        lambda value: folded(value).rstrip(".") == needle,
        lambda value: bool(NUMERIC_DATE_RE.match(value.replace(" ", ""))),
    )
    return parse_entries(section, reference_date, max_entries=30)


def parse_vasarhely(lines: list[str], reference_date: date) -> list[Programme]:
    variants = hu_long_date_variants(reference_date)
    # Hódpress omits the colon after the weekday.
    variants.add(
        folded(
            f"{reference_date.year}. {HU_MONTHS[reference_date.month]} "
            f"{reference_date.day}. {WEEKDAYS[reference_date.weekday()].casefold()}"
        )
    )
    section = slice_section(
        lines,
        lambda value: folded(value) in variants,
        looks_like_hu_dated_heading,
    )
    return parse_entries(section, reference_date, max_entries=80)


def parse_mako(lines: list[str], reference_date: date) -> list[Programme]:
    def marker(value: date) -> str:
        return folded(
            f"{WEEKDAYS[value.weekday()]} {value.strftime('%m.%d')}"
        ).rstrip(".")

    section = slice_section(
        lines,
        lambda value: folded(value).rstrip(".") == marker(reference_date),
        lambda value: folded(value).rstrip(".") == marker(reference_date + timedelta(days=1)),
    )

    normalized: list[str] = []
    for line in section:
        match = re.match(r"^(\d{1,2})[.:](\d{2})\s+(.+)$", clean_title(line))
        if match:
            normalized.append(
                f"{int(match.group(1)):02d}:{match.group(2)} {match.group(3)}"
            )
        else:
            normalized.append(line)

    return parse_entries(normalized, reference_date, max_entries=30)


def parse_tvmustra(lines: list[str], reference_date: date) -> list[Programme]:
    end = find_index(lines, lambda value: folded(value) == "epp most megy")
    section = lines[: end if end is not None else len(lines)]
    # The actual channel schedule is the final block of time/title pairs before
    # the unrelated "Épp most megy" recommendations.
    time_indexes = [index for index, value in enumerate(section) if time_parts(value)]
    if not time_indexes:
        return []
    start = max(0, time_indexes[0] - 2)
    return parse_entries(
        section[start:],
        reference_date,
        allow_rollover=True,
        max_entries=90,
    )


PARSERS = {
    "nytv": parse_nytv,
    "cegled": parse_cegled,
    "halom": parse_halom,
    "kanizsa": parse_kanizsa,
    "eger": parse_eger,
    "keszthely": parse_keszthely,
    "pannon": parse_pannon,
    "ozd": parse_ozd,
    "vasarhely": parse_vasarhely,
    "mako": parse_mako,
    "tvmustra": parse_tvmustra,
}


def sources_for(reference_date: date) -> list[Source]:
    weekday_slug = PANNON_SLUGS[reference_date.weekday()]
    day_text = reference_date.isoformat()
    return [
        Source(
            "CeglediVarosiTelevizio.hu",
            "Ceglédi Városi Televízió",
            "ctv.hu",
            "cegled",
            "https://ctv.hu/heti-tv-musor/",
        ),
        Source(
            "HalomTV.hu",
            "Halom TV",
            "halomtv.hu",
            "halom",
            f"https://www.halomtv.hu/tvmusor/{day_text}",
        ),
        Source(
            "KanizsaTV.hu@SD",
            "Kanizsa TV",
            "kanizsamediahaz.hu",
            "kanizsa",
            "https://kanizsamediahaz.hu/kanizsatv",
            8,
        ),
        Source(
            "NYTV.hu",
            "Nyíregyházi Televízió",
            "nyiregyhazitv.hu",
            "nytv",
            "https://nyiregyhazitv.hu/tv-musor",
        ),
        Source(
            "TVEger.hu@SD",
            "TV Eger",
            "tveger.hu",
            "eger",
            "https://www.tveger.hu/tv-musor/",
        ),
        Source(
            "TVKeszthely.hu@SD",
            "Keszthely TV",
            "tvkeszthely.hu",
            "keszthely",
            "https://tvkeszthely.hu/musor",
            8,
        ),
        Source(
            "PannonTV.rs@SD",
            "Pannon TV",
            "pannonrtv.com",
            "pannon",
            f"https://pannonrtv.com/musor/pannon-tv-{weekday_slug}",
            8,
        ),
        Source(
            "OzdiVarosiTV.hu@SD",
            "Ózdi Városi TV",
            "ovtv.eu",
            "ozd",
            "https://www.ovtv.eu/index.php/tv-musor",
        ),
        Source(
            "VasarhelyiTelevizio.hu@SD",
            "Vásárhelyi Televízió",
            "hodpress.hu",
            "vasarhely",
            "https://www.hodpress.hu/vtv-musor/",
            8,
        ),
        Source(
            "MakoiVarosiTelevizio.hu@SD",
            "Makói Városi Televízió",
            "makotv.hu",
            "mako",
            "https://makotv.hu/heti-musor/",
            5,
        ),
        Source(
            "EWTNBonumTV.hu@SD",
            "EWTN Bonum",
            "tvmustra.hu",
            "tvmustra",
            f"https://www.tvmustra.hu/tvmusor/EWTN/{day_text}",
            8,
        ),
        Source(
            "FILMBOXPlusComedy.pl@MagyarRomania",
            "FILMBOX+ Comedy",
            "tvmustra.hu",
            "tvmustra",
            f"https://www.tvmustra.hu/tvmusor/FILMBOX_PLUSZ_COMEDY/{day_text}",
            8,
        ),
        Source(
            "FILMBOXPlusEmotion.pl@Hungary",
            "FILMBOX+ Emotion",
            "tvmustra.hu",
            "tvmustra",
            f"https://www.tvmustra.hu/tvmusor/FILMBOX_PLUSZ_EMOTION/{day_text}",
            8,
        ),
        Source(
            "FILMBOXPlusHits.pl@Hungary",
            "FILMBOX+ Hits",
            "tvmustra.hu",
            "tvmustra",
            f"https://www.tvmustra.hu/tvmusor/FILMBOX_PLUSZ_HITS/{day_text}",
            8,
        ),
        Source(
            "FILMBOXPlusOne.pl@Magyar",
            "FILMBOX+ One",
            "tvmustra.hu",
            "tvmustra",
            f"https://www.tvmustra.hu/tvmusor/FILMBOX_PLUSZ_ONE/{day_text}",
            8,
        ),
    ]


def fresh_programme_ids(root: ET.Element, reference_date: date, future_days: int) -> set[str]:
    result: set[str] = set()
    latest = reference_date + timedelta(days=future_days)
    for programme in root.findall("programme"):
        channel = (programme.get("channel") or "").strip()
        start = (programme.get("start") or "").strip()
        match = re.match(r"(\d{8})", start)
        if not channel or not match:
            continue
        try:
            programme_day = datetime.strptime(match.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        if reference_date <= programme_day <= latest:
            result.add(channel)
    return result


def xmltv_timestamp(value: datetime) -> str:
    offset = value.strftime("%z")
    return value.strftime("%Y%m%d%H%M%S") + f" {offset}"


def append_channel_programmes(
    root: ET.Element,
    source: Source,
    programmes: list[Programme],
) -> None:
    channel = ET.Element("channel", {"id": source.tvg_id})
    display = ET.SubElement(channel, "display-name")
    display.text = source.name
    root.append(channel)

    for index, programme in enumerate(programmes):
        if index + 1 < len(programmes):
            stop = programmes[index + 1].start
        else:
            stop = programme.start + timedelta(hours=1)
        if stop <= programme.start:
            stop = programme.start + timedelta(minutes=30)

        node = ET.Element(
            "programme",
            {
                "start": xmltv_timestamp(programme.start),
                "stop": xmltv_timestamp(stop),
                "channel": source.tvg_id,
            },
        )
        title = ET.SubElement(node, "title", {"lang": "hu"})
        title.text = programme.title
        root.append(node)


def remove_channel(root: ET.Element, tvg_id: str) -> None:
    for node in list(root):
        if node.tag == "channel" and (node.get("id") or "").strip() == tvg_id:
            root.remove(node)
        elif node.tag == "programme" and (node.get("channel") or "").strip() == tvg_id:
            root.remove(node)


def recalculate_coverage(coverage: dict, playlist_ids: list[str]) -> None:
    matched = [item for item in (coverage.get("matched") or []) if isinstance(item, dict)]
    by_id: dict[str, dict] = {}
    for item in matched:
        tvg_id = str(item.get("tvg_id") or "").strip()
        if tvg_id and tvg_id in playlist_ids:
            by_id[tvg_id] = item
    matched = [by_id[tvg_id] for tvg_id in playlist_ids if tvg_id in by_id]
    matched_ids = set(by_id)
    coverage["playlist_tvg_ids"] = len(playlist_ids)
    coverage["matched_tvg_ids"] = len(matched)
    coverage["mapping_coverage_percent"] = round(
        len(matched) / len(playlist_ids) * 100.0 if playlist_ids else 0.0,
        1,
    )
    coverage["matched"] = matched
    coverage["unmatched_tvg_ids"] = [tvg_id for tvg_id in playlist_ids if tvg_id not in matched_ids]

    providers: Counter[str] = Counter()
    fresh: Counter[str] = Counter()
    for item in matched:
        provider = str(item.get("provider") or "unknown")
        providers[provider] += 1
        if int(item.get("fresh_programmes") or 0) > 0:
            fresh[provider] += 1
    coverage["providers"] = dict(sorted(providers.items()))
    coverage["fresh_channels_by_provider"] = dict(sorted(fresh.items()))


def overlay_local_epg(
    *,
    playlist_path: Path,
    guide_path: Path,
    coverage_path: Path,
    report_path: Path,
    reference_date: date,
    future_days: int,
    timeout: float,
    fetcher=fetch_lines,
) -> dict:
    playlist_ids = read_playlist_tvg_ids(playlist_path)
    playlist_set = set(playlist_ids)
    guide_tree = ET.parse(guide_path)
    root = guide_tree.getroot()
    if root.tag != "tv":
        raise RuntimeError(f"Invalid XMLTV root: {root.tag!r}")

    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    already_fresh = fresh_programme_ids(root, reference_date, future_days)
    matched = [item for item in (coverage.get("matched") or []) if isinstance(item, dict)]

    results: list[dict] = []
    filled = 0
    skipped_not_in_playlist = 0
    skipped_covered = 0

    for source in sources_for(reference_date):
        item = {
            "tvg_id": source.tvg_id,
            "channel": source.name,
            "provider": source.provider,
            "source_url": source.url,
            "status": "pending",
            "programmes": 0,
        }
        results.append(item)

        if source.tvg_id not in playlist_set:
            item["status"] = "not_in_playlist"
            skipped_not_in_playlist += 1
            continue
        if source.tvg_id in already_fresh:
            item["status"] = "already_covered"
            skipped_covered += 1
            continue

        try:
            lines = fetcher(source.url, timeout)
            programmes = PARSERS[source.kind](lines, reference_date)
            programmes = [programme for programme in programmes if programme.title]
            if len(programmes) < source.minimum_programmes:
                raise RuntimeError(
                    f"parsed only {len(programmes)} programmes; expected at least {source.minimum_programmes}"
                )

            remove_channel(root, source.tvg_id)
            append_channel_programmes(root, source, programmes)
            matched = [entry for entry in matched if str(entry.get("tvg_id") or "") != source.tvg_id]
            matched.append(
                {
                    "tvg_id": source.tvg_id,
                    "provider": source.provider,
                    "provider_xmltv_id": source.tvg_id,
                    "match_type": "local_schedule_exact_id",
                    "fresh_programmes": len(programmes),
                    "source_url": source.url,
                }
            )
            coverage["matched"] = matched
            already_fresh.add(source.tvg_id)
            filled += 1
            item["status"] = "filled"
            item["programmes"] = len(programmes)
            item["first_start"] = programmes[0].start.isoformat()
            item["last_start"] = programmes[-1].start.isoformat()
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
            item["status"] = "error"
            item["error"] = f"{type(exc).__name__}: {exc}"

    recalculate_coverage(coverage, playlist_ids)
    coverage["local_overlay"] = {
        "filled_channels": filled,
        "attempted_sources": len(results),
        "report": str(report_path),
    }

    ET.indent(root, space="  ")
    guide_tree.write(guide_path, encoding="utf-8", xml_declaration=True)
    coverage_path.write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = {
        "generated_at": datetime.now(TZ).isoformat(),
        "reference_date": reference_date.isoformat(),
        "advisory_only": False,
        "policy": "Exact known playlist IDs only; local sources fill channels that lack current/future programmes in the merged guide.",
        "summary": {
            "configured_sources": len(results),
            "filled_channels": filled,
            "errors": sum(1 for item in results if item["status"] == "error"),
            "already_covered": skipped_covered,
            "not_in_playlist": skipped_not_in_playlist,
        },
        "sources": results,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        "Local EPG overlay: "
        f"{filled}/{len(results)} configured sources filled; "
        f"{report['summary']['errors']} errors, "
        f"{skipped_covered} already covered, "
        f"{skipped_not_in_playlist} not in playlist."
    )
    for item in results:
        suffix = f" ({item.get('programmes', 0)} programmes)" if item["status"] == "filled" else ""
        if item["status"] == "error":
            suffix = f" — {item.get('error')}"
        print(f"- {item['tvg_id']}: {item['status']}{suffix}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fill unresolved EPG channels from exact broadcaster/local schedule pages."
    )
    parser.add_argument("--playlist", type=Path, default=Path("public/tv.m3u"))
    parser.add_argument("--guide", type=Path, default=Path("public/guide.xml"))
    parser.add_argument("--coverage", type=Path, default=Path("public/epg-coverage.json"))
    parser.add_argument("--report", type=Path, default=Path("public/local-epg.json"))
    parser.add_argument("--reference-date", type=date.fromisoformat)
    parser.add_argument("--future-days", type=int, default=7)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    reference_date = args.reference_date or datetime.now(TZ).date()
    overlay_local_epg(
        playlist_path=args.playlist,
        guide_path=args.guide,
        coverage_path=args.coverage,
        report_path=args.report,
        reference_date=reference_date,
        future_days=max(args.future_days, 0),
        timeout=max(args.timeout, 1.0),
    )


if __name__ == "__main__":
    main()
