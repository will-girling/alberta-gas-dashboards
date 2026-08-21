"""Download TC NGTL outage tracker publications.

TC republishes the entire maintenance tracker roughly once per business
day and keeps every publication addressable:

    GET .../production/outages/publisheddates   -> list of timestamps
    GET .../production/outages/<timestamp>      -> that full publication

Same API host as CSR, GDSR and the capacity areas, and no credentials
(the app sends "Bearer undefined").

Each publication is archived verbatim under outages_raw/. That archive
is what prepare_outage_changes.py diffs to recover the change log TC
does not publish: outages appearing, extending, deepening or being
cancelled.

Because every publication is a full snapshot, re-running is safe -
already-downloaded publications are skipped.

Usage
-----
    python3 download_outages.py                # newest 10 not yet held
    python3 download_outages.py --limit 60     # newest 60
    python3 download_outages.py --all          # entire history (slow)
    python3 download_outages.py --since 2026-06-01

Be considerate with --all: publications are ~1.5 MB each and there are
several hundred. The default fetches a small batch.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path("/Users/willgirling/Desktop/NGTL Project")
RAW_DIR = PROJECT_ROOT / "outages_raw"
LOG_FILE = PROJECT_ROOT / "outage_download_log.json"

API_ROOT = "https://f51561ras5.execute-api.us-west-2.amazonaws.com/production"
DATES_URL = f"{API_ROOT}/outages/publisheddates"

# Mirrors the browser request captured from the outage map. The
# authorization header matters: the app sends the literal string
# "Bearer undefined" when it holds no token, and the publication route
# rejects requests without it with a 403 - even though /areas and
# /publisheddates do not care. It is a placeholder, not a credential.
HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "authorization": "Bearer undefined",
    "content-type": "application/json",
    "origin": "https://my.tccustomerexpress.com",
    "referer": "https://my.tccustomerexpress.com/",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
    ),
}

REQUEST_TIMEOUT = 90
PAUSE_SECONDS = 1.0          # be polite between publications
DEFAULT_LIMIT = 10


def stamp_to_filename(stamp: str) -> str:
    """'2026-08-05 21:37:58' -> 'outages_2026_08_05_21_37_58.json'."""
    cleaned = stamp.replace("-", "_").replace(":", "_").replace(" ", "_")
    return f"outages_{cleaned}.json"


def publication_url(stamp: str) -> str:
    """Build the publication URL exactly as the browser does.

    Two things matter here, both confirmed from a captured request:

    1. The route is /outages/history/<stamp>, not /outages/<stamp>.
       API Gateway answers an unmatched route with 403 rather than 404,
       so a wrong path looks like an auth failure.
    2. Only the space is percent-encoded. requests.utils.quote escapes
       the colons to %3A by default, which does not match.
    """
    return f"{API_ROOT}/outages/history/{stamp.replace(' ', '%20')}"


def fetch_json(url: str) -> dict | list | None:
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    if not response.content.strip():
        return None
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"publications to fetch (default {DEFAULT_LIMIT})")
    parser.add_argument("--all", action="store_true",
                        help="fetch every publication available")
    parser.add_argument("--since", type=str, default=None,
                        help="only publications on/after this date, YYYY-MM-DD")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Fetching publication list from {DATES_URL} ...")
    payload = fetch_json(DATES_URL)
    stamps = payload.get("data") if isinstance(payload, dict) else payload
    if not stamps:
        raise SystemExit("No publication dates returned.")
    print(f"  {len(stamps)} publications available, "
          f"{stamps[-1]} to {stamps[0]}")

    if args.since:
        stamps = [s for s in stamps if s[:10] >= args.since]
        print(f"  {len(stamps)} on/after {args.since}")

    wanted = stamps if args.all else stamps[:max(args.limit, 0)]

    todo = [s for s in wanted if not (RAW_DIR / stamp_to_filename(s)).exists()]
    have = len(wanted) - len(todo)
    print(f"  {have} already held, {len(todo)} to download\n")

    downloaded, empty, failed = 0, [], []
    for index, stamp in enumerate(todo, start=1):
        destination = RAW_DIR / stamp_to_filename(stamp)
        url = publication_url(stamp)
        if index == 1:
            print(f"  using URL form: {url}\n")
        try:
            data = fetch_json(url)
        except Exception as exc:
            print(f"  [{index}/{len(todo)}] {stamp}  FAILED: {exc}")
            failed.append({"published": stamp, "error": str(exc)})
            if index == 1:
                # Nothing is gained by hammering a route that rejected the
                # very first request; stop and report instead.
                print("\n  First request failed - stopping rather than "
                      "retrying the rest.\n  Headers sent: "
                      f"{sorted(HEADERS)}")
                break
            continue

        records = data.get("data") if isinstance(data, dict) else data
        if not records:
            # Some historic publications come back empty; record and move on
            # rather than writing a file that looks like a real snapshot.
            print(f"  [{index}/{len(todo)}] {stamp}  empty, skipped")
            empty.append(stamp)
            time.sleep(PAUSE_SECONDS)
            continue

        destination.write_text(json.dumps(data), encoding="utf-8")
        size_kb = destination.stat().st_size / 1024
        print(f"  [{index}/{len(todo)}] {stamp}  {len(records)} rows, "
              f"{size_kb:,.0f} KB")
        downloaded += 1
        time.sleep(PAUSE_SECONDS)

    held = sorted(p.name for p in RAW_DIR.glob("outages_*.json"))
    LOG_FILE.write_text(json.dumps({
        "run_finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "publications_available": len(stamps),
        "downloaded_this_run": downloaded,
        "empty_publications": empty,
        "failures": failed,
        "publications_held": len(held),
        "newest_held": held[-1] if held else None,
    }, indent=1), encoding="utf-8")

    print(f"\ndownloaded {downloaded}, archive now holds {len(held)} "
          f"publications")
    if empty:
        print(f"  {len(empty)} returned empty and were skipped")
    if failed:
        print(f"  {len(failed)} failed - see {LOG_FILE.name}")
    print(f"\nNext: python3 prepare_outage_changes.py")


if __name__ == "__main__":
    main()
