from pathlib import Path


p = Path("local_epg.py")
text = p.read_text(encoding="utf-8")

text = text.replace(
    "from pathlib import Path\nfrom urllib.error import HTTPError, URLError\n",
    "from pathlib import Path\nfrom time import sleep\nfrom urllib.error import HTTPError, URLError\n",
    1,
)

old = '''def fetch_lines(url: str, timeout: float = 15.0) -> list[str]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Cache-Control": "no-cache",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(750_000)
        charset = response.headers.get_content_charset() or "utf-8"
    return html_lines(raw.decode(charset, errors="replace"))
'''
new = '''def fetch_lines(url: str, timeout: float = 15.0) -> list[str]:
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
'''
if old not in text:
    raise SystemExit("fetch_lines block not found")
text = text.replace(old, new, 1)

marker = '''def slice_section(lines: list[str], start_predicate, end_predicate) -> list[str]:
    start = find_index(lines, start_predicate)
    if start is None:
        return []
    end = find_index(lines, end_predicate, start + 1)
    return lines[start + 1 : end if end is not None else len(lines)]
'''
replacement = marker + '''

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
'''
if marker not in text:
    raise SystemExit("slice_section block not found")
text = text.replace(marker, replacement, 1)

old = '''def parse_eger(lines: list[str], reference_date: date) -> list[Programme]:
    variants = hu_long_date_variants(reference_date)
    section = slice_section(
        lines,
        lambda value: folded(value) in variants,
        looks_like_hu_dated_heading,
    )
    return parse_entries(section, reference_date, max_entries=50)
'''
new = '''def parse_eger(lines: list[str], reference_date: date) -> list[Programme]:
    variants = {value.rstrip(".") for value in hu_long_date_variants(reference_date)}
    section = best_section(
        lines,
        lambda value: folded(value).rstrip(".") in variants,
        looks_like_hu_dated_heading,
    )
    return parse_entries(section, reference_date, max_entries=50)
'''
if old not in text:
    raise SystemExit("parse_eger block not found")
text = text.replace(old, new, 1)

old = '''def parse_ozd(lines: list[str], reference_date: date) -> list[Programme]:
    needle = folded(reference_date.strftime("%Y. %m. %d."))
    start = find_index(lines, lambda value: folded(value) == needle)
    if start is None:
        return []
    end = find_index(
        lines,
        lambda value: bool(NUMERIC_DATE_RE.match(value.replace(" ", ""))),
        start + 1,
    )
    section = lines[start + 1 : end if end is not None else start + 80]
    return parse_entries(section, reference_date, max_entries=30)
'''
new = '''def parse_ozd(lines: list[str], reference_date: date) -> list[Programme]:
    needle = folded(reference_date.strftime("%Y. %m. %d.")).rstrip(".")
    section = best_section(
        lines,
        lambda value: folded(value).rstrip(".") == needle,
        lambda value: bool(NUMERIC_DATE_RE.match(value.replace(" ", ""))),
    )
    return parse_entries(section, reference_date, max_entries=30)
'''
if old not in text:
    raise SystemExit("parse_ozd block not found")
text = text.replace(old, new, 1)
p.write_text(text, encoding="utf-8")


t = Path("tests/test_local_epg.py")
tests = t.read_text(encoding="utf-8")
tests = tests.replace(
    "    parse_cegled,\n    parse_entries,\n    parse_tvmustra,\n",
    "    parse_cegled,\n    parse_eger,\n    parse_entries,\n    parse_ozd,\n    parse_tvmustra,\n",
    1,
)
insert_tests = '''
    def test_dated_parsers_choose_real_schedule_block(self):
        eger = parse_eger(
            [
                "Kedd: 2026. augusztus 11",
                "Szerda: 2026. augusztus 12",
                "Kedd: 2026. augusztus 11",
                "8:00 Tv Eger szignál",
                "8:01 HírAdás Plusz",
                "18:00 Híradó",
                "Szerda: 2026. augusztus 12",
            ],
            date(2026, 8, 11),
        )
        self.assertEqual(len(eger), 3)

        ozd = parse_ozd(
            [
                "2026. 08. 11",
                "2026. 08. 12",
                "2026. 08. 11",
                "18:25 A szomszéd vár ism.",
                "19:00 Ózdi Krónika",
                "19:30 Forgószínpad",
                "2026. 08. 12",
            ],
            date(2026, 8, 11),
        )
        self.assertEqual(len(ozd), 3)
'''
marker = '\n\nif __name__ == "__main__":\n'
if marker not in tests:
    raise SystemExit("test insertion marker not found")
tests = tests.replace(marker, insert_tests + marker, 1)
t.write_text(tests, encoding="utf-8")

print("Patched local EPG retries and robust dated-section selection.")
