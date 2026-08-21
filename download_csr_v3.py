from __future__ import annotations

import argparse
import asyncio
import io
import json
import math
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd
from playwright.async_api import async_playwright


PROJECT_FOLDER = Path("/Users/willgirling/Desktop/NGTL Project")
MASTER_FILE = PROJECT_FOLDER / "CSR_Master.csv"
RAW_FOLDER = PROJECT_FOLDER / "csr_raw"
CAPTURE_FILE = PROJECT_FOLDER / "csr_request_capture.json"
LOG_FILE = PROJECT_FOLDER / "csr_download_log.json"
PROFILE_DIR = PROJECT_FOLDER / ".playwright_profile_csr"

MAX_DURATION_DAYS = 7

EXPECTED_COLUMNS = {
    "Timestamp",
    "NGTL-Field Receipts",
    "Groundbirch East Receipt",
    "Gordondale Receipt",
    "Total Receipts",
    "Intraprovincial Demand",
    "Empress Border Flow",
    "Mcneil Border Flow",
    "Alberta-BC Border Flow",
    "Willow Valley Interconnect",
    "Total Deliveries",
    "Current Linepack",
    "Linepack 4Hr Roc",
    "Net Storage Flow",
    "Flow Differential",
    "Linepack Target",
}


def parse_cli() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Update CSR_Master.csv from TC Energy Current System Report. "
            "Automatically requests enough history to catch up, up to 7 days."
        )
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Download/merge in memory but do not modify CSR_Master.csv.",
    )
    p.add_argument(
        "--no-keep-raw",
        action="store_true",
        help="Do not retain the downloaded CSR CSV in csr_raw/.",
    )
    p.add_argument(
        "--duration",
        type=int,
        choices=range(1, MAX_DURATION_DAYS + 1),
        metavar="1-7",
        help="Override automatic catch-up and request exactly N days.",
    )
    return p.parse_args()


def load_capture() -> dict:
    if not CAPTURE_FILE.exists():
        raise FileNotFoundError(
            f"Missing request capture: {CAPTURE_FILE}. "
            "Run the previously tested capture script first."
        )
    return json.loads(CAPTURE_FILE.read_text(encoding="utf-8"))


def read_csv(source: Path | bytes) -> pd.DataFrame:
    if isinstance(source, Path):
        df = pd.read_csv(source)
    else:
        df = pd.read_csv(io.BytesIO(source))

    df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
    return df.dropna(how="all").reset_index(drop=True)


def validate_schema(df: pd.DataFrame) -> None:
    missing = EXPECTED_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError(
            "CSR schema changed or wrong report was returned. "
            f"Missing columns: {sorted(missing)}"
        )


def latest_master_timestamp() -> pd.Timestamp:
    if not MASTER_FILE.exists():
        raise FileNotFoundError(f"Missing master file: {MASTER_FILE}")

    master = read_csv(MASTER_FILE)
    validate_schema(master)

    timestamps = pd.to_datetime(master["Timestamp"], errors="coerce")
    latest = timestamps.max()

    if pd.isna(latest):
        raise ValueError("CSR_Master.csv contains no valid Timestamp values.")

    return latest


def choose_duration_days(now: datetime, latest: pd.Timestamp) -> tuple[int, float, bool]:
    latest_dt = latest.to_pydatetime()
    gap_hours = max(0.0, (now - latest_dt).total_seconds() / 3600)

    # Request enough whole days to cover the gap. A normal 6-hourly run remains
    # duration=1. If the laptop has been unavailable for >24h, duration grows.
    required_days = max(1, math.ceil(gap_hours / 24))
    capped = required_days > MAX_DURATION_DAYS
    duration = min(required_days, MAX_DURATION_DAYS)

    return duration, gap_hours, capped


def set_duration(url: str, duration_days: int) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["duration"] = str(duration_days)

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )


def append_master(new_df: pd.DataFrame, dry_run: bool) -> dict:
    master = read_csv(MASTER_FILE)
    validate_schema(master)
    validate_schema(new_df)

    # Preserve the master schema exactly.
    new_df = new_df.reindex(columns=master.columns)

    before = len(master)
    combined = pd.concat([master, new_df], ignore_index=True)

    # One CSR row = one full system snapshot. Timestamp is the unique observation key.
    combined = combined.drop_duplicates(subset=["Timestamp"], keep="last")

    combined["_sort_ts"] = pd.to_datetime(
        combined["Timestamp"],
        errors="coerce",
    )
    combined = (
        combined.sort_values("_sort_ts", kind="stable", na_position="last")
        .drop(columns="_sort_ts")
        .reset_index(drop=True)
    )

    after = len(combined)
    net_new = after - before

    latest_after = pd.to_datetime(
        combined["Timestamp"], errors="coerce"
    ).max()

    print("\nMASTER MERGE")
    print("------------")
    print(f"Existing rows: {before:,}")
    print(f"Pulled rows:   {len(new_df):,}")
    print("Dedup key:     ['Timestamp']")
    print(f"Master rows:   {after:,}")
    print(f"Net new rows:  {net_new:,}")
    print(f"Latest obs:    {latest_after}")

    if dry_run:
        print("DRY RUN: CSR_Master.csv not modified.")
    else:
        temp = MASTER_FILE.with_suffix(".tmp.csv")
        combined.to_csv(temp, index=False)
        temp.replace(MASTER_FILE)
        print(f"Updated: {MASTER_FILE}")

    return {
        "existing_rows": before,
        "pulled_rows": len(new_df),
        "master_rows": after,
        "net_new_rows": net_new,
        "latest_observation": str(latest_after),
        "dedup_key": ["Timestamp"],
    }


async def main() -> None:
    args = parse_cli()

    PROJECT_FOLDER.mkdir(parents=True, exist_ok=True)
    RAW_FOLDER.mkdir(parents=True, exist_ok=True)

    started = datetime.now()

    try:
        capture = load_capture()
        latest_before = latest_master_timestamp()
        now = datetime.now()

        auto_duration, gap_hours, capped = choose_duration_days(
            now=now,
            latest=latest_before,
        )
        duration = args.duration or auto_duration

        print("\nCSR CATCH-UP CHECK")
        print("------------------")
        print(f"Latest master observation: {latest_before}")
        print(f"Current local time:         {now:%Y-%m-%d %H:%M:%S}")
        print(f"Gap:                        {gap_hours:.2f} hours")
        print(f"CSR duration requested:     {duration} day(s)")

        if capped and args.duration is None:
            print(
                "WARNING: The master is more than 7 days behind. "
                "The script will request the maximum 7 days, but observations "
                "older than TC Energy's available window may be unrecoverable."
            )

        request_url = set_duration(capture["url"], duration)

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=True,
            )

            try:
                response = await context.request.fetch(
                    request_url,
                    method=capture.get("method", "GET"),
                    headers=capture.get("headers", {}),
                    data=capture.get("post_data"),
                    timeout=60_000,
                    fail_on_status_code=False,
                )

                if not response.ok:
                    raise RuntimeError(
                        f"HTTP {response.status}: {response.status_text}"
                    )

                body = await response.body()
                new_df = read_csv(body)
                validate_schema(new_df)

                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                raw_name = f"CSR_Last{duration}Day_{stamp}.csv"
                raw_path = RAW_FOLDER / raw_name

                if not args.no_keep_raw:
                    raw_path.write_bytes(body)
                    print(f"Saved raw pull: {raw_path}")

                merge = append_master(
                    new_df=new_df,
                    dry_run=args.dry_run,
                )

            finally:
                await context.close()

        result = {
            "success": True,
            "run_started": started.isoformat(timespec="seconds"),
            "run_finished": datetime.now().isoformat(timespec="seconds"),
            "latest_before": str(latest_before),
            "gap_hours_before_run": gap_hours,
            "duration_days_requested": duration,
            "duration_was_capped": capped,
            "raw_file": None if args.no_keep_raw else str(raw_path),
            "dry_run": args.dry_run,
            **merge,
        }

        LOG_FILE.write_text(
            json.dumps(result, indent=2),
            encoding="utf-8",
        )

        print(f"\nLog: {LOG_FILE}")
        print("CSR update completed successfully.")

    except Exception as exc:
        failure = {
            "success": False,
            "run_started": started.isoformat(timespec="seconds"),
            "run_finished": datetime.now().isoformat(timespec="seconds"),
            "error": repr(exc),
        }

        LOG_FILE.write_text(
            json.dumps(failure, indent=2),
            encoding="utf-8",
        )
        print(f"\nCSR UPDATE FAILED: {exc}")
        print(f"Failure log: {LOG_FILE}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
