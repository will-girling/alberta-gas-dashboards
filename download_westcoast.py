"""Download Westcoast Energy (BC Pipeline) informational postings.

Why this matters for AECO/Station 2
-----------------------------------
NGTL tells you what is happening in Alberta. Westcoast is the BC system
that sets Station 2, and its critical notices name exactly the points
that price it - "Huntingdon/Station 2 South Capacity", "Fort St John
Mainline to Station 2 (Station #1 Westbound)", "Sunset Creek
Interconnect". Those are capacity constraint notices on the path that
competes with NGTL for NEBC supply.

Source
------
Enbridge's informational postings, a server-rendered ASP site:

    https://infopost.enbridge.com/infopost/NoticesList.asp?pipe=WE&type=CRI

The landing page (WEHome.asp) is only a frameset shell and carries no
data - the notice list is a separate document, which is why it has to be
requested directly.

The site returns nothing to a bare request; it needs browser-like
headers, the same as TC's API. Nothing here is authenticated.

Output
------
westcoast_raw/notices_<type>_<timestamp>.html   raw pages, kept immutable
processed/westcoast_notices.csv                 parsed notices

Notice types
------------
CRI is critical notices (capacity constraints, force majeure). Other
codes exist on the site; add them to NOTICE_TYPES once confirmed rather
than guessing, since a wrong code returns an empty page rather than an
error.

Run
---
    python3 download_westcoast.py
"""

from __future__ import annotations

import html as html_module
import re
import time
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path("/Users/willgirling/Desktop/NGTL Project")
RAW_DIR = PROJECT_ROOT / "westcoast_raw"
OUTPUT = PROJECT_ROOT / "processed" / "westcoast_notices.csv"

BASE = "https://infopost.enbridge.com/infopost/NoticesList.asp"
PIPE = "WE"

# Confirmed from a captured browser request. Others may exist.
NOTICE_TYPES = {
    "CRI": "Critical",
}

HEADERS = {
    "accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    ),
    "accept-language": "en-US,en;q=0.9",
    "referer": "https://infopost.enbridge.com/infopost/WEHome.asp?Pipe=WE",
    "upgrade-insecure-requests": "1",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
    ),
}

REQUEST_TIMEOUT = 60

# Points whose notices bear on the AECO/Station 2 relationship. Used to
# flag rows, not to filter them - everything is kept.
STATION_2_TERMS = ("station 2", "huntingdon", "sumas", "fort st john")


def fetch(notice_type: str) -> str:
    params = {"pipe": PIPE, "type": notice_type}
    response = requests.get(
        BASE, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.text


class TableReader(HTMLParser):
    """Minimal table extractor using only the standard library.

    pandas.read_html needs lxml or bs4, neither of which the project
    otherwise requires. The page is a single plain table, so parsing it
    directly avoids adding a dependency for one file.

    Cell links are kept: each Subject links to NoticeListDetail.asp,
    which is where the actual constrained capacity figure lives.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.links: list[list[str]] = []
        self._row: list[str] | None = None
        self._row_links: list[str] = []
        self._cell: list[str] | None = None
        self._cell_link = ""

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row, self._row_links = [], []
        elif tag in ("td", "th"):
            self._cell, self._cell_link = [], ""
        elif tag == "a" and self._cell is not None:
            href = dict(attrs).get("href", "")
            if href:
                self._cell_link = href

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            self._row.append(text)
            self._row_links.append(self._cell_link)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(cell for cell in self._row):
                self.rows.append(self._row)
                self.links.append(self._row_links)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse(html: str) -> pd.DataFrame:
    """Pull the notice table out of the page."""
    reader = TableReader()
    reader.feed(html_module.unescape(html))

    if len(reader.rows) < 2:
        return pd.DataFrame()

    header, *body = reader.rows
    _, *body_links = reader.links

    width = len(header)
    body = [row[:width] + [""] * (width - len(row)) for row in body]

    table = pd.DataFrame(body, columns=[str(c).strip() for c in header])

    # Keep the notice key so detail pages can be fetched later.
    keys = []
    for row_links in body_links:
        key = ""
        for link in row_links:
            match = re.search(r"strKey1=(\d+)", link or "")
            if match:
                key = match.group(1)
                break
        keys.append(key)
    table["notice_key"] = keys[:len(table)]
    table["detail_url"] = [
        (f"https://infopost.enbridge.com/infopost/NoticeListDetail.asp"
         f"?strKey1={k}&type=CRI&Embed=2&pipe={PIPE}") if k else ""
        for k in table["notice_key"]
    ]

    return table


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    frames = []
    for code, label in NOTICE_TYPES.items():
        url = f"{BASE}?pipe={PIPE}&type={code}"
        print(f"Fetching {label} notices\n  {url}")

        try:
            html = fetch(code)
        except Exception as exc:
            print(f"  FAILED: {exc}")
            continue

        raw_path = RAW_DIR / f"notices_{code}_{stamp}.html"
        raw_path.write_text(html, encoding="utf-8")
        print(f"  saved raw -> {raw_path.name} ({len(html) / 1024:,.1f} KB)")

        try:
            table = parse(html)
        except ValueError as exc:
            print(f"  could not parse a table: {exc}")
            continue

        if table.empty:
            print("  no rows found")
            continue

        table["notice_type_code"] = code
        table["notice_type"] = label
        table["retrieved"] = stamp
        frames.append(table)

        print(f"  parsed {len(table)} rows")
        print(f"  columns: {list(table.columns)[:8]}")
        time.sleep(0.5)

    if not frames:
        raise SystemExit(
            "Nothing parsed. If the browser shows rows but this does not, "
            "the page shape has changed - send a fresh capture."
        )

    notices = pd.concat(frames, ignore_index=True)

    # Flag the rows that bear on Station 2 without discarding the rest.
    subject_col = next(
        (c for c in notices.columns if "subject" in c.lower()), None
    )
    if subject_col:
        subject = notices[subject_col].astype(str).str.lower()
        notices["station_2_related"] = subject.apply(
            lambda text: any(term in text for term in STATION_2_TERMS)
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    notices.to_csv(OUTPUT, index=False)

    print(f"\nwrote {len(notices)} notices -> {OUTPUT.name}")
    if subject_col:
        flagged = int(notices["station_2_related"].sum())
        print(f"  Station 2 / Huntingdon / Fort St John related: {flagged}")

    type_col = next(
        (c for c in notices.columns if c.lower().startswith("notice type")),
        None,
    )
    if type_col:
        print("\n  by notice category:")
        for value, count in notices[type_col].value_counts().items():
            print(f"    {str(value)[:44]:46} {count:4d}")


if __name__ == "__main__":
    main()
