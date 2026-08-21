"""Extract NGTL's linepack target and operational tolerance band.

Why this is separate from the flow compile
------------------------------------------
The GDSR compile keeps numeric flow rows. Tolerance is published as a
string - "0/2 (%)" - so it is dropped, along with the target and the
account balances that sit beside it. Those are the rows a scheduler
actually watches: linepack against target, and how much room is left
before TC acts.

What tolerance means
--------------------
The band is a percentage range around the linepack target that TC is
willing to operate within. It is deliberately asymmetric and TC moves it
to steer the system:

    "0/2 (%)"   target to +2%   - TC wants linepack built up
    "-1/1 (%)"  +/- 1%          - balanced
    "-2/0 (%)"  -2% to target   - TC wants linepack drawn down

So the band is not a passive measurement, it is an instruction. A move
from -1/1 to 0/2 is TC telling the market it wants gas left in the pipe,
which tightens supply available to the border. Over the archive TC has
changed it 16 times in 411 gas days, roughly every four weeks.

Also captured
-------------
Total SD Account and Total OBA Account, in TJ. These are the aggregate
shipper imbalance positions - how much gas shippers collectively owe the
system or are owed - which is the other half of the tolerance picture.

Output
------
processed/ngtl_linepack_tolerance.csv

Run
---
    python3 prepare_linepack_tolerance.py
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path("/Users/willgirling/Desktop/NGTL Project")
GDSR_DIR = PROJECT_ROOT / "gdsr"
OUTPUT = PROJECT_ROOT / "processed" / "ngtl_linepack_tolerance.csv"

# Row labels as GDSR prints them, mapped to output columns.
WANTED = {
    "Gas Day": "gas_day",
    "End of Day Linepack": "linepack_mmcf",
    "Linepack Target": "target_mmcf",
    "Linepack Rate of Change": "linepack_roc_mmcfd",
    "Linepack Change (Last 24 hours)": "linepack_change_24h_mmcf",
    "Tolerance": "tolerance_raw",
    "Tolerance Last Changed": "tolerance_changed_raw",
    "Total SD Account (TJ)": "sd_account_tj",
    "Total OBA Account (TJ)": "oba_account_tj",
}

TOLERANCE_RE = re.compile(r"\s*(-?[\d.]+)\s*/\s*(-?[\d.]+)\s*\(%\)")


def cell(row: list[str]) -> str:
    """First non-empty value after the label.

    The value lands in the Prorated column for some rows and the
    Extrapolated column for others, so both are checked rather than
    assuming a fixed position.
    """
    for value in row[1:4]:
        text = (value or "").strip()
        if text:
            return text
    return ""


def read_file(path: Path) -> dict:
    record: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.reader(handle):
            if not row:
                continue
            label = row[0].strip()
            if label in WANTED:
                record[WANTED[label]] = cell(row)
    record["source_file"] = path.name
    return record


def to_number(value: str) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return float("nan")


def main() -> None:
    files = sorted(GDSR_DIR.glob("GdsrNGTL*.csv"))
    if not files:
        raise SystemExit(f"No GDSR files found in {GDSR_DIR}")

    print(f"Reading {len(files)} GDSR files")
    frame = pd.DataFrame([read_file(path) for path in files])

    frame["gas_day"] = pd.to_datetime(
        frame["gas_day"], format="%Y-%b-%d", errors="coerce"
    )
    frame = frame.dropna(subset=["gas_day"]).sort_values("gas_day")

    for column in (
        "linepack_mmcf", "target_mmcf", "linepack_roc_mmcfd",
        "linepack_change_24h_mmcf", "sd_account_tj", "oba_account_tj",
    ):
        frame[column] = frame.get(column, "").map(to_number)

    # Split "0/2 (%)" into its two edges, then express the band in MMcf
    # so it can be compared with a linepack reading directly.
    edges = frame["tolerance_raw"].fillna("").map(
        lambda text: TOLERANCE_RE.match(text)
    )
    frame["tolerance_low_pct"] = [
        float(m.group(1)) if m else float("nan") for m in edges
    ]
    frame["tolerance_high_pct"] = [
        float(m.group(2)) if m else float("nan") for m in edges
    ]

    frame["band_low_mmcf"] = frame["target_mmcf"] * (
        1 + frame["tolerance_low_pct"] / 100
    )
    frame["band_high_mmcf"] = frame["target_mmcf"] * (
        1 + frame["tolerance_high_pct"] / 100
    )

    # Where the day's linepack sits in the band: 0 at the low edge, 1 at
    # the high edge, outside those values when the band is breached.
    width = frame["band_high_mmcf"] - frame["band_low_mmcf"]
    frame["band_position"] = (
        frame["linepack_mmcf"] - frame["band_low_mmcf"]
    ) / width.where(width != 0)

    frame["tolerance_changed"] = pd.to_datetime(
        frame["tolerance_changed_raw"].str.replace(
            r"\s+at\s+", " ", regex=True
        ),
        format="%Y-%b-%d %H:%M",
        errors="coerce",
    )

    # A change is worth flagging on the day it lands.
    frame["tolerance_shifted"] = (
        frame["tolerance_raw"] != frame["tolerance_raw"].shift()
    )
    frame.loc[frame.index[:1], "tolerance_shifted"] = False

    columns = [
        "gas_day", "linepack_mmcf", "target_mmcf",
        "tolerance_raw", "tolerance_low_pct", "tolerance_high_pct",
        "band_low_mmcf", "band_high_mmcf", "band_position",
        "tolerance_changed", "tolerance_shifted",
        "linepack_roc_mmcfd", "linepack_change_24h_mmcf",
        "sd_account_tj", "oba_account_tj", "source_file",
    ]
    frame = frame[[c for c in columns if c in frame.columns]]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUTPUT, index=False)

    print(f"\nwrote {len(frame)} gas days -> {OUTPUT.name}")
    print(f"  {frame['gas_day'].min():%Y-%m-%d} to "
          f"{frame['gas_day'].max():%Y-%m-%d}")

    print("\n  tolerance settings used:")
    for value, count in frame["tolerance_raw"].value_counts().items():
        print(f"    {str(value):14} {count:4d} gas days")

    shifts = int(frame["tolerance_shifted"].sum())
    print(f"\n  tolerance changed {shifts} times")

    outside = frame["band_position"].dropna()
    breaches = int(((outside < 0) | (outside > 1)).sum())
    print(f"  gas days with linepack outside the band: {breaches} "
          f"of {len(outside)} ({breaches / max(len(outside), 1) * 100:.0f}%)")

    latest = frame.iloc[-1]
    print(f"\n  latest ({latest['gas_day']:%Y-%m-%d}): "
          f"linepack {latest['linepack_mmcf']:,.0f} vs target "
          f"{latest['target_mmcf']:,.0f}, band {latest['tolerance_raw']} "
          f"= {latest['band_low_mmcf']:,.0f}–{latest['band_high_mmcf']:,.0f}")


if __name__ == "__main__":
    main()
