"""Precompute the tables the production app derives from the parquets.

Why
---
The app reads two parquet files, 128 MB and 113 MB, to produce a handful
of small tables: a monthly history chart, a base decline series, vintage
curves and an operator scorecard. Together those outputs are under a
megabyte.

That is fine locally and impossible to deploy - GitHub rejects files
over 100 MB, and Streamlit Community Cloud would be reading a quarter of
a gigabyte to draw a bar chart.

So this computes the outputs once and writes them to processed/deploy/.
The app prefers the parquets when they exist and falls back to these,
which means a local checkout stays fully interactive while a deployed
copy carries only what it needs.

The one interactive control that cannot survive this is the vintage
tab's rate floor, which recomputes from raw well-months. It is
precomputed at a fixed set of floors instead, and the app snaps the
slider to the nearest available one.

Output
------
processed/deploy/*.csv          a few hundred KB in total

Run
---
    python3 prepare_deploy_data.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import analyse_ab_supply as supply

PROJECT_ROOT = Path(__file__).resolve().parent
LOCATED = PROJECT_ROOT / "processed" / "ab_well_production_located.parquet"
OUTPUT_DIR = PROJECT_ROOT / "processed" / "deploy"

# Floors the vintage slider can take once deployed. The app snaps to the
# nearest of these rather than recomputing from well-months.
FLOORS = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]

MAX_AGE = 24


def write(frame: pd.DataFrame, name: str) -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    frame.to_csv(path, index=False)
    size = path.stat().st_size
    print(f"  {name:34}{len(frame):>8,} rows  {size / 1024:>8,.0f} KB")
    return size


def main() -> None:
    print("Reading well-month data...")
    frame = supply.load()
    aged = supply.well_age_table(frame)
    total = 0

    print("\nSupply analytics:")
    total += write(supply.base_decline(frame), "base_decline.csv")

    curve, cohorts = supply.vintage_curves(aged)
    dropped = cohorts.attrs.get("dropped_cohorts") or []
    cohorts = cohorts.assign(
        dropped_cohorts=",".join(str(d) for d in dropped)
    )
    total += write(cohorts, "vintage_summary.csv")
    total += write(curve, "vintage_curves.csv")

    board = supply.operator_scorecard(frame, aged).reset_index()
    board = board.rename(columns={"index": "operator"})
    total += write(board, "operators.csv")

    # The vintage tab's fixed-age median curve, at each selectable floor.
    print("\nVintage curves by rate floor:")
    peaks = aged.groupby("well_id")["rate_mmcfd"].max()
    window_start = aged["month"].min()
    rows = []
    for floor in FLOORS:
        keep = peaks[peaks > floor].index
        subset = aged[
            aged["well_id"].isin(keep)
            & (aged["first_month"] > window_start)
            & (aged["age_months"] <= MAX_AGE)
        ].copy()
        if subset.empty:
            continue
        subset["cohort"] = subset["first_month"].dt.year
        grouped = (
            subset.groupby(["cohort", "age_months"])["rate_mmcfd"]
            .median().reset_index()
        )
        grouped["floor"] = floor
        rows.append(grouped)
    total += write(pd.concat(rows, ignore_index=True), "vintage_by_floor.csv")

    # Monthly history for the bar chart, aggregated to the grain the app
    # actually plots: month x product x operator.
    print("\nMonthly history:")
    if LOCATED.exists():
        history = pd.read_parquet(LOCATED, columns=[
            "production_month", "product_class", "operator",
            "rate_mmcfd", "rate_bbld",
        ])
    else:
        history = pd.read_parquet(
            PROJECT_ROOT / "processed" / "ab_well_production.parquet",
            columns=[
                "production_month", "product_class", "operator",
                "rate_mmcfd", "rate_bbld",
            ],
        )
    monthly = history.groupby(
        ["production_month", "product_class", "operator"], as_index=False
    )[["rate_mmcfd", "rate_bbld"]].sum()
    total += write(monthly, "monthly_history.csv")

    print(f"\ntotal {total / 1e6:.2f} MB, replacing 241 MB of parquet")


if __name__ == "__main__":
    main()
