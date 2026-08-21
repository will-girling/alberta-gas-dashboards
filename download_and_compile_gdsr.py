from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pandas as pd

from playwright.async_api import (
    BrowserContext,
    Playwright,
    Request,
    Response,
    async_playwright,
)


SITE_URL = "https://my.tccustomerexpress.com/#GasDaySummaryReport"
PROJECT_FOLDER = Path("/Users/willgirling/Desktop/NGTL Project")
OUTPUT_FOLDER = PROJECT_FOLDER / "gdsr"
CAPTURE_FILE = PROJECT_FOLDER / "gdsr_request_capture.json"
PROCESSED_FOLDER = PROJECT_FOLDER / "processed"
FLOW_OUTPUT = PROCESSED_FOLDER / "ngtl_daily_flows.csv"
METRIC_OUTPUT = PROCESSED_FOLDER / "ngtl_operational_metrics.csv"

EXPECTED_CSV_HEADERS = {
    "Item",
    "Prorated",
    "Extrapolated",
    "NextDayNominated",
}


@dataclass
class CapturedRequest:
    method: str
    url: str
    headers: dict[str, str]
    post_data: str | None
    selected_date: str
    date_token: str
    date_format: str


def parse_cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Capture the TC Energy Gas Day Summary CSV request once, "
            "then replay it over a date range."
        )
    )
    parser.add_argument(
        "--start",
        default="2026-07-15",
        help="First gas day to download, YYYY-MM-DD.",
    )
    parser.add_argument(
        "--end",
        default=date.today().isoformat(),
        help="Last gas day to download, YYYY-MM-DD.",
    )
    parser.add_argument(
        "--capture-date",
        default="2026-07-15",
        help=(
            "Date you will manually select during request capture, YYYY-MM-DD. "
            "Use a distinctive date in the requested range."
        ),
    )
    parser.add_argument(
        "--recapture",
        action="store_true",
        help="Ignore any saved request capture and capture a fresh request.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite raw files that already exist.",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=1.0,
        help="Seconds to wait between requests.",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Download raw CSVs but do not rebuild processed datasets.",
    )
    parser.add_argument(
        "--compile-only",
        action="store_true",
        help="Skip downloading and only rebuild processed datasets from gdsr/.",
    )
    return parser.parse_args()


def iter_dates(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def possible_date_tokens(day: date) -> list[tuple[str, str]]:
    """Likely date encodings used in URLs or request payloads."""
    return [
        (day.strftime("%Y-%m-%d"), "YYYY-MM-DD"),
        (day.strftime("%Y%m%d"), "YYYYMMDD"),
        (day.strftime("%m/%d/%Y"), "MM/DD/YYYY"),
        (day.strftime("%m-%d-%Y"), "MM-DD-YYYY"),
        (day.strftime("%Y/%m/%d"), "YYYY/MM/DD"),
        (day.strftime("%b %d, %Y"), "MMM DD, YYYY"),
        (day.strftime("%B %d, %Y"), "MMMM DD, YYYY"),
        (day.strftime("%Y-%b-%d"), "YYYY-MMM-DD"),
    ]


def format_date(day: date, format_name: str) -> str:
    formats = {
        "YYYY-MM-DD": "%Y-%m-%d",
        "YYYYMMDD": "%Y%m%d",
        "MM/DD/YYYY": "%m/%d/%Y",
        "MM-DD-YYYY": "%m-%d-%Y",
        "YYYY/MM/DD": "%Y/%m/%d",
        "MMM DD, YYYY": "%b %d, %Y",
        "MMMM DD, YYYY": "%B %d, %Y",
        "YYYY-MMM-DD": "%Y-%b-%d",
    }
    return day.strftime(formats[format_name])


def identify_date_token(
    url: str,
    post_data: str | None,
    selected_day: date,
) -> tuple[str, str] | None:
    haystacks = [
        url,
        unquote(url),
        post_data or "",
        unquote(post_data or ""),
    ]

    for token, format_name in possible_date_tokens(selected_day):
        if any(token in haystack for haystack in haystacks):
            return token, format_name

    return None


def looks_like_csv_response(response: Response) -> bool:
    headers = {k.lower(): v.lower() for k, v in response.headers.items()}
    content_type = headers.get("content-type", "")
    disposition = headers.get("content-disposition", "")
    url = response.url.lower()

    return (
        "csv" in content_type
        or ".csv" in disposition
        or ".csv" in url
        or "export" in url
        or "download" in url
    )


async def response_has_expected_csv(response: Response) -> bool:
    if not looks_like_csv_response(response):
        return False

    try:
        body = await response.body()
    except Exception:
        return False

    sample = body[:5000].decode("utf-8-sig", errors="ignore")
    return EXPECTED_CSV_HEADERS.issubset(
        {column.strip().strip('"') for column in sample.splitlines()[0].split(",")}
    )


async def capture_request(
    playwright: Playwright,
    capture_day: date,
) -> CapturedRequest:
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    # Persistent profile lets the browser preserve normal site state/cookies.
    profile_dir = PROJECT_FOLDER / ".playwright_profile"
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=False,
        accept_downloads=True,
    )

    page = context.pages[0] if context.pages else await context.new_page()

    candidate_responses: list[Response] = []
    captured_future: asyncio.Future[CapturedRequest] = (
        asyncio.get_running_loop().create_future()
    )

    async def inspect_response(response: Response) -> None:
        candidate_responses.append(response)

        if captured_future.done():
            return

        if not await response_has_expected_csv(response):
            return

        request = response.request
        match = identify_date_token(
            request.url,
            request.post_data,
            capture_day,
        )

        if match is None:
            print(
                "\nA CSV response was detected, but the selected date was not "
                "found in its URL or payload."
            )
            return

        date_token, date_format = match

        # Do not save transient browser-only headers that commonly break replay.
        excluded_headers = {
            "content-length",
            "host",
            "connection",
            "cookie",
            "sec-fetch-dest",
            "sec-fetch-mode",
            "sec-fetch-site",
            "sec-ch-ua",
            "sec-ch-ua-mobile",
            "sec-ch-ua-platform",
        }
        replay_headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in excluded_headers
        }

        capture = CapturedRequest(
            method=request.method,
            url=request.url,
            headers=replay_headers,
            post_data=request.post_data,
            selected_date=capture_day.isoformat(),
            date_token=date_token,
            date_format=date_format,
        )
        captured_future.set_result(capture)

    page.on(
        "response",
        lambda response: asyncio.create_task(inspect_response(response)),
    )

    await page.goto(SITE_URL, wait_until="domcontentloaded")

    print("\nREQUEST CAPTURE")
    print("---------------")
    print(
        f"1. In the opened browser, select {capture_day.strftime('%b %d, %Y')}."
    )
    print("2. Keep the report set to NGTL and Imperial.")
    print("3. Generate the report if required.")
    print("4. Click the CSV download button once.")
    print("5. Return to Terminal and wait for capture confirmation.\n")

    try:
        capture = await asyncio.wait_for(captured_future, timeout=300)
    except asyncio.TimeoutError as exc:
        diagnostics = []
        for response in candidate_responses[-100:]:
            diagnostics.append(
                {
                    "status": response.status,
                    "url": response.url,
                    "content_type": response.headers.get("content-type"),
                    "content_disposition": response.headers.get(
                        "content-disposition"
                    ),
                    "request_method": response.request.method,
                    "request_post_data": response.request.post_data,
                }
            )

        diagnostic_path = PROJECT_FOLDER / "gdsr_network_diagnostics.json"
        diagnostic_path.write_text(
            json.dumps(diagnostics, indent=2),
            encoding="utf-8",
        )
        raise RuntimeError(
            "No replayable CSV request was captured within five minutes. "
            f"Diagnostics were saved to {diagnostic_path}."
        ) from exc
    finally:
        await context.close()

    CAPTURE_FILE.write_text(
        json.dumps(asdict(capture), indent=2),
        encoding="utf-8",
    )

    print(f"Captured request and saved it to:\n{CAPTURE_FILE}\n")
    return capture


def load_capture() -> CapturedRequest:
    payload = json.loads(CAPTURE_FILE.read_text(encoding="utf-8"))
    return CapturedRequest(**payload)


def substitute_date(
    capture: CapturedRequest,
    requested_day: date,
) -> tuple[str, str | None]:
    replacement = format_date(requested_day, capture.date_format)

    url = capture.url.replace(capture.date_token, replacement)
    post_data = capture.post_data

    if post_data is not None:
        post_data = post_data.replace(capture.date_token, replacement)

    return url, post_data


def validate_csv(content: bytes, requested_day: date) -> None:
    text = content.decode("utf-8-sig", errors="replace")

    if text.lstrip().lower().startswith("<!doctype html") or "<html" in text[:500].lower():
        raise ValueError("The server returned HTML rather than CSV data.")

    lines = text.splitlines()
    if not lines:
        raise ValueError("The response was empty.")

    first_row = {
        cell.strip().strip('"')
        for cell in lines[0].split(",")
    }
    missing = EXPECTED_CSV_HEADERS.difference(first_row)
    if missing:
        raise ValueError(
            f"CSV is missing expected headers: {sorted(missing)}"
        )

    requested_tokens = {
        requested_day.strftime("%Y-%b-%d"),
        requested_day.strftime("%b %d, %Y"),
        requested_day.strftime("%Y-%m-%d"),
        requested_day.strftime("%Y%m%d"),
    }

    if not any(token in text for token in requested_tokens):
        raise ValueError(
            "CSV does not appear to contain the requested gas-day date."
        )


async def download_range(
    playwright: Playwright,
    capture: CapturedRequest,
    start_day: date,
    end_day: date,
    overwrite: bool,
    pause_seconds: float,
) -> None:
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    profile_dir = PROJECT_FOLDER / ".playwright_profile"
    context: BrowserContext = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=True,
    )

    failures: list[dict[str, str]] = []
    successes = 0
    skipped = 0

    try:
        for requested_day in iter_dates(start_day, end_day):
            output_path = (
                OUTPUT_FOLDER
                / f"GdsrNGTLImperial{requested_day.strftime('%Y%m%d')}.csv"
            )

            if output_path.exists() and not overwrite:
                print(f"Skip existing: {requested_day}")
                skipped += 1
                continue

            url, post_data = substitute_date(capture, requested_day)

            try:
                response = await context.request.fetch(
                    url,
                    method=capture.method,
                    headers=capture.headers,
                    data=post_data,
                    timeout=60_000,
                    fail_on_status_code=False,
                )

                if not response.ok:
                    raise RuntimeError(
                        f"HTTP {response.status}: {response.status_text}"
                    )

                body = await response.body()
                validate_csv(body, requested_day)

                output_path.write_bytes(body)
                print(f"Downloaded: {requested_day}")
                successes += 1

            except Exception as exc:
                print(f"FAILED {requested_day}: {exc}")
                failures.append(
                    {
                        "gas_day": requested_day.isoformat(),
                        "error": str(exc),
                        "url": url,
                    }
                )

            await asyncio.sleep(pause_seconds)

    finally:
        await context.close()

    log_path = PROJECT_FOLDER / "gdsr_download_log.json"
    log_path.write_text(
        json.dumps(
            {
                "run_timestamp": datetime.now().isoformat(timespec="seconds"),
                "start": start_day.isoformat(),
                "end": end_day.isoformat(),
                "successes": successes,
                "skipped": skipped,
                "failures": failures,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\nDOWNLOAD SUMMARY")
    print("----------------")
    print(f"Successful: {successes}")
    print(f"Skipped:    {skipped}")
    print(f"Failed:     {len(failures)}")
    print(f"Log:        {log_path}")


FLOW_ITEM_MAP = {
    "EMPRESS BORDER": ("EMPRESS", "Border Flow"),
    "MCNEILL BORDER": ("MCNEILL", "Border Flow"),
    "ALBERTA-B.C. BDR": ("ALBERTA_BC", "Border Flow"),
    "WILLOW VALLEY INTERCONNECT": ("WILLOW_VALLEY", "Interconnect Flow"),
    "GORDONDALE BORDER": ("GORDONDALE", "Interconnect Flow"),
    "GROUNDBIRCH EAST": ("GROUNDBIRCH_EAST", "Interconnect Flow"),
    "*OTHER BORDERS": ("OTHER_BORDERS", "Border Flow"),
    "Intraprovincial": ("INTRAPROVINCIAL", "Internal Delivery"),
    "Total Storage + Intraprovincial": (
        "TOTAL_STORAGE_AND_INTRAPROVINCIAL",
        "System Total",
    ),
    "**Total Net Storage": ("TOTAL_NET_STORAGE", "Storage"),
    "Total Storage Deliveries": ("TOTAL_STORAGE_DELIVERIES", "Storage"),
    "Total Storage Receipts": ("TOTAL_STORAGE_RECEIPTS", "Storage"),
    "Total NGTL Deliveries": ("TOTAL_NGTL_DELIVERIES", "System Total"),
    "Total NGTL Receipts": ("TOTAL_NGTL_RECEIPTS", "System Total"),
}

OPERATIONAL_METRIC_MAP = {
    "***NGTL Field Receipts": "NGTL_FIELD_RECEIPTS",
    "End of Day Linepack": "END_OF_DAY_LINEPACK",
    "Linepack Rate of Change": "LINEPACK_RATE_OF_CHANGE",
    "Linepack Change (Last 24 hours)": "LINEPACK_CHANGE_24H",
    "Linepack Target": "LINEPACK_TARGET",
    "Tolerance": "TOLERANCE",
    "Tolerance Last Changed": "TOLERANCE_LAST_CHANGED",
    "Total SD Account (TJ)": "TOTAL_SD_ACCOUNT_TJ",
    "Total OBA Account (TJ)": "TOTAL_OBA_ACCOUNT_TJ",
}


def parse_number(value: object) -> float | None:
    if pd.isna(value):
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_report_day(value: object) -> pd.Timestamp:
    return pd.to_datetime(value, format="%Y-%b-%d", errors="coerce")


def read_report_for_compile(path: Path) -> pd.DataFrame:
    report = pd.read_csv(path, encoding="utf-8-sig")
    missing = EXPECTED_CSV_HEADERS.difference(report.columns)
    if missing:
        raise ValueError(f"Missing expected columns: {sorted(missing)}")
    report["Item"] = report["Item"].astype(str).str.strip()
    return report


def extract_report_days(report: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    matches = report.loc[report["Item"].eq("Gas Day")]
    if matches.empty:
        raise ValueError("Missing Gas Day row")
    row = matches.iloc[0]
    current_day = parse_report_day(row["Extrapolated"])
    if pd.isna(current_day):
        current_day = parse_report_day(row["Prorated"])
    next_day = parse_report_day(row["NextDayNominated"])
    if pd.isna(current_day):
        raise ValueError("Could not parse current gas day")
    return current_day, next_day


def extract_flow_table(report: pd.DataFrame, source_file: str) -> pd.DataFrame:
    gas_day, next_day = extract_report_days(report)
    rows: list[dict[str, object]] = []
    for raw_item, (clean_item, category) in FLOW_ITEM_MAP.items():
        matches = report.loc[report["Item"].eq(raw_item)]
        if matches.empty:
            continue
        row = matches.iloc[0]
        rows.append({
            "GasDay": gas_day,
            "NextDayGasDay": next_day,
            "Item": clean_item,
            "Category": category,
            "ProratedMMcfd": parse_number(row["Prorated"]),
            "ExtrapolatedMMcfd": parse_number(row["Extrapolated"]),
            "NextDayNominatedMMcfd": parse_number(row["NextDayNominated"]),
            "SourceFile": source_file,
        })
    return pd.DataFrame(rows)


def extract_metric_table(report: pd.DataFrame, source_file: str) -> pd.DataFrame:
    gas_day, _ = extract_report_days(report)
    rows: list[dict[str, object]] = []
    for raw_item, clean_metric in OPERATIONAL_METRIC_MAP.items():
        matches = report.loc[report["Item"].eq(raw_item)]
        if matches.empty:
            continue
        row = matches.iloc[0]
        raw_value = row["Extrapolated"]
        if raw_item in {"Tolerance", "Tolerance Last Changed"}:
            numeric_value = None
            text_value = None if pd.isna(raw_value) else str(raw_value).strip()
        else:
            numeric_value = parse_number(raw_value)
            text_value = None
        rows.append({
            "GasDay": gas_day,
            "Metric": clean_metric,
            "NumericValue": numeric_value,
            "TextValue": text_value,
            "SourceFile": source_file,
        })
    return pd.DataFrame(rows)


def compile_downloaded_reports() -> None:
    files = sorted(
        path for path in OUTPUT_FOLDER.glob("GdsrNGTLImperial*.csv")
        if re.fullmatch(r"GdsrNGTLImperial\d{8}\.csv", path.name)
    )
    if not files:
        raise FileNotFoundError(f"No raw GDSR files found in {OUTPUT_FOLDER}")

    flow_frames: list[pd.DataFrame] = []
    metric_frames: list[pd.DataFrame] = []
    failures: list[dict[str, str]] = []

    for path in files:
        try:
            report = read_report_for_compile(path)
            flow_frames.append(extract_flow_table(report, path.name))
            metric_frames.append(extract_metric_table(report, path.name))
        except Exception as exc:
            failures.append({"file": path.name, "error": str(exc)})
            print(f"Compile failed for {path.name}: {exc}")

    if not flow_frames:
        raise RuntimeError("No raw reports compiled successfully")

    flows = pd.concat(flow_frames, ignore_index=True)
    metrics = pd.concat(metric_frames, ignore_index=True)

    flows = (
        flows.drop_duplicates(subset=["GasDay", "Item"], keep="last")
        .sort_values(["GasDay", "Category", "Item"])
        .reset_index(drop=True)
    )
    metrics = (
        metrics.drop_duplicates(subset=["GasDay", "Metric"], keep="last")
        .sort_values(["GasDay", "Metric"])
        .reset_index(drop=True)
    )

    PROCESSED_FOLDER.mkdir(parents=True, exist_ok=True)
    flows.to_csv(FLOW_OUTPUT, index=False, date_format="%Y-%m-%d")
    metrics.to_csv(METRIC_OUTPUT, index=False, date_format="%Y-%m-%d")

    compile_log = PROJECT_FOLDER / "gdsr_compile_log.json"
    compile_log.write_text(
        json.dumps({
            "run_timestamp": datetime.now().isoformat(timespec="seconds"),
            "raw_files_found": len(files),
            "flow_rows": len(flows),
            "metric_rows": len(metrics),
            "failures": failures,
        }, indent=2),
        encoding="utf-8",
    )

    print("\nCOMPILE SUMMARY")
    print("---------------")
    print(f"Raw files:   {len(files)}")
    print(f"Flow rows:   {len(flows)}")
    print(f"Metric rows: {len(metrics)}")
    print(f"Flows:       {FLOW_OUTPUT}")
    print(f"Metrics:     {METRIC_OUTPUT}")
    print(f"Log:         {compile_log}")


async def main() -> None:
    args = parse_cli()

    start_day = date.fromisoformat(args.start)
    end_day = date.fromisoformat(args.end)
    capture_day = date.fromisoformat(args.capture_date)

    if end_day < start_day:
        raise ValueError("--end must be on or after --start.")

    PROJECT_FOLDER.mkdir(parents=True, exist_ok=True)
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    if not args.compile_only:
        async with async_playwright() as playwright:
            if args.recapture or not CAPTURE_FILE.exists():
                capture = await capture_request(playwright, capture_day)
            else:
                capture = load_capture()
                print(f"Using saved request capture: {CAPTURE_FILE}")

            await download_range(
                playwright=playwright,
                capture=capture,
                start_day=start_day,
                end_day=end_day,
                overwrite=args.overwrite,
                pause_seconds=args.pause,
            )

    if not args.download_only:
        compile_downloaded_reports()


if __name__ == "__main__":
    asyncio.run(main())
