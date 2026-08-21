from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from playwright.async_api import Playwright, Response, async_playwright


SITE_URL = "https://my.tccustomerexpress.com/#CurrentSystemReport"
PROJECT_FOLDER = Path("/Users/willgirling/Desktop/NGTL Project")
MASTER_FILE = PROJECT_FOLDER / "CSR_Master.csv"
RAW_FOLDER = PROJECT_FOLDER / "csr_raw"
CAPTURE_FILE = PROJECT_FOLDER / "csr_request_capture.json"
LOG_FILE = PROJECT_FOLDER / "csr_download_log.json"
PROFILE_DIR = PROJECT_FOLDER / ".playwright_profile_csr"


@dataclass
class CapturedRequest:
    method: str
    url: str
    headers: dict[str, str]
    post_data: str | None
    captured_at: str


def parse_cli() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Pull CSR Last 24 Hours and append new observations to CSR_Master.csv."
    )
    p.add_argument("--recapture", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--keep-raw",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    return p.parse_args()


def looks_like_csv(response: Response) -> bool:
    h = {k.lower(): v.lower() for k, v in response.headers.items()}
    ct = h.get("content-type", "")
    cd = h.get("content-disposition", "")
    u = response.url.lower()
    return (
        "csv" in ct
        or ".csv" in cd
        or ".csv" in u
        or "export" in u
        or "download" in u
    )


def validate_csv_bytes(body: bytes) -> tuple[int, int]:
    text = body.decode("utf-8-sig", errors="replace")
    if "<html" in text[:500].lower():
        raise ValueError("Server returned HTML, not CSV.")
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        raise ValueError("CSV has too few rows.")
    cols = max((len(r) for r in rows[:25]), default=0)
    if cols < 2:
        raise ValueError("CSV has too few columns.")
    return len(rows), cols


async def probable_csr_csv(response: Response) -> bool:
    if not looks_like_csv(response):
        return False
    try:
        body = await response.body()
        rows, cols = validate_csv_bytes(body)
        return rows >= 3 and cols >= 2
    except Exception:
        return False


async def capture_request(playwright: Playwright) -> CapturedRequest:
    PROJECT_FOLDER.mkdir(parents=True, exist_ok=True)
    RAW_FOLDER.mkdir(parents=True, exist_ok=True)

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        accept_downloads=True,
    )
    page = context.pages[0] if context.pages else await context.new_page()

    future = asyncio.get_running_loop().create_future()
    diagnostics = []

    async def inspect(response: Response) -> None:
        diagnostics.append(
            {
                "status": response.status,
                "url": response.url,
                "content_type": response.headers.get("content-type"),
                "content_disposition": response.headers.get("content-disposition"),
                "method": response.request.method,
                "post_data": response.request.post_data,
            }
        )

        if future.done() or not await probable_csr_csv(response):
            return

        req = response.request
        excluded = {
            "content-length", "host", "connection", "cookie",
            "sec-fetch-dest", "sec-fetch-mode", "sec-fetch-site",
            "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
        }
        headers = {
            k: v for k, v in req.headers.items()
            if k.lower() not in excluded
        }

        future.set_result(
            CapturedRequest(
                method=req.method,
                url=req.url,
                headers=headers,
                post_data=req.post_data,
                captured_at=datetime.now().isoformat(timespec="seconds"),
            )
        )

    page.on("response", lambda r: asyncio.create_task(inspect(r)))
    await page.goto(SITE_URL, wait_until="domcontentloaded")

    print("\nCSR REQUEST CAPTURE")
    print("-------------------")
    print("1. Keep system = NGTL.")
    print("2. Keep the same units used in CSR_Master.csv.")
    print("3. Select 'Last 24 Hours'.")
    print("4. Generate/refresh the report if required.")
    print("5. Click the CSV export/download button ONCE.")
    print("6. Return to Terminal.\n")

    try:
        capture = await asyncio.wait_for(future, timeout=300)
    except asyncio.TimeoutError as exc:
        path = PROJECT_FOLDER / "csr_network_diagnostics.json"
        path.write_text(json.dumps(diagnostics[-150:], indent=2), encoding="utf-8")
        raise RuntimeError(
            f"No CSV request captured within five minutes. Diagnostics: {path}"
        ) from exc
    finally:
        await context.close()

    CAPTURE_FILE.write_text(
        json.dumps(asdict(capture), indent=2),
        encoding="utf-8",
    )
    print(f"Saved request capture: {CAPTURE_FILE}")
    return capture


def load_capture() -> CapturedRequest:
    return CapturedRequest(
        **json.loads(CAPTURE_FILE.read_text(encoding="utf-8"))
    )


# Shift explicit timestamps from the original rolling request forward.
ISO_PATTERN = re.compile(
    r"20\d{2}-\d{2}-\d{2}(?:[T ][0-2]\d:[0-5]\d"
    r"(?::[0-5]\d(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
)
EPOCH_MS = re.compile(r"(?<!\d)(1\d{12})(?!\d)")
EPOCH_SEC = re.compile(r"(?<!\d)(1\d{9})(?!\d)")


def shift_recent_tokens(
    text: str | None,
    captured_at: datetime,
    now: datetime,
) -> str | None:
    if text is None:
        return None

    elapsed = now - captured_at
    out = text

    for m in reversed(list(ISO_PATTERN.finditer(out))):
        token = m.group(0)
        try:
            dt = datetime.fromisoformat(token.replace("Z", "+00:00"))
        except ValueError:
            continue

        dt_cmp = dt.replace(tzinfo=None)
        cap_cmp = captured_at.replace(tzinfo=None)

        if abs(dt_cmp - cap_cmp) > timedelta(hours=48):
            continue

        shifted = dt + elapsed

        if "T" in token:
            sep = "T"
        elif " " in token:
            sep = " "
        else:
            replacement = shifted.strftime("%Y-%m-%d")
            out = out[:m.start()] + replacement + out[m.end():]
            continue

        has_seconds = bool(re.search(r":\d{2}:\d{2}", token))
        fmt = f"%Y-%m-%d{sep}%H:%M:%S" if has_seconds else f"%Y-%m-%d{sep}%H:%M"
        replacement = shifted.strftime(fmt)
        if token.endswith("Z"):
            replacement += "Z"
        out = out[:m.start()] + replacement + out[m.end():]

    cap_epoch = captured_at.timestamp()

    for pattern, divisor in ((EPOCH_MS, 1000), (EPOCH_SEC, 1)):
        for m in reversed(list(pattern.finditer(out))):
            raw = int(m.group(0))
            epoch = raw / divisor
            if abs(epoch - cap_epoch) <= 48 * 3600:
                shifted_epoch = epoch + elapsed.total_seconds()
                replacement = str(int(shifted_epoch * divisor))
                out = out[:m.start()] + replacement + out[m.end():]

    return out


def build_current_request(capture: CapturedRequest) -> tuple[str, str | None]:
    captured_at = datetime.fromisoformat(capture.captured_at)
    now = datetime.now()
    url = shift_recent_tokens(capture.url, captured_at, now)
    post_data = shift_recent_tokens(capture.post_data, captured_at, now)
    assert url is not None
    return url, post_data


def read_csv_robust(source: Path | bytes) -> pd.DataFrame:
    if isinstance(source, Path):
        df = pd.read_csv(source)
    else:
        df = pd.read_csv(io.BytesIO(source))

    df.columns = [
        str(c).replace("\ufeff", "").strip()
        for c in df.columns
    ]
    return df.dropna(how="all").reset_index(drop=True)


def infer_dedup_key(df: pd.DataFrame) -> list[str]:
    metadata = {"PullTimestamp", "SourceFile"}
    source_cols = [c for c in df.columns if c not in metadata]

    time_terms = (
        "timestamp", "datetime", "date/time", "date time",
        "gas day", "gasday", "date", "time",
    )
    id_terms = (
        "item", "metric", "location", "point", "station",
        "facility", "border", "name", "description", "parameter",
    )

    time_cols = [
        c for c in source_cols
        if any(t in c.lower() for t in time_terms)
    ][:4]

    id_cols = [
        c for c in source_cols
        if any(t in c.lower() for t in id_terms)
        and c not in time_cols
    ][:4]

    if time_cols:
        return list(dict.fromkeys(time_cols + id_cols))

    # Safe fallback: exact source-row deduplication.
    return source_cols


def append_master(
    new_df: pd.DataFrame,
    source_file: str,
    dry_run: bool,
) -> dict:
    new_df = new_df.copy()
    new_df["PullTimestamp"] = datetime.now().isoformat(timespec="seconds")
    new_df["SourceFile"] = source_file

    if MASTER_FILE.exists():
        master = read_csv_robust(MASTER_FILE)
    else:
        master = pd.DataFrame(columns=new_df.columns)

    all_cols = list(master.columns)
    for col in new_df.columns:
        if col not in all_cols:
            all_cols.append(col)

    master = master.reindex(columns=all_cols)
    new_df = new_df.reindex(columns=all_cols)

    before = len(master)
    combined = pd.concat([master, new_df], ignore_index=True)

    key = infer_dedup_key(combined)
    combined = combined.drop_duplicates(subset=key, keep="last")

    # Sort by first date/time-like key if possible.
    sort_candidates = [
        c for c in key
        if any(t in c.lower() for t in ("date", "time", "gasday", "gas day"))
    ]
    if sort_candidates:
        c = sort_candidates[0]
        combined["_sort_dt"] = pd.to_datetime(combined[c], errors="coerce")
        combined = (
            combined.sort_values("_sort_dt", kind="stable", na_position="last")
            .drop(columns="_sort_dt")
            .reset_index(drop=True)
        )

    after = len(combined)

    print("\nMASTER MERGE")
    print("------------")
    print(f"Existing rows: {before:,}")
    print(f"Pulled rows:   {len(new_df):,}")
    print(f"Dedup key:     {key}")
    print(f"Master rows:   {after:,}")
    print(f"Net new rows:  {after - before:,}")

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
        "net_new_rows": after - before,
        "dedup_key": key,
    }


async def download_and_append(
    playwright: Playwright,
    capture: CapturedRequest,
    keep_raw: bool,
    dry_run: bool,
) -> dict:
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=True,
    )

    try:
        url, post_data = build_current_request(capture)

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
        csv_rows, csv_cols = validate_csv_bytes(body)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        raw_name = f"CSR_Last24Hours_{stamp}.csv"
        raw_path = RAW_FOLDER / raw_name

        if keep_raw:
            raw_path.write_bytes(body)
            print(f"Saved raw pull: {raw_path}")

        df = read_csv_robust(body)
        print(f"Parsed columns: {list(df.columns)}")

        merge = append_master(
            new_df=df,
            source_file=raw_name,
            dry_run=dry_run,
        )

        return {
            "success": True,
            "downloaded_at": datetime.now().isoformat(timespec="seconds"),
            "raw_file": str(raw_path) if keep_raw else None,
            "csv_rows": csv_rows,
            "csv_columns": csv_cols,
            "parsed_columns": list(df.columns),
            **merge,
        }

    finally:
        await context.close()


async def main() -> None:
    args = parse_cli()

    PROJECT_FOLDER.mkdir(parents=True, exist_ok=True)
    RAW_FOLDER.mkdir(parents=True, exist_ok=True)

    started = datetime.now()

    try:
        async with async_playwright() as playwright:
            if args.recapture or not CAPTURE_FILE.exists():
                capture = await capture_request(playwright)
            else:
                capture = load_capture()
                print(f"Using saved request capture: {CAPTURE_FILE}")

            result = await download_and_append(
                playwright,
                capture,
                keep_raw=args.keep_raw,
                dry_run=args.dry_run,
            )

        result["run_started"] = started.isoformat(timespec="seconds")
        result["run_finished"] = datetime.now().isoformat(timespec="seconds")
        LOG_FILE.write_text(json.dumps(result, indent=2), encoding="utf-8")

        print(f"\nLog: {LOG_FILE}")
        print("CSR update completed successfully.")

    except Exception as exc:
        failure = {
            "success": False,
            "run_started": started.isoformat(timespec="seconds"),
            "run_finished": datetime.now().isoformat(timespec="seconds"),
            "error": repr(exc),
        }
        LOG_FILE.write_text(json.dumps(failure, indent=2), encoding="utf-8")
        print(f"\nCSR UPDATE FAILED: {exc}")
        print(f"Failure log: {LOG_FILE}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
