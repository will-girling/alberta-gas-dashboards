"""Plant-level C5+ condensate, and why it needs its own script.

The problem this solves
-----------------------
prepare_well_production.py reads ProductID == "COND" on PROD activity at
batteries. That is field condensate - liquid dropped out at a battery the
operator owns and measures. It is real, but it is a minority of Alberta's
condensate:

    Plant C5-SP (spec pentanes plus)   275,938 bbl/d
    Plant C5-MX (mix)                   56,220
    Battery COND (field)                95,870
                                       --------
    Alberta C5+                       ~372,000 bbl/d

Against that, the well-level file carries 67,951 bbl/d for located wells -
about 18% of the real stream.

The gap is not missing data. It is *where the data sits*. Petrinex reports
a volume at the facility that measures it. An operator whose raw gas goes
to a third-party deep-cut or straddle plant has its C5+ stripped downstream
and booked against the plant, never against the well. So ARC - which meters
liquids at its own effluent batteries - shows 84 bbl/MMcf, while Ovintiv
shows 0.1 bbl/MMcf in Kakwa, one of the most condensate-rich areas on the
continent. That contrast is measurement, not geology, and reading it as
geology would be badly wrong.

What this script does NOT do
----------------------------
It does not push plant volumes back to wells. That was tested and rejected:
gas receipts recorded at plants total 613 MMcf/d against 11,650 MMcf/d of
Alberta production, and only 3.8% of those receipts name a facility present
in the well file. Most gas arrives through gathering systems whose upstream
legs are not reported here. Allocating on that basis would be invention
dressed as measurement.

It also does not treat the plant operator as the producer. The largest C5+
processors are Pembina Gas Infrastructure and Keyera - midstream companies
that own none of the molecules they handle.

So the honest product is a map of *where condensate is recovered*, which is
a real and separate fact from where it is produced, and which the well
layer cannot show at all.

Geocoding
---------
Plants carry a DLS location (township, range, meridian) but no coordinates.
Rather than convert DLS analytically - which has to cope with correction
lines and drifting range widths - township centroids are derived
empirically from the well file, where UWI and latitude/longitude are both
present. 2,695 townships, built from 158,549 well-rows. Same survey grid,
so the errors that matter cancel.

Output
------
processed/map/ab_plant_condensate.geojson
processed/plant_condensate.csv

Run
---
    python3 prepare_plant_condensate.py
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
RAW_DIR = PROJECT_ROOT / "petrinex_raw"
WELLS = PROJECT_ROOT / "processed" / "ab_well_production_located.parquet"
OUTPUT_DIR = PROJECT_ROOT / "processed"
MAP_DIR = OUTPUT_DIR / "map"

# C5-SP is spec pentanes plus - the sales stream that becomes diluent.
# C5-MX is the unfractionated mix; FRAC activity converts it to C5-SP, so
# counting both PROC volumes would double count the fractionated portion.
# C5-SP alone is the defensible plant number.
PLANT_PRODUCT = "C5-SP"
PLANT_ACTIVITY = "PROC"

# GP is a gas plant, GS a gas gathering system. Both strip liquids.
PLANT_TYPES = ("GP", "GS")

# Petrinex volumes are cubic metres per month.
M3_PER_BBL = 0.158987

# Below this a plant is a rounding error on the map and only adds clutter.
MIN_BBLD = 25.0

COORD_DECIMALS = 5

UWI_DLS = re.compile(r"^\d\d/\d\d-\d\d-(\d{3})-(\d{2})W(\d)/")


def read_zip(blob: bytes):
    """Petrinex ships a zip inside a zip, so recurse."""
    archive = zipfile.ZipFile(io.BytesIO(blob))
    for name in archive.namelist():
        data = archive.read(name)
        if name.lower().endswith(".zip"):
            yield from read_zip(data)
        elif name.lower().endswith(".csv"):
            yield name, data


def latest_volume_file() -> Path:
    files = sorted(RAW_DIR.glob("AB_Vol_*.zip"))
    if not files:
        raise SystemExit(
            f"no AB_Vol_*.zip in {RAW_DIR} - run download_petrinex_volumes.py"
        )
    return files[-1]


def township_centroids() -> pd.DataFrame:
    """Empirical DLS township -> lat/lon, from wells that carry both."""
    if not WELLS.exists():
        raise SystemExit(
            f"{WELLS.name} not found - run prepare_well_production.py"
        )

    wells = pd.read_parquet(
        WELLS,
        columns=["production_month", "Prod_String_UWI",
                 "BH_Latitude", "BH_Longitude", "well_id"],
    )
    wells = wells[
        (wells["production_month"] == wells["production_month"].max())
        & wells["BH_Latitude"].notna()
    ]

    parts = wells["Prod_String_UWI"].astype(str).str.extract(UWI_DLS)
    wells = wells.assign(
        twp=pd.to_numeric(parts[0], errors="coerce"),
        rge=pd.to_numeric(parts[1], errors="coerce"),
        mer=pd.to_numeric(parts[2], errors="coerce"),
    ).dropna(subset=["twp", "rge", "mer"])

    # Median rather than mean: a township with one stray mislocated well
    # should not drag its centroid across the county.
    return wells.groupby(["mer", "twp", "rge"]).agg(
        lat=("BH_Latitude", "median"),
        lon=("BH_Longitude", "median"),
        wells=("well_id", "size"),
    ).reset_index()


def load_plants(path: Path) -> pd.DataFrame:
    name, data = next(read_zip(path.read_bytes()))
    frame = pd.read_csv(io.BytesIO(data), low_memory=False)
    frame.columns = [c.strip() for c in frame.columns]

    for column in ("ActivityID", "ProductID", "ReportingFacilityType",
                   "ReportingFacilityID", "ReportingFacilityName",
                   "OperatorName"):
        frame[column] = frame[column].astype(str).str.strip()

    frame["Volume"] = pd.to_numeric(frame["Volume"], errors="coerce").fillna(0)

    plants = frame[
        (frame["ActivityID"] == PLANT_ACTIVITY)
        & (frame["ProductID"] == PLANT_PRODUCT)
        & frame["ReportingFacilityType"].isin(PLANT_TYPES)
    ].copy()

    days = pd.to_datetime(plants["ProductionMonth"] + "-01").dt.days_in_month
    plants["rate_bbld"] = plants["Volume"] / M3_PER_BBL / days

    grouped = plants.groupby("ReportingFacilityID", as_index=False).agg(
        name=("ReportingFacilityName", "first"),
        operator=("OperatorName", "first"),
        facility_type=("ReportingFacilityType", "first"),
        twp=("FacilityTownship", "first"),
        rge=("FacilityRange", "first"),
        mer=("FacilityMeridian", "first"),
        location=("ReportingFacilityLocation", "first"),
        rate_bbld=("rate_bbld", "sum"),
    )
    grouped["month"] = plants["ProductionMonth"].iloc[0]
    return grouped


def main() -> None:
    source = latest_volume_file()
    print(f"Reading {source.name}")

    plants = load_plants(source)
    month = plants["month"].iloc[0]
    print(f"Production month: {month}")
    print(f"  {len(plants):,} facilities reporting {PLANT_PRODUCT}, "
          f"{plants['rate_bbld'].sum():,.0f} bbl/d")

    centroids = township_centroids()
    print(f"  {len(centroids):,} township centroids from the well file")

    for column in ("twp", "rge", "mer"):
        plants[column] = pd.to_numeric(plants[column], errors="coerce")

    located = plants.merge(centroids, on=["mer", "twp", "rge"], how="left")
    hit = located["lat"].notna()
    volume_hit = located.loc[hit, "rate_bbld"].sum() / located["rate_bbld"].sum()
    print(f"  geocoded {hit.sum():,} of {len(located):,} facilities "
          f"({volume_hit * 100:.1f}% of volume)")

    located = located[hit & (located["rate_bbld"] >= MIN_BBLD)].copy()
    located = located.sort_values("rate_bbld", ascending=False)
    print(f"  {len(located):,} above {MIN_BBLD:g} bbl/d, "
          f"{located['rate_bbld'].sum():,.0f} bbl/d mapped")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / "plant_condensate.csv"
    located.drop(columns=["wells"]).to_csv(csv_path, index=False)
    print(f"  -> {csv_path.name}")

    # Property keys stay short for the same reason the well layer's do:
    # this ships to a browser. r rate, o operator, n name, l DLS location,
    # t facility type.
    features = [{
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [
                round(row.lon, COORD_DECIMALS),
                round(row.lat, COORD_DECIMALS),
            ],
        },
        "properties": {
            "r": round(row.rate_bbld, 1),
            "o": (row.operator or "")[:44],
            "n": (row.name or "")[:44],
            "l": row.location or "",
            "t": row.facility_type,
        },
    } for row in located.itertuples()]

    MAP_DIR.mkdir(parents=True, exist_ok=True)
    geo_path = MAP_DIR / "ab_plant_condensate.geojson"
    geo_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features},
                   separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"  -> {geo_path.name} ({geo_path.stat().st_size / 1024:.0f} KB)")

    print("\nTop plants by C5+ recovered — processor, NOT gas owner:")
    for row in located.head(10).itertuples():
        print(f"  {row.name[:34]:36}{row.operator[:26]:28}{row.rate_bbld:>9,.0f}")


if __name__ == "__main__":
    main()
