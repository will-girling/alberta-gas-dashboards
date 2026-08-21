"""Download Alberta monthly well-level production from Petrinex.

What this gets you
------------------
Per-well, per-product monthly volumes - not facility totals allocated
down. Rows where Activity ID is PROD and the From/To ID is a well are
that well's reported production for the month, as filed by the operator.

Source
------
Petrinex Alberta Public Data. Documented API, no authentication:

    https://www.petrinex.gov.ab.ca/publicdata/API/Files/AB/Vol/2026-05/CSV

Returns a ZIP containing one CSV per production month.

Coverage and limits - read these before trusting a number
---------------------------------------------------------
- History is the current production year plus the previous four. There
  is no deep history here; five years is the whole archive.
- Oil sands and waste plant volumes are EXCLUDED. For Alberta that is a
  large hole - this is conventional production only.
- Whole facility types are withheld under Petrinex's "security blanket":
  terminals, meter stations, gas plant fractionation (subtype 407),
  pipelines, custom treating and refineries. Their volumes are absent,
  not zero.
- Confidential wells appear with From/To ID and Hours masked as "***".
  Those are real volumes attached to an unidentifiable well, so they
  must be dropped from well-level work but still count in totals.
- Published monthly after the AER reporting deadline, so expect roughly
  a two month lag, and expect restatements of earlier months.

Units
-----
Gas is 10^3 m3, liquids are m3, energy is GJ. Converted here to MMcf and
bbl to match the NGTL dashboard's conventions. Volumes are monthly
totals; per-day rates divide by days in the production month.

Output
------
petrinex_raw/AB_Vol_<YYYY-MM>.zip      raw, kept immutable
processed/ab_well_production.parquet   tidy well-month-product table

Run
---
    python3 download_petrinex_volumes.py                 # last 12 months
    python3 download_petrinex_volumes.py --months 60     # full archive
    python3 download_petrinex_volumes.py --inspect 2026-05
"""

from __future__ import annotations

import argparse
import calendar
import re
import io
import time
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path("/Users/willgirling/Desktop/NGTL Project")
RAW_DIR = PROJECT_ROOT / "petrinex_raw"
OUTPUT = PROJECT_ROOT / "processed" / "ab_well_production.parquet"

API = "https://www.petrinex.gov.ab.ca/publicdata/API/Files/AB/Vol/{month}/CSV"

REQUEST_TIMEOUT = 300

# Production only. The file also carries receipts, dispositions, flaring,
# fuel, injection and inventory movements; including them would count
# the same gas several times over as it moves through the system.
PRODUCTION_ACTIVITY = "PROD"

# Products worth keeping for a gas-market map. GAS is metered in 10^3m3,
# the liquids in m3.
# Verified present on PROD rows: GAS, WATER, OIL, COND, BRKWTR,
# FSHWTR. Water is dropped here - it is a disposal cost, not
# production - but the codes are listed so the choice is visible.
KEEP_PRODUCTS = {"GAS", "OIL", "COND"}

# Petrinex product code OIL is documented as "Crude Oil, Crude Bitumen"
# - one code for two very different things. In May 2026 it was 2.42
# million bbl/d, of which only ~553k was conventional crude; the rest
# was in-situ bitumen reported through ordinary batteries. Left
# unsplit, any map coloured by oil production is dominated by a few
# thousand SAGD pads.
#
# ST37's Status_Fluid does not resolve it either: 57% of the oil sits
# under "Not Applicable". The reporting facility's subtype does, and it
# is AER's own classification carried in the volumetric file itself.
#
# Subtype families, verified against the May 2026 file:
#   311/321/322  crude oil batteries          553k bbl/d
#   331/341/342/343/344/345  bitumen and oil sands  1.85M bbl/d
#   351/361/362/364/365  gas batteries         16k bbl/d of liquids
OIL_SUBTYPE_CLASS = {
    "31": "CRUDE_OIL",
    "32": "CRUDE_OIL",
    "33": "BITUMEN",
    "34": "BITUMEN",
    "35": "OIL_AT_GAS_BATTERY",
    "36": "OIL_AT_GAS_BATTERY",
}


def classify_oil(subtype: pd.Series) -> pd.Series:
    """Split the OIL product code by the reporting facility's subtype."""
    family = subtype.fillna("").str.strip().str[:2]
    return family.map(OIL_SUBTYPE_CLASS).fillna("OIL_UNCLASSIFIED")

E3M3_TO_MMCF = 35.3147 / 1000.0     # 10^3 m3 -> MMcf
M3_TO_BBL = 6.2898

# Petrinex masks identifiers it will not release.
MASKED = "***"


def months_back(count: int) -> list[str]:
    """Production months, newest first, as YYYY-MM.

    Starts two months back: the current and previous month are not
    published yet, so requesting them just returns nothing.
    """
    today = date.today()
    year, month = today.year, today.month - 2
    while month < 1:
        month += 12
        year -= 1

    out = []
    for _ in range(count):
        out.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month < 1:
            month, year = 12, year - 1
    return out


def fetch_month(month: str) -> bytes | None:
    url = API.format(month=month)
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except Exception as exc:
        print(f"  {month}: FAILED {exc}")
        return None

    payload = response.content
    if len(payload) < 1024:
        print(f"  {month}: empty response ({len(payload)} bytes) - "
              "month probably not published yet")
        return None
    return payload


def read_zip(payload: bytes, depth: int = 0) -> pd.DataFrame:
    """Read the CSV out of Petrinex's archive.

    The download is a zip containing another zip: the outer archive
    holds ``Vol_2026-05-AB.csv.zip``, and the CSV is inside that. This
    recurses rather than assuming one level, so a change in packaging
    does not break it.
    """
    if depth > 3:
        raise ValueError("archive nested deeper than expected")

    frames = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for name in archive.namelist():
            lower = name.lower()
            if lower.endswith(".zip"):
                frames.append(read_zip(archive.read(name), depth + 1))
            elif lower.endswith(".csv"):
                with archive.open(name) as handle:
                    # Everything as string: leading zeros are
                    # significant in facility and BA identifiers, and
                    # pandas would silently eat them.
                    frames.append(
                        pd.read_csv(handle, dtype=str, low_memory=False)
                    )

    if not frames:
        raise ValueError("no CSV inside the archive")
    return pd.concat(frames, ignore_index=True)


def tidy(raw: pd.DataFrame, month: str) -> pd.DataFrame:
    raw.columns = [c.strip() for c in raw.columns]

    # The learning aid names fields with spaces and slashes ("From/To
    # ID"); the CSV header has neither ("FromToID"). Match on letters
    # only so either spelling resolves.
    def column(*candidates: str) -> str | None:
        def squash(text: str) -> str:
            return re.sub(r"[^a-z0-9]", "", text.lower())

        lookup = {squash(actual): actual for actual in raw.columns}
        for candidate in candidates:
            hit = lookup.get(squash(candidate))
            if hit:
                return hit
        return None

    activity = column("Activity ID", "ActivityID")
    product = column("Product ID", "ProductID")
    volume = column("Volume")
    # The identifier without the "ABWI" province/type prefix is what
    # joins to ST37, so prefer it over the full From/To ID.
    well = column("From/To ID Identifier", "FromToIDIdentifier")
    well_full = column("From/To ID", "FromToID")
    well_type = column("From/To ID Type", "FromToIDType")
    operator = column("Operator Name", "OperatorName")
    facility = column("Reporting Facility ID", "ReportingFacilityID")
    fac_type = column("Reporting Facility Type", "ReportingFacilityType")
    subtype = column("Reporting Facility SubType", "ReportingFacilitySubType")
    subtype_desc = column(
        "Reporting Facility SubType Desc", "ReportingFacilitySubTypeDesc"
    )
    hours = column("Hours")
    energy = column("Energy")

    if well is None:
        well = well_full

    missing = [n for n, c in [
        ("ActivityID", activity), ("ProductID", product),
        ("Volume", volume), ("FromToIDIdentifier", well),
    ] if c is None]
    if missing:
        raise ValueError(f"expected columns absent: {missing}")

    frame = raw[raw[activity].str.strip() == PRODUCTION_ACTIVITY].copy()
    frame[product] = frame[product].str.strip()
    frame = frame[frame[product].isin(KEEP_PRODUCTS)]

    # Drop confidential rows: the volume is real but the well is not
    # identifiable, so it cannot be placed on a map.
    frame["confidential"] = frame[well].str.strip() == MASKED
    withheld = int(frame["confidential"].sum())
    frame = frame[~frame["confidential"]]

    out = pd.DataFrame({
        "production_month": month,
        "well_id": frame[well].str.strip(),
        "well_id_type": (
            frame[well_type].str.strip() if well_type else pd.NA
        ),
        "product": frame[product],
        "volume": pd.to_numeric(frame[volume], errors="coerce"),
        "energy_gj": (
            pd.to_numeric(frame[energy], errors="coerce")
            if energy else pd.NA
        ),
        "hours": (
            pd.to_numeric(frame[hours], errors="coerce")
            if hours else pd.NA
        ),
        "operator": frame[operator].str.strip() if operator else pd.NA,
        "facility_id": frame[facility].str.strip() if facility else pd.NA,
        "facility_type": (
            frame[fac_type].str.strip() if fac_type else pd.NA
        ),
        "facility_subtype": (
            frame[subtype].str.strip() if subtype else pd.NA
        ),
        "facility_subtype_desc": (
            frame[subtype_desc].str.strip() if subtype_desc else pd.NA
        ),
    })

    # Split OIL into conventional crude and bitumen. product keeps the
    # code as Petrinex published it; product_class is what the map
    # should read, so the raw value stays auditable.
    out["product_class"] = out["product"]
    is_oil = out["product"] == "OIL"
    if subtype and is_oil.any():
        out.loc[is_oil, "product_class"] = classify_oil(
            out.loc[is_oil, "facility_subtype"]
        )

    out = out.dropna(subset=["volume"])
    out = out[out["volume"] != 0]

    # Convert to the units the rest of the project speaks, and to a
    # daily rate, which is what compares across months of unequal length.
    year, mon = (int(p) for p in month.split("-"))
    days = calendar.monthrange(year, mon)[1]

    is_gas = out["product"] == "GAS"
    out["volume_mmcf"] = (out["volume"] * E3M3_TO_MMCF).where(is_gas)
    out["volume_bbl"] = (out["volume"] * M3_TO_BBL).where(~is_gas)
    out["rate_mmcfd"] = out["volume_mmcf"] / days
    out["rate_bbld"] = out["volume_bbl"] / days
    out["days_in_month"] = days

    out.attrs["withheld_rows"] = withheld
    return out


def inspect(month: str) -> None:
    """Dump the raw shape of one month, to check assumptions."""
    payload = fetch_month(month)
    if payload is None:
        return
    raw = read_zip(payload)
    print(f"\n{month}: {len(raw):,} rows, {len(raw.columns)} columns\n")
    print("columns:")
    for c in raw.columns:
        print(f"   {c}")
    print("\nactivity codes present:")
    act = [c for c in raw.columns if c.lower() == "activity id"][0]
    for value, count in raw[act].str.strip().value_counts().head(12).items():
        print(f"   {value:12}{count:>10,}")
    print("\nsample PROD rows (this is the well-level detail):")
    sample = raw[raw[act].str.strip() == "PROD"].head(3)
    for _, row in sample.iterrows():
        print("   " + " | ".join(
            f"{c}={str(row[c]).strip()[:22]}" for c in raw.columns[:12]
        ))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=int, default=12,
                        help="how many production months to pull")
    parser.add_argument("--inspect", metavar="YYYY-MM",
                        help="print one month's raw structure and exit")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if args.inspect:
        inspect(args.inspect)
        return

    frames, withheld_total = [], 0
    for month in months_back(args.months):
        target = RAW_DIR / f"AB_Vol_{month}.zip"

        if target.exists():
            payload = target.read_bytes()
            print(f"  {month}: cached ({len(payload) / 1e6:.1f} MB)")
        else:
            payload = fetch_month(month)
            if payload is None:
                continue
            target.write_bytes(payload)
            print(f"  {month}: downloaded {len(payload) / 1e6:.1f} MB")
            time.sleep(1.0)

        try:
            tidied = tidy(read_zip(payload), month)
        except Exception as exc:
            print(f"  {month}: could not parse - {exc}")
            continue

        withheld_total += tidied.attrs.get("withheld_rows", 0)
        frames.append(tidied)
        print(f"      {len(tidied):,} well-product rows, "
              f"{tidied['well_id'].nunique():,} wells")

    if not frames:
        raise SystemExit("Nothing downloaded.")

    production = pd.concat(frames, ignore_index=True)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        production.to_parquet(OUTPUT, index=False)
        written = OUTPUT
    except Exception:
        written = OUTPUT.with_suffix(".csv")
        production.to_csv(written, index=False)
        print("  (parquet unavailable, wrote CSV instead)")

    print(f"\nwrote {len(production):,} rows -> {written.name}")
    print(f"  {production['well_id'].nunique():,} distinct wells, "
          f"{production['operator'].nunique():,} operators")
    print(f"  months: {production['production_month'].min()} to "
          f"{production['production_month'].max()}")
    print(f"  confidential rows dropped: {withheld_total:,}")

    print("\n  by product class:")
    for value, group in production.groupby("product_class"):
        gas = value == "GAS"
        unit = "MMcf/d" if gas else "bbl/d"
        rate = (
            group["rate_mmcfd"] if gas else group["rate_bbld"]
        ).sum() / production["production_month"].nunique()
        print(f"    {value:20}{group['well_id'].nunique():>9,} wells "
              f"{rate:>12,.0f} {unit} average")

    print("\n  by raw product code:")
    for value, group in production.groupby("product"):
        unit = "MMcf/d" if value == "GAS" else "bbl/d"
        rate = (
            group["rate_mmcfd"] if value == "GAS" else group["rate_bbld"]
        ).sum() / production["production_month"].nunique()
        print(f"    {value:8}{group['well_id'].nunique():>9,} wells "
              f"{rate:>12,.0f} {unit} average")

    print("\n  NOTE: conventional only. Oil sands and waste plants are "
          "excluded from this feed, as are terminals, meter stations, "
          "pipelines, refineries and gas plant fractionation.")


if __name__ == "__main__":
    main()
