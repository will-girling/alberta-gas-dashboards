"""Precompute the Montney Supply Monitor's inputs.

Why precompute
--------------
The monitor answers one question - is the Montney responding to LNG - and
it has to answer it in a browser, in front of someone, without a 241 MB
parquet behind it. The Alberta side needs a vintage decomposition and a
fixed-age productivity comparison, both of which take tens of seconds
over the full well-month history. Neither changes between page loads.

So the heavy work happens here, once, and the app reads four small CSVs.
Same pattern as prepare_deploy_data.py.

The BC frac table is left as-is: 2,158 rows is nothing, and keeping the
raw records means the app can filter by operator and date without a
precomputed cross-tab constraining what can be asked.

Outputs (processed/monitor/)
----------------------------
ab_montney_monthly.csv      gas by month and well vintage
ab_montney_wells.csv        new wells by first-production month
ab_montney_vintage.csv      fixed-age productivity per vintage/operator
bc_fracs.csv                BC frac records, Montney flagged

Run
---
    python3 prepare_montney_monitor_data.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import ab_plays

PROJECT_ROOT = Path(__file__).resolve().parent
PROCESSED = PROJECT_ROOT / "processed"
OUT_DIR = PROCESSED / "monitor"

HISTORY = PROCESSED / "ab_well_production.parquet"
LOCATED = PROCESSED / "ab_well_production_located.parquet"
BC_FRACS = PROCESSED / "bc_frac_activity.parquet"

PLAY = "Montney (Alberta)"
LATERAL_MIN_M, LATERAL_MAX_M = 500, 7000

# Fixed-age windows offered in the app. Six months keeps the most recent
# vintage in the sample; twelve is the more honest comparison but drops a
# year of wells. Both are precomputed so the app can toggle.
AGE_WINDOWS = (6, 12)


def alberta_montney() -> pd.DataFrame:
    """Monthly Montney gas by well, with vintage, age and lateral length."""
    loc = pd.read_parquet(
        LOCATED,
        columns=["well_id", "BH_Latitude", "BH_Longitude",
                 "Final_Total_Depth", "Max_True_Vertical_Depth"],
    ).drop_duplicates("well_id")
    loc["play"] = ab_plays.assign(loc, "BH_Latitude", "BH_Longitude")
    loc["lateral_m"] = (
        pd.to_numeric(loc["Final_Total_Depth"], errors="coerce")
        - pd.to_numeric(loc["Max_True_Vertical_Depth"], errors="coerce")
    )
    loc = loc.loc[loc["play"] == PLAY,
                  ["well_id", "lateral_m", "BH_Latitude", "BH_Longitude"]]

    gas = pd.read_parquet(
        HISTORY,
        columns=["production_month", "product_class", "rate_mmcfd",
                 "operator", "well_id"],
        filters=[("product_class", "==", "GAS")],
    )
    gas = gas[gas["well_id"].isin(set(loc["well_id"]))].copy()
    gas["month"] = gas["production_month"].astype(str)
    gas = gas.groupby(["month", "well_id", "operator"],
                      observed=True, as_index=False)["rate_mmcfd"].sum()

    first = (gas[gas["rate_mmcfd"] > 0]
             .groupby("well_id")["month"].min().rename("first_month"))
    gas = gas.join(first, on="well_id").merge(loc, on="well_id")
    gas["vintage"] = gas["first_month"].str[:4]
    gas["age"] = (
        gas["month"].str[:4].astype(int) * 12 + gas["month"].str[5:7].astype(int)
        - gas["first_month"].str[:4].astype(int) * 12
        - gas["first_month"].str[5:7].astype(int)
    )
    return gas


def write_monthly(gas: pd.DataFrame) -> None:
    """Gas by month and cohort - the treadmill chart's source.

    Wells first seen in the opening month of the archive are lumped as
    "2022 & earlier" because their true first production predates the
    data and treating them as a 2022 vintage would invent a cohort.
    """
    cohort = gas["vintage"].where(gas["vintage"] > "2022", "2022 & earlier")
    table = (gas.assign(cohort=cohort)
             .groupby(["month", "cohort"], observed=True)["rate_mmcfd"]
             .sum().reset_index())
    table["bcfd"] = table["rate_mmcfd"] / 1000
    table[["month", "cohort", "bcfd"]].to_csv(
        OUT_DIR / "ab_montney_monthly.csv", index=False)
    print(f"  ab_montney_monthly.csv  {len(table):,} rows")


def write_wells(gas: pd.DataFrame) -> None:
    wells = gas.drop_duplicates("well_id")[
        ["well_id", "first_month", "operator", "lateral_m",
         "BH_Latitude", "BH_Longitude"]]
    wells = wells[wells["first_month"] >= "2023-01"]
    wells.to_csv(OUT_DIR / "ab_montney_wells.csv", index=False)
    print(f"  ab_montney_wells.csv    {len(wells):,} wells")


def write_vintage(gas: pd.DataFrame) -> None:
    """Fixed-age cumulative gas per well, complete windows only.

    Complete windows matter more than they look: annualising a
    four-month well measures its flush period and flatters every recent
    vintage, which is exactly the direction that would fake a
    'productivity is fine' conclusion.
    """
    frames = []
    for months in AGE_WINDOWS:
        window = gas[(gas["age"] < months) & (gas["vintage"] >= "2023")]
        well = window.groupby(["vintage", "well_id"], observed=True).agg(
            rate_sum=("rate_mmcfd", "sum"),
            months=("age", "size"),
            lateral_m=("lateral_m", "first"),
            operator=("operator", "first"),
        ).reset_index()
        well = well[well["months"] == months]
        well = well[well["lateral_m"].between(LATERAL_MIN_M, LATERAL_MAX_M)]
        well["cum_mmcf"] = well["rate_sum"] * 30.4
        well["per_1000m"] = well["cum_mmcf"] / well["lateral_m"] * 1000
        well["window"] = months
        frames.append(well[["window", "vintage", "well_id", "operator",
                            "lateral_m", "cum_mmcf", "per_1000m"]])

    out = pd.concat(frames, ignore_index=True)
    out.to_csv(OUT_DIR / "ab_montney_vintage.csv", index=False)
    print(f"  ab_montney_vintage.csv  {len(out):,} well-windows")


def write_bc() -> None:
    if not BC_FRACS.exists():
        print("  bc_fracs.csv            SKIPPED - run "
              "prepare_bc_well_locations.py --download fracs")
        return

    frame = pd.read_parquet(BC_FRACS)
    frame["start"] = pd.to_datetime(frame["OPS_EXPECTED_START_DATE"],
                                    errors="coerce")
    frame = frame.dropna(subset=["start"])
    # One row per well authorization so a re-frac cannot read as a new
    # well. Affects six records of 2,164, but the app lets people count
    # things and the count should be right.
    frame = frame.sort_values("start").drop_duplicates("WA_NUM")
    frame["is_montney"] = (
        frame["OBJECTIVE_FORMATION"].astype(str).str.upper() == "MONTNEY")

    out = frame.rename(columns={
        "WA_NUM": "wa_num", "OPERATOR_ABBREVIATION": "operator",
        "WELL_NAME": "well_name", "OBJECTIVE_FORMATION": "formation",
        "TD_DEPTH": "td_m",
    })[["wa_num", "operator", "well_name", "formation", "td_m",
        "start", "is_montney", "lat", "lon"]]
    out.to_csv(OUT_DIR / "bc_fracs.csv", index=False)
    print(f"  bc_fracs.csv            {len(out):,} fracs "
          f"({int(out['is_montney'].sum()):,} Montney), "
          f"{out['start'].min().date()} to {out['start'].max().date()}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Building monitor inputs")

    gas = alberta_montney()
    print(f"  Alberta Montney: {gas['well_id'].nunique():,} wells, "
          f"{gas['month'].min()} to {gas['month'].max()}")
    write_monthly(gas)
    write_wells(gas)
    write_vintage(gas)
    write_bc()

    total = sum(f.stat().st_size for f in OUT_DIR.glob("*.csv"))
    print(f"\ntotal {total / 1e6:.2f} MB in {OUT_DIR}")


if __name__ == "__main__":
    main()
