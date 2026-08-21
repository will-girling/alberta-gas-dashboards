"""Build browser-sized map layers from well-level production.

Why this is not just a filter
-----------------------------
The latest month has 116,748 located wells. As GeoJSON that is about
10.5 MB before any properties, against 2.36 MB for the entire NGTL map -
which was already the slow part of that app.

Production is concentrated enough to make this easy rather than a
compromise. Measured on the latest month's gas:

    top  1% of wells (1,159)   30.4% of production
    top  5% (5,796)            62.5%
    top 10% (11,592)           76.7%
    top 25% (28,981)           91.1%

and 84% of wells produce under 0.1 MMcf/d while carrying 15.3% of the
gas between them.

So the layer is built in two parts:

  wells      individual points above a rate threshold. Everything the
             eye can actually resolve and nearly all the volume.
  townships  the remainder rolled to DLS township centroids, so the
             long tail still shows as density rather than vanishing.

Nothing is discarded: a well below the threshold is in the township
aggregate, and the aggregate reports how many wells it stands for.

Output
------
processed/map/ab_wells_<product>.geojson
processed/map/ab_well_townships_<product>.geojson

Run
---
    python3 prepare_well_map_layer.py
    python3 prepare_well_map_layer.py --threshold 0.05
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path("/Users/willgirling/Desktop/NGTL Project")
SOURCE = PROJECT_ROOT / "processed" / "ab_well_production_located.parquet"
OUTPUT_DIR = PROJECT_ROOT / "processed" / "map"

# Products to build layers for. BITUMEN is deliberately absent by
# default: at 1.85M bbl/d it dominates any output-scaled symbol, and it
# is a different business from the gas book this sits beside. Add it
# here if it is wanted.
PRODUCTS = ["GAS", "COND", "CRUDE_OIL"]

# Individual points above this rate; everything else is aggregated.
# MMcf/d for gas, bbl/d for liquids.
THRESHOLDS = {"GAS": 0.1, "COND": 5.0, "CRUDE_OIL": 5.0}

# ~1.1 m. Far below a screen pixel at any zoom this map uses.
COORD_DECIMALS = 5

# DLS township is about 10 km square - a sensible bin for the tail, and
# it is a real unit operators think in rather than an arbitrary grid.
TOWNSHIP_DECIMALS = 1


def rate_column(product: str) -> str:
    return "rate_mmcfd" if product == "GAS" else "rate_bbld"


def unit(product: str) -> str:
    return "MMcf/d" if product == "GAS" else "bbl/d"


def latest_month(frame: pd.DataFrame) -> str:
    return frame["production_month"].max()


def well_points(
    wells: pd.DataFrame, product: str, operators: dict[str, int]
) -> list[dict]:
    """Compact point features.

    Property names are single letters and the tooltip is NOT baked in.
    An earlier version wrote six tooltip_* strings per well and came to
    9.7 MB for gas alone - the text outweighed the geometry roughly ten
    to one, and every operator name was repeated once per well. Operator
    is an index into a lookup shipped once; the app composes the tooltip
    from these fields at render time.

    r  rate            o  operator index
    n  well name       u  UWI
    f  facility index  y  spud year        d  total depth, m
    m  match tier, only when it is the weaker location-only join

    Facility is the gathering point a well reports into - the bridge
    between this map and the pipeline side, since a well matters
    commercially because of what it can reach.
    """
    rate = rate_column(product)
    features = []
    for row in wells.itertuples():
        props = {
            "r": round(getattr(row, rate), 2),
            "o": operators.get(row.operator or "", -1),
            "n": (row.well_name or "")[:40],
            "u": row.uwi or "",
        }
        if getattr(row, "facility_idx", -1) >= 0:
            props["f"] = int(row.facility_idx)
        if getattr(row, "spud_year", None) and row.spud_year == row.spud_year:
            props["y"] = int(row.spud_year)
        if getattr(row, "depth", None) and row.depth == row.depth:
            props["d"] = int(row.depth)
        # Only carried when true, so the common case costs nothing.
        if row.match == "location":
            props["m"] = 1

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [
                    round(row.lon, COORD_DECIMALS),
                    round(row.lat, COORD_DECIMALS),
                ],
            },
            "properties": props,
        })
    return features


def township_bins(
    wells: pd.DataFrame, product: str, operators: dict[str, int]
) -> list[dict]:
    """Roll sub-threshold wells to a coarse grid.

    r  combined rate   w  well count   o  dominant operator index
    """
    rate = rate_column(product)
    binned = wells.assign(
        blat=wells["lat"].round(TOWNSHIP_DECIMALS),
        blon=wells["lon"].round(TOWNSHIP_DECIMALS),
    )
    grouped = binned.groupby(["blat", "blon"]).agg(
        rate=(rate, "sum"),
        wells=("uwi", "nunique"),
        operator=("operator", lambda s: s.value_counts().index[0]
                  if len(s.dropna()) else ""),
    ).reset_index()

    return [{
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [float(row.blon), float(row.blat)],
        },
        "properties": {
            "r": round(row.rate, 2),
            "w": int(row.wells),
            "o": operators.get(row.operator or "", -1),
        },
    } for row in grouped.itertuples()]


def write(features: list[dict], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"type": "FeatureCollection", "features": features},
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return path.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float,
                        help="override the gas threshold, MMcf/d")
    parser.add_argument("--month", help="production month, default latest")
    args = parser.parse_args()

    if not SOURCE.exists():
        raise SystemExit(
            f"{SOURCE.name} not found - run prepare_well_production.py"
        )

    frame = pd.read_parquet(SOURCE)
    month = args.month or latest_month(frame)
    print(f"Production month: {month}")

    frame = frame[
        (frame["production_month"] == month)
        & frame["BH_Latitude"].notna()
    ].copy()

    # One row per well: a well can report through more than one facility
    # in a month, and drawing it twice would double its symbol.
    frame = frame.rename(columns={
        "BH_Latitude": "lat", "BH_Longitude": "lon",
        "Licensee": "licensee", "Well_Name": "well_name",
        "Prod_String_UWI": "uwi",
    })

    # Derived once for all products.
    #
    # Facility label pairs the ID with its subtype description, because
    # "ABBT0051211" alone says nothing - "ABBT0051211 · CRUDE OIL
    # MULTIWELL PRORATION BATTERY" says what kind of gathering point it
    # is. Both come from the volumetric file, so no extra source.
    frame["facility_label"] = (
        frame["facility_id"].fillna("")
        + frame["facility_subtype_desc"].fillna("").radd(" · ").where(
            frame["facility_subtype_desc"].notna(), ""
        )
    ).str.strip(" ·")

    # Optional: these arrive only once prepare_well_production.py has
    # been re-run with the wider ST37 column list. Absent, the layer
    # still builds and simply carries no vintage or depth.
    if "Spud_Date" in frame.columns:
        frame["spud_year"] = pd.to_datetime(
            frame["Spud_Date"], errors="coerce", utc=True
        ).dt.year
    else:
        frame["spud_year"] = pd.NA
        print("  note: Spud_Date absent - re-run prepare_well_production.py "
              "for well vintage")

    if "Final_Total_Depth" in frame.columns:
        frame["depth"] = pd.to_numeric(
            frame["Final_Total_Depth"], errors="coerce"
        ).round()
    else:
        frame["depth"] = pd.NA

    facility_names = sorted(
        v for v in frame["facility_label"].dropna().unique() if v
    )
    facilities = {name: i for i, name in enumerate(facility_names)}
    facility_path = OUTPUT_DIR / "ab_facilities.json"
    facility_path.parent.mkdir(parents=True, exist_ok=True)
    facility_path.write_text(
        json.dumps(facility_names, separators=(",", ":")), encoding="utf-8"
    )
    print(f"  {len(facility_names):,} facilities -> {facility_path.name} "
          f"({facility_path.stat().st_size / 1024:.0f} KB)")

    # One lookup for every operator name, shipped once instead of
    # repeated on every well. 401 operators against 116,748 wells.
    names = sorted(frame["operator"].dropna().unique())
    operators = {name: i for i, name in enumerate(names)}
    lookup_path = OUTPUT_DIR / "ab_operators.json"
    lookup_path.parent.mkdir(parents=True, exist_ok=True)
    lookup_path.write_text(json.dumps(names, separators=(",", ":")),
                           encoding="utf-8")
    print(f"  {len(names)} operators -> {lookup_path.name} "
          f"({lookup_path.stat().st_size / 1024:.0f} KB)")

    total_bytes = lookup_path.stat().st_size
    for product in PRODUCTS:
        subset = frame[frame["product_class"] == product]
        if subset.empty:
            print(f"\n{product}: no rows")
            continue

        rate = rate_column(product)
        wells = subset.groupby("well_id", as_index=False).agg(
            lat=("lat", "first"), lon=("lon", "first"),
            operator=("operator", "first"), licensee=("licensee", "first"),
            well_name=("well_name", "first"), uwi=("uwi", "first"),
            match=("match", "first"),
            facility=("facility_label", "first"),
            spud_year=("spud_year", "first"), depth=("depth", "first"),
            **{rate: (rate, "sum")},
        )
        wells["facility_idx"] = wells["facility"].map(
            lambda f: facilities.get(f, -1)
        )

        cutoff = (
            args.threshold if (args.threshold and product == "GAS")
            else THRESHOLDS[product]
        )
        big = wells[wells[rate] >= cutoff]
        small = wells[wells[rate] < cutoff]

        total = wells[rate].sum()
        share = big[rate].sum() / total * 100 if total else 0

        points = write(
            well_points(big, product, operators),
            OUTPUT_DIR / f"ab_wells_{product.lower()}.geojson",
        )
        bins = write(
            township_bins(small, product, operators),
            OUTPUT_DIR / f"ab_well_townships_{product.lower()}.geojson",
        )
        total_bytes += points + bins

        print(f"\n{product} — threshold {cutoff:g} {unit(product)}")
        print(f"   {len(wells):>8,} wells, {total:>12,.0f} {unit(product)}")
        print(f"   {len(big):>8,} drawn individually  "
              f"({share:.1f}% of production, {points / 1e6:.2f} MB)")
        print(f"   {len(small):>8,} aggregated  "
              f"({100 - share:.1f}% of production, {bins / 1e6:.2f} MB)")

    print(f"\ntotal payload {total_bytes / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
