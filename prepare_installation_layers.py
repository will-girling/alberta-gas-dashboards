"""Preprocess the AER pipeline installation shapefile into map layers.

Mirrors prepare_pipeline_layers.py: the heavy GIS file is processed once
here rather than on every dashboard run, and the dashboard reads only
the lightweight GeoJSON written to processed/.

Source
------
Pipeline_Installations_SHP/Pipeline_Installations_GCS_NAD83.shp
    5,493 point installations across Alberta, EPSG:4269.

Outputs
-------
processed/ngtl_compressor_stations.geojson
    NOVA Gas Transmission operating compressor stations (82).
processed/ngtl_meter_stations.geojson
    NOVA Gas Transmission operating meter stations (947).
processed/installation_type_summary.csv
    Counts by operator, installation type and status, for reference.

Field notes
-----------
Field names in the shapefile are truncated to 10 characters by the DBF
format. The untruncated equivalents are in "Pipeline Installations.csv",
which has no geometry, so the shapefile is authoritative here.

There is no station *name* field in this dataset. The only identifier is
LICINSTNO (licence number + installation number, e.g. "80146-10").
Matching these to maintenance-bulletin facility names will require a
separate hand-built lookup.

PERM_APPR is not a commissioning date: every populated value falls in a
four-day window in May 2009, which is an AER data-migration artefact. It
is deliberately not carried through to the output.

Run
---
    python3 prepare_installation_layers.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import geopandas as gpd
import pandas as pd

PROJECT_ROOT = Path("/Users/willgirling/Desktop/NGTL Project")
INSTALLATION_SHP = (
    PROJECT_ROOT
    / "Pipeline_Installations_SHP"
    / "Pipeline_Installations_GCS_NAD83.shp"
)
PROCESSED_DIR = PROJECT_ROOT / "processed"

COMPRESSOR_OUTPUT = PROCESSED_DIR / "ngtl_compressor_stations.geojson"
METER_OUTPUT = PROCESSED_DIR / "ngtl_meter_stations.geojson"
SUMMARY_OUTPUT = PROCESSED_DIR / "installation_type_summary.csv"

NGTL_OPERATOR = "NOVA Gas Transmission Ltd."
OUTPUT_CRS = "EPSG:4326"

# Four sites hold two compressor units at identical coordinates, so one
# would sit invisibly beneath the other and be impossible to hover. Each
# duplicate is nudged onto a small circle around the shared point. The
# offset is ~150 m: invisible at province zoom, enough to separate the
# markers when zoomed in.
COLOCATION_OFFSET_DEGREES = 0.0015

KEEP_FIELDS = [
    "LICINSTNO",
    "INSTA_LIC",
    "INSTA_NUM",
    "INSTA_TYPE",
    "BA_NAME",
    "POWER",
    "PRIME_SORC",
    "INST_LOCAT",
    "FLD_CENTRE",
    "SUBSTANCE1",
    "PLINSTATUS",
]


def separate_colocated(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Nudge exactly-coincident points apart so each stays hoverable."""
    gdf = gdf.copy()
    gdf["_key"] = gdf.geometry.apply(lambda p: (round(p.x, 6), round(p.y, 6)))

    moved = 0
    for _, group in gdf.groupby("_key"):
        if len(group) < 2:
            continue

        for slot, idx in enumerate(group.index):
            angle = 2 * math.pi * slot / len(group)
            point = gdf.at[idx, "geometry"]
            gdf.at[idx, "geometry"] = type(point)(
                point.x + COLOCATION_OFFSET_DEGREES * math.cos(angle),
                point.y + COLOCATION_OFFSET_DEGREES * math.sin(angle),
            )
            moved += 1

    if moved:
        print(f"  separated {moved} co-located points")

    return gdf.drop(columns="_key")


def write_layer(
    gdf: gpd.GeoDataFrame,
    path: Path,
    label: str,
) -> None:
    if gdf.empty:
        print(f"  WARNING: no features for {label}; nothing written")
        return

    out = gdf[KEEP_FIELDS + ["geometry"]].to_crs(OUTPUT_CRS)
    out.to_file(path, driver="GeoJSON")

    size_kb = path.stat().st_size / 1024
    print(f"  wrote {len(out):,} {label} -> {path.name} ({size_kb:,.0f} KB)")


def main() -> None:
    if not INSTALLATION_SHP.exists():
        raise SystemExit(f"Installation shapefile not found: {INSTALLATION_SHP}")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Reading {INSTALLATION_SHP.name} ...")
    gdf = gpd.read_file(INSTALLATION_SHP)
    print(f"  {len(gdf):,} installations, CRS {gdf.crs}")

    missing = [f for f in KEEP_FIELDS if f not in gdf.columns]
    if missing:
        raise SystemExit(
            "Shapefile is missing expected fields: " + ", ".join(missing)
        )

    gdf["POWER"] = pd.to_numeric(gdf["POWER"], errors="coerce")

    summary = (
        gdf.groupby(["BA_NAME", "INSTA_TYPE", "PLINSTATUS"])
        .size()
        .reset_index(name="Count")
        .sort_values("Count", ascending=False)
    )
    summary.to_csv(SUMMARY_OUTPUT, index=False)
    print(f"  wrote summary -> {SUMMARY_OUTPUT.name}")

    ngtl = gdf.loc[
        (gdf["BA_NAME"] == NGTL_OPERATOR)
        & (gdf["PLINSTATUS"] == "Operating")
    ]

    print("\nCompressor stations:")
    compressors = ngtl.loc[ngtl["INSTA_TYPE"] == "Compressor Station"]
    compressors = separate_colocated(compressors)
    write_layer(compressors, COMPRESSOR_OUTPUT, "compressor stations")

    if not compressors.empty:
        power = compressors["POWER"].dropna()
        print(
            f"  power range {power.min():,.0f} to {power.max():,.0f} "
            f"(total {power.sum():,.0f}, median {power.median():,.0f})"
        )

    print("\nMeter stations:")
    meters = ngtl.loc[ngtl["INSTA_TYPE"] == "Meter Station"]
    write_layer(meters, METER_OUTPUT, "meter stations")

    print("\nDone.")


if __name__ == "__main__":
    main()
