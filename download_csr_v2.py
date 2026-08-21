from __future__ import annotations

import argparse
import asyncio
import io
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from playwright.async_api import async_playwright


PROJECT_FOLDER = Path("/Users/willgirling/Desktop/NGTL Project")
MASTER_FILE = PROJECT_FOLDER / "CSR_Master.csv"
RAW_FOLDER = PROJECT_FOLDER / "csr_raw"
CAPTURE_FILE = PROJECT_FOLDER / "csr_request_capture.json"
LOG_FILE = PROJECT_FOLDER / "csr_download_log.json"
PROFILE_DIR = PROJECT_FOLDER / ".playwright_profile_csr"


def parse_cli() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Download the latest 24 hours of NGTL Current System Report data "
            "and append new 30-minute observations to CSR_Master.csv."
        )
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Download and merge in memory but do not modify CSR_Master.csv.",
    )
    p.add_argument(
        "--no-keep-raw",
        action="store_true",
        help="Do not save the raw 24-hour CSV in csr_raw/.",
    )
    return p.parse_args()


def load_capture() -> dict:
    if not CAPTURE_FILE.exists():
        raise FileNotFoundError(
            f"Missing saved request capture: {CAPTURE_FILE}"
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
    expected = {
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

    missing = expected.difference(df.columns)
    if missing:
        raise ValueError(
            f"CSR schema changed. Missing expected columns: {sorted(missing)}"
        )


def append_master(new_df: pd.DataFrame, source_file: str, dry_run: bool) -> dict:
    if not MASTER_FILE.exists():
        raise FileNotFoundError(
            f"Expected master file does not exist: {MASTER_FILE}"
        )

    master = read_csv(MASTER_FILE)

    validate_schema(master)
    validate_schema(new_df)

    # Keep source schemas aligned. Do not add scraper metadata into the master.
    new_df = new_df.reindex(columns=master.columns)

    before_rows = len(master)

    combined = pd.concat([master, new_df], ignore_index=True)

    # Each CSR row is one complete 30-minute system snapshot, so Timestamp is
    # the natural unique key. Overlapping 24-hour pulls are intentional.
    combined = combined.drop_duplicates(
        subset=["Timestamp"],
        keep="last",
    )

    parsed_ts = pd.to_datetime(combined["Timestamp"], errors="coerce")
    combined = (
        combined.assign(_sort_ts=parsed_ts)
        .sort_values("_sort_ts", kind="stable", na_position="last")
        .drop(columns="_sort_ts")
        .reset_index(drop=True)
    )

    after_rows = len(combined)
    net_new = after_rows - before_rows

    print("\nMASTER MERGE")
    print("------------")
    print(f"Existing rows: {before_rows:,}")
    print(f"Pulled rows:   {len(new_df):,}")
    print("Dedup key:     ['Timestamp']")
    print(f"Master rows:   {after_rows:,}")
    print(f"Net new rows:  {net_new:,}")

    if dry_run:
        print("DRY RUN: CSR_Master.csv not modified.")
    else:
        # Write safely via temp file, then replace.
        temp = MASTER_FILE.with_suffix(".tmp.csv")
        combined.to_csv(temp, index=False)
        temp.replace(MASTER_FILE)
        print(f"Updated: {MASTER_FILE}")

    return {
        "existing_rows": before_rows,
        "pulled_rows": len(new_df),
        "master_rows": after_rows,
        "net_new_rows": net_new,
        "dedup_key": ["Timestamp"],
        "source_file": source_file,
    }


async def main() -> None:
    args = parse_cli()

    PROJECT_FOLDER.mkdir(parents=True, exist_ok=True)
    RAW_FOLDER.mkdir(parents=True, exist_ok=True)

    capture = load_capture()

    method = capture.get("method", "GET")
    url = capture["url"]
    headers = capture.get("headers", {})
    post_data = capture.get("post_data")

    started = datetime.now()

    try:
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=True,
            )

            try:
                response = await context.request.fetch(
                    url,
                    method=method,
                    headers=headers,
                    data=post_data,
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
                raw_name = f"CSR_Last24Hours_{stamp}.csv"
                raw_path = RAW_FOLDER / raw_name

                if not args.no_keep_raw:
                    raw_path.write_bytes(body)
                    print(f"Saved raw pull: {raw_path}")

                print(f"Parsed columns: {list(new_df.columns)}")

                merge = append_master(
                    new_df=new_df,
                    source_file=raw_name,
                    dry_run=args.dry_run,
                )

            finally:
                await context.close()

        result = {
            "success": True,
            "downloaded_at": datetime.now().isoformat(timespec="seconds"),
            "raw_file": None if args.no_keep_raw else str(raw_path),
            **merge,
            "run_started": started.isoformat(timespec="seconds"),
            "run_finished": datetime.now().isoformat(timespec="seconds"),
            "dry_run": args.dry_run,
        }

        LOG_FILE.write_text(
            json.dumps(result, indent=2),
            encoding="utf-8",
        )

        print(f"\nLog: {LOG_FILE}")
        print("CSR update completed successfully.")

    except Exception as exc:
        LOG_FILE.write_text(
            json.dumps(
                {
                    "success": False,
                    "run_started": started.isoformat(timespec="seconds"),
                    "run_finished": datetime.now().isoformat(timespec="seconds"),
                    "error": repr(exc),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        raise


if __name__ == "__main__":
    asyncio.run(main())
