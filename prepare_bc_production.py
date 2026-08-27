"""BC well production from BCER, joined to locations.

What this closes
----------------
Every BC statement in this project so far has been about *activity* —
wells frac'd — because I could not find accessible BC production. That
was wrong. BCER publishes it as a direct download, no logon:

    https://iris.bcogc.ca/download/prod_csv.zip
    https://iris.bcogc.ca/download/well_index.csv

I had only looked at the ArcGIS spatial server, which carries wells and
fracs but no volumes, and at the Legacy Well Lookup, which is gated. The
Data Centre listing has it under BCOGC-42126.

Why BC attribution is better than Alberta's
-------------------------------------------
The production file carries Formtn_code, a formation identifier. Code
5000 is the Montney, verified empirically rather than assumed: every one
of the 58,177 production records belonging to wells the BCER frac layer
independently labels MONTNEY carries code 5000, with no exceptions.

That is a real advantage over the Alberta side of this project, where
plays are geographic boxes and the Montney/Deep Basin split is out by
±32% as a result. BC needs no boxes.

Units
-----
BCER reports gas in e3m3 (thousand cubic metres) and liquids in m3, per
month. Both are converted to the field units used everywhere else here —
MMcf/d and bbl/d — using Prod_days rather than days in the month, since
a well that produced 12 days of a 31-day month has a rate of its own.

Output
------
processed/bc_well_production.parquet   well-month, located, Montney flagged

Run
---
    python3 prepare_bc_production.py
    python3 prepare_bc_production.py --all-formations
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
PROD_ZIP = PROJECT_ROOT / "prod_csv.zip"
LOCATIONS = PROJECT_ROOT / "processed" / "bc_well_locations.parquet"
OUTPUT = PROJECT_ROOT / "processed" / "bc_well_production.parquet"

# The archive splits by era. Only the modern file is read by default:
# it starts in 2016, covers every period this project compares, and the
# full zone_prd.csv is 369 MB of mostly irrelevant history.
MEMBER = "zone_prd_2016_to_present.csv"

# Verified against the BCER frac layer's OBJECTIVE_FORMATION field.
MONTNEY_CODE = 5000

# 1 e3m3 = 1,000 m3 = 35,314.7 cf = 0.0353147 MMcf
E3M3_TO_MMCF = 0.0353147
M3_TO_BBL = 1 / 0.158987

# A month with a handful of producing days is usually a well being
# brought on or worked over; its implied daily rate is unstable.
MIN_PROD_DAYS = 1


def load_production(all_formations: bool) -> pd.DataFrame:
    if not PROD_ZIP.exists():
        raise SystemExit(
            f"{PROD_ZIP.name} not found. Download it:\n"
            "  curl -O https://iris.bcogc.ca/download/prod_csv.zip"
        )

    with zipfile.ZipFile(PROD_ZIP) as archive:
        with archive.open(MEMBER) as handle:
            # Row 0 is a title banner, not a header.
            frame = pd.read_csv(handle, skiprows=1, low_memory=False)

    frame.columns = [c.strip() for c in frame.columns]
    frame = frame.rename(columns={
        "Wa_num": "wa_num", "Prod_period": "period", "UWI": "uwi",
        "Formtn_code": "formation_code", "Area_code": "area_code",
        "Pool_seq": "pool_seq", "Prod_days": "prod_days",
        "Gas_prod_vol (e3m3)": "gas_e3m3",
        "Oil_prod_vol (m3)": "oil_m3",
        "Cond_prod_vol (m3)": "cond_m3",
        "Water_prod_vol (m3)": "water_m3",
    })

    frame["wa_num"] = pd.to_numeric(frame["wa_num"], errors="coerce")
    frame["formation_code"] = pd.to_numeric(frame["formation_code"],
                                            errors="coerce")
    for column in ("gas_e3m3", "oil_m3", "cond_m3", "water_m3", "prod_days"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0)

    if not all_formations:
        frame = frame[frame["formation_code"] == MONTNEY_CODE]

    # YYYYMM -> YYYY-MM, matching the Alberta convention.
    period = frame["period"].astype(str).str.zfill(6)
    frame["month"] = period.str[:4] + "-" + period.str[4:6]

    frame = frame[frame["prod_days"] >= MIN_PROD_DAYS]

    frame["gas_mmcfd"] = frame["gas_e3m3"] * E3M3_TO_MMCF / frame["prod_days"]
    frame["oil_bbld"] = frame["oil_m3"] * M3_TO_BBL / frame["prod_days"]
    frame["cond_bbld"] = frame["cond_m3"] * M3_TO_BBL / frame["prod_days"]
    frame["is_montney"] = frame["formation_code"] == MONTNEY_CODE

    return frame[[
        "wa_num", "month", "uwi", "formation_code", "area_code", "pool_seq",
        "prod_days", "gas_mmcfd", "oil_bbld", "cond_bbld", "is_montney",
    ]]


def attach_locations(frame: pd.DataFrame) -> pd.DataFrame:
    """Join the ArcGIS well layer on WA number.

    WA numbers arrive zero-padded as strings in one source and as
    integers in the other, so both sides are coerced to numeric rather
    than string-matched — otherwise "00027" and "27" miss each other and
    the join silently drops most of the province.
    """
    if not LOCATIONS.exists():
        print("  no bc_well_locations.parquet — run "
              "prepare_bc_well_locations.py --download wells")
        return frame

    wells = pd.read_parquet(LOCATIONS)
    wells["wa_num"] = pd.to_numeric(wells["WELL_AUTHORITY_NUMBER"],
                                    errors="coerce")
    wells = wells.dropna(subset=["wa_num"]).drop_duplicates("wa_num")
    wells = wells[["wa_num", "lat", "lon", "OPERATOR_ABBREVIATION",
                   "WELL_NAME", "WELL_ACTIVITY"]].rename(columns={
        "OPERATOR_ABBREVIATION": "operator",
        "WELL_NAME": "well_name",
        "WELL_ACTIVITY": "well_activity",
    })

    merged = frame.merge(wells, on="wa_num", how="left")
    located = merged["lat"].notna()
    latest = merged["month"].max()
    recent = merged[merged["month"] == latest]
    share = (recent.loc[recent["lat"].notna(), "gas_mmcfd"].sum()
             / max(recent["gas_mmcfd"].sum(), 1e-9) * 100)
    print(f"  located {located.sum():,} of {len(merged):,} well-months "
          f"({share:.1f}% of latest-month gas)")
    return merged


def report(frame: pd.DataFrame) -> None:
    montney = frame[frame["is_montney"]]
    monthly = montney.groupby("month")["gas_mmcfd"].sum() / 1000

    print(f"\nBC Montney gas, Bcf/d — annual averages")
    annual = monthly.groupby(monthly.index.str[:4]).mean()
    for year, value in annual.items():
        print(f"   {year}   {value:.2f}")

    latest12 = monthly.tail(12).mean()
    print(f"\n   trailing 12-month average: {latest12:.2f} Bcf/d gross")
    print(f"   at 15% shrinkage:          {latest12 * 0.85:.2f} Bcf/d marketable")
    print(f"   Peters 2026E BC Montney:   7.5 Bcf/d marketable")

    liquids = montney.groupby("month")[["cond_bbld", "oil_bbld"]].sum().tail(12).mean()
    gas12 = montney.groupby("month")["gas_mmcfd"].sum().tail(12).mean()
    print(f"\n   condensate {liquids['cond_bbld']:,.0f} b/d · "
          f"oil {liquids['oil_bbld']:,.0f} b/d")
    print(f"   condensate yield {liquids['cond_bbld'] / gas12:.1f} bbl/MMcf")
    print("   (Alberta Montney, same basis: 22.1 bbl/MMcf)")

    if "operator" in frame.columns:
        recent = montney[montney["month"] == montney["month"].max()]
        top = recent.groupby("operator")["gas_mmcfd"].sum().nlargest(10)
        print("\n   top BC Montney gas operators, latest month, MMcf/d:")
        for name, value in top.items():
            print(f"     {str(name)[:24]:26}{value:>8,.0f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-formations", action="store_true",
                        help="keep every formation, not just the Montney")
    args = parser.parse_args()

    print(f"Reading {MEMBER} from {PROD_ZIP.name}")
    frame = load_production(args.all_formations)
    print(f"  {len(frame):,} well-months, "
          f"{frame['wa_num'].nunique():,} wells, "
          f"{frame['month'].min()} to {frame['month'].max()}")

    frame = attach_locations(frame)
    report(frame)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OUTPUT, index=False)
    print(f"\n  -> {OUTPUT.name} ({OUTPUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
