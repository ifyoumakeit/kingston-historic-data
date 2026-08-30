#!/usr/bin/env python3
"""Walk the City of Kingston "Agendas & Minutes" ASP.NET cascade and emit an
index of every HLPC agenda / minutes / audio document.

The city site (QScend CMS) exposes documents only through chained __doPostBack
dropdowns on https://www.kingston-ny.gov/Agendas:

    folder 10476 (Agendas & Minutes)
      -> 16128  Historic Landmarks Preservation Commission
           -> 16479 hlpc_agendas / 16481 hlpc_minutes / 18621 hlpc_meeting_audio
                -> <year folder>
                     -> document links under /filestorage/...

Each selection is a full-page postback carrying __VIEWSTATE forward, so the
walk has to be sequential.
"""

import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://www.kingston-ny.gov"
URL = f"{BASE}/Agendas"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

ROOT_FOLDER = "10476"          # Agendas & Minutes
HLPC = "16128"                 # Historic Landmarks Preservation Commission
SECTIONS = {                   # child folder id -> document kind
    "16479": "agenda",
    "16481": "minutes",
    "18621": "audio",
}

OUT = Path(__file__).resolve().parent.parent / "data" / "index.json"


class Cascade:
    """Sequential postback driver for the QScend folder browser."""

    def __init__(self):
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor()
        )
        self.page = self._request()

    def _request(self, data=None):
        headers = {"User-Agent": UA, "Referer": URL}
        body = None
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            body = urllib.parse.urlencode(data).encode()
        for attempt in range(3):
            try:
                with self.opener.open(
                    urllib.request.Request(URL, data=body, headers=headers), timeout=60
                ) as resp:
                    return resp.read().decode("utf-8", "replace")
            except Exception as exc:  # transient CDN hiccups are common here
                if attempt == 2:
                    raise
                print(f"  retry after {exc}", file=sys.stderr)
                time.sleep(2 * (attempt + 1))

    @staticmethod
    def _hidden(page):
        state = {}
        for tag in re.finditer(r'<input[^>]*type="hidden"[^>]*>', page):
            name = re.search(r'name="([^"]+)"', tag.group(0))
            value = re.search(r'value="([^"]*)"', tag.group(0))
            if name:
                state[name.group(1)] = html.unescape(value.group(1)) if value else ""
        return state

    def select(self, path):
        """Re-walk the cascade from a fresh page, selecting folder ids in order.

        `path` is a list of (select_id, value) pairs, outermost first.
        """
        self.page = self._request()
        chosen = {}
        for select_id, value in path:
            state = self._hidden(self.page)
            state.update(chosen)
            state["__EVENTTARGET"] = f"FB$F_{select_id}"
            state["__EVENTARGUMENT"] = ""
            state[f"FB$F_{select_id}"] = value
            chosen[f"FB$F_{select_id}"] = value
            self.page = self._request(state)
        return self.page

    def options(self, select_id):
        match = re.search(
            rf'<select name="FB\$F_{re.escape(select_id)}"[^>]*>(.*?)</select>',
            self.page,
            re.S,
        )
        if not match:
            return []
        return [
            (value, html.unescape(label).strip())
            for value, label in re.findall(
                r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)</option>', match.group(1)
            )
            if value
        ]

    def documents(self):
        seen = {}
        for href, label in re.findall(
            r'href="([^"]*/filestorage/[^"]*)"[^>]*>([^<]*)<', self.page
        ):
            url = urllib.parse.urljoin(BASE, html.unescape(href))
            seen.setdefault(url, html.unescape(label).strip())
        return seen


# Filenames are wildly inconsistent across 20 years. Cover the common shapes.
DATE_PATTERNS = [
    # 2025.6.5_hlpc_minutes / 2014.10.2_hlpc_min
    (r"(?<!\d)(20\d{2})[._-](\d{1,2})[._-](\d{1,2})(?!\d)", ("y", "m", "d")),
    # HLPC_12.03.2020_GTM_Minutes / 08.1.2019
    (r"(?<!\d)(\d{1,2})[._-](\d{1,2})[._-](20\d{2})(?!\d)", ("m", "d", "y")),
    # July_10_2019_HLPC_DRAFT_MINUTES
    (
        r"(?i)(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[._\s-]+"
        r"(\d{1,2})[a-z]{0,2}[._,\s-]+(20\d{2})",
        ("mon", "d", "y"),
    ),
    # HAC_HLPC_Meeting_Minutes_May_2022  (month + year only)
    (
        r"(?i)(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[._\s-]+(20\d{2})",
        ("mon", "y"),
    ),
]

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_date(name, fallback_year=None):
    """Return (iso_date, is_exact). Falls back to the year folder when needed."""
    stem = urllib.parse.unquote(name)
    for pattern, order in DATE_PATTERNS:
        match = re.search(pattern, stem)
        if not match:
            continue
        parts = dict(zip(order, match.groups()))
        year = int(parts["y"])
        month = MONTHS[parts["mon"][:3].lower()] if "mon" in parts else int(parts["m"])
        day = int(parts.get("d", 0) or 0)
        if not 1 <= month <= 12 or day > 31:
            continue
        if day:
            return f"{year:04d}-{month:02d}-{day:02d}", True
        return f"{year:04d}-{month:02d}", False
    if fallback_year:
        return str(fallback_year), False
    return None, False


def main():
    cascade = Cascade()
    records = []

    for section_id, kind in SECTIONS.items():
        print(f"section {kind} ({section_id})", file=sys.stderr)
        cascade.select([(ROOT_FOLDER, HLPC), (HLPC, section_id)])

        # Documents can sit directly in the section folder as well as in year folders.
        loose = cascade.documents()
        years = cascade.options(section_id)

        buckets = [(None, None, loose)]
        for year_id, year_label in years:
            print(f"  {year_label}", file=sys.stderr)
            cascade.select(
                [(ROOT_FOLDER, HLPC), (HLPC, section_id), (section_id, year_id)]
            )
            buckets.append((year_id, year_label, cascade.documents()))
            time.sleep(0.3)

        for year_id, year_label, docs in buckets:
            year_hint = None
            if year_label:
                m = re.search(r"(20\d{2})", year_label)
                year_hint = int(m.group(1)) if m else None
            for url, label in docs.items():
                filename = url.rsplit("/", 1)[-1]
                date, exact = parse_date(label) 
                if not date:
                    date, exact = parse_date(filename, year_hint)
                records.append(
                    {
                        "kind": kind,
                        "date": date,
                        "date_exact": exact,
                        "year_folder": year_label,
                        "label": label,
                        "filename": urllib.parse.unquote(filename),
                        "url": url,
                    }
                )

    records.sort(key=lambda r: (r["date"] or "", r["kind"], r["filename"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(records, indent=2) + "\n")

    by_kind = {}
    undated = 0
    for r in records:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
        if not r["date_exact"]:
            undated += 1
    print(f"\n{len(records)} documents -> {OUT}", file=sys.stderr)
    print(f"  by kind: {by_kind}", file=sys.stderr)
    print(f"  without an exact date: {undated}", file=sys.stderr)


if __name__ == "__main__":
    main()
