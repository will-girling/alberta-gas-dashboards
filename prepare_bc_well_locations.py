"""BC well coordinates from the BC Energy Regulator, for the Petrinex BC join.

Why this exists
---------------
BC reports THROUGH Petrinex to BCER, but the Petrinex public-data extract
publishes Alberta and Saskatchewan only - every BC month returns HTTP 400.
So unlike Alberta, where one endpoint gives volumes and ST37 gives
locations, BC needs BCER for both.

This matters more than a normal data-plumbing task. The Montney supply
question that the LNG thesis turns on is roughly 1.3 Bcf/d of BC growth
against 0.6 in Alberta - so the province this script unlocks is the one
carrying most of the forecast, and the Alberta analysis in
analyse_montney_supply.py is measuring the smaller, more mature half.

The layers that matter
----------------------
Confirmed present on geoweb-ags.bc-er.ca:

  WELL/WELL_BOTTOM_HOLE_STATE_PT    bottom-hole locations - the direct
                                    analogue of ST37's BH_Latitude, and
                                    the right geometry for play
                                    assignment on horizontals
  WELL/HISTORIC_FRACTURING          frac ACTIVITY - WA number, TD depth,
                                    operator, objective formation, and
                                    expected start/end dates. It does NOT
                                    carry proppant or fluid volumes; that
                                    is BCER's separate Hydraulic Fracture
                                    CSV, or FracFocus.ca.
  ADMIN/UNCONVENTIONAL_PLAY_TRENDS_PY   BCER's own play polygons
  WELL/ACT_DRILL_PT                 currently drilling

Two things make HISTORIC_FRACTURING more useful than it first looks.

OBJECTIVE_FORMATION names the target - "MONTNEY" - so BC wells can be
attributed by formation rather than by the geographic boxes ab_plays.py
uses for Alberta. That is strictly better attribution than the Alberta
half of the analysis has.

OPS_EXPECTED_START_DATE dates the completion. Counting fracs per
formation per quarter is a direct analogue of the Alberta new-well
count, and it needs no production data - which matters, because BC
production is the piece still missing. If BC Montney completion activity
is falling the way Alberta's is, the Alberta finding generalises. If it
is holding up, the story becomes "Alberta is mature, BC is carrying the
growth", which is a different and more defensible thesis.

Discovery
---------
    python3 prepare_bc_well_locations.py --services
    python3 prepare_bc_well_locations.py --layers WELL/WELL_BOTTOM_HOLE_STATE_PT
    python3 prepare_bc_well_locations.py --fields WELL/WELL_BOTTOM_HOLE_STATE_PT/0

Then download both layers:

    python3 prepare_bc_well_locations.py --download wells
    python3 prepare_bc_well_locations.py --download fracs

Production data
---------------
Still outstanding. BCER's Data Centre and the Legacy Well Lookup are the
routes; the latter sits behind a logon. The GIS Open Data Portal at
data-bc-er.opendata.arcgis.com is the first place to check for an
unauthenticated monthly volumes extract.

BC identifies wells by Well Authorization number, not the Alberta
16-character UWI, so none of the UWI parsing in
prepare_well_production.py transfers.

Output
------
processed/bc_well_locations.parquet
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT = PROJECT_ROOT / "processed" / "bc_well_locations.parquet"

ROOT = "https://geoweb-ags.bc-er.ca/arcgis/rest/services"
REQUEST_TIMEOUT = 300

# ArcGIS caps a single response; page through rather than trusting that
# one request returned everything. A silent truncation here would look
# exactly like "BC has fewer wells than expected".
PAGE_SIZE = 1000


def get_json(url: str, params: dict | None = None) -> dict:
    params = {**(params or {}), "f": "json"}
    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def list_services() -> None:
    """Every service, including inside folders."""
    root = get_json(ROOT)
    print("Root services:")
    for service in root.get("services", []):
        print(f"  {service['name']}  ({service['type']})")

    for folder in root.get("folders", []):
        print(f"\nFolder {folder}:")
        try:
            sub = get_json(f"{ROOT}/{folder}")
        except Exception as error:
            print(f"  could not read: {error}")
            continue
        for service in sub.get("services", []):
            print(f"  {service['name']}  ({service['type']})")


def list_layers(service: str) -> None:
    data = get_json(f"{ROOT}/{service}/MapServer")
    # An unknown service returns a valid JSON error rather than a 404,
    # which previously printed as "0 fields" and looked like an empty
    # layer instead of a wrong name.
    if "error" in data:
        raise SystemExit(f"{service}: {data['error'].get('message')} "
                         "- check the name against --services")
    print(f"{service} layers:")
    for layer in data.get("layers", []):
        print(f"  [{layer['id']}] {layer['name']}")
    for table in data.get("tables", []):
        print(f"  (table) [{table['id']}] {table['name']}")


def list_fields(layer_path: str) -> None:
    """Field names and a sample row, because names alone mislead."""
    service, layer_id = layer_path.rsplit("/", 1)
    base = f"{ROOT}/{service}/MapServer/{layer_id}"
    data = get_json(base)
    print(f"{data.get('name')} — {len(data.get('fields', []))} fields\n")
    for field in data.get("fields", []):
        print(f"  {field['name']:34}{field['type']:24}{field.get('alias','')}")

    sample = get_json(f"{base}/query",
                      {"where": "1=1", "outFields": "*", "resultRecordCount": 1,
                       "returnGeometry": "true"})
    features = sample.get("features", [])
    if features:
        print("\nSample record:")
        print(json.dumps(features[0], indent=2)[:1800])


# Named presets, so the field lists live with the code rather than in a
# shell command. Verified against the layers' own metadata.
DATASETS = {
    "wells": {
        "layer": "WELL/WELL_BOTTOM_HOLE_STATE_PT/0",
        "output": "bc_well_locations.parquet",
        "fields": [
            "WELL_AUTHORITY_NUMBER", "UNIQUE_WELL_IDENTIFIER",
            "WELL_ACTIVITY", "BORE_FLUID_TYPE", "OPERATION_TYPE",
            "OPERATOR_ABBREVIATION", "WELL_NAME", "WELL_AREA_NAME",
            "STATUS_EFFECTIVE_DATE",
        ],
        "label": "wells (bottom-hole)",
    },
    "fracs": {
        "layer": "WELL/HISTORIC_FRACTURING/0",
        "output": "bc_frac_activity.parquet",
        "fields": [
            "WA_NUM", "OPERATOR_ABBREVIATION", "WELL_NAME",
            "OBJECTIVE_FORMATION", "TD_DEPTH",
            "OPS_EXPECTED_START_DATE", "OPS_EXPECTED_END_DATE",
        ],
        "label": "frac activity",
    },
}

# ArcGIS returns dates as epoch milliseconds.
DATE_FIELDS = ("STATUS_EFFECTIVE_DATE", "OPS_EXPECTED_START_DATE",
               "OPS_EXPECTED_END_DATE")


def download(name: str) -> None:
    spec = DATASETS[name]
    service, layer_id = spec["layer"].rsplit("/", 1)
    base = f"{ROOT}/{service}/MapServer/{layer_id}/query"
    fields = spec["fields"]

    print(f"Downloading {spec['label']} from {spec['layer']}")
    rows: list[dict] = []
    offset = 0
    while True:
        page = get_json(base, {
            "where": "1=1",
            "outFields": ",".join(fields),
            "returnGeometry": "true",
            # WGS84. The layer's native CRS is BC Albers, so without this
            # the coordinates come back as metres and silently land in
            # the Gulf of Guinea when treated as degrees.
            "outSR": 4326,
            "resultOffset": offset,
            "resultRecordCount": PAGE_SIZE,
        })
        if "error" in page:
            raise SystemExit(f"query failed: {page['error'].get('message')}")

        features = page.get("features", [])
        if not features:
            break

        for feature in features:
            geometry = feature.get("geometry") or {}
            attributes = feature.get("attributes") or {}
            rows.append({
                **{k: attributes.get(k) for k in fields},
                "lon": geometry.get("x"),
                "lat": geometry.get("y"),
            })

        offset += len(features)
        print(f"  {offset:,} records...", end="\r")
        if not page.get("exceededTransferLimit") and len(features) < PAGE_SIZE:
            break

    frame = pd.DataFrame(rows)
    print(f"\n{len(frame):,} records")

    for column in DATE_FIELDS:
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], unit="ms",
                                           errors="coerce")

    located = frame[frame["lat"].notna() & frame["lon"].notna()]
    if not located.empty:
        print(f"  {len(located):,} with coordinates — "
              f"lat {located['lat'].min():.2f} to {located['lat'].max():.2f}, "
              f"lon {located['lon'].min():.2f} to {located['lon'].max():.2f}")
        if not located["lat"].between(47, 61).all():
            print("  WARNING: coordinates are not lat/lon. outSR was "
                  "ignored — do not use these until fixed.")

    if "OBJECTIVE_FORMATION" in frame.columns:
        print("\n  top objective formations:")
        for k, v in frame["OBJECTIVE_FORMATION"].value_counts().head(8).items():
            print(f"    {str(k)[:28]:30}{v:>7,}")

    out = PROJECT_ROOT / "processed" / spec["output"]
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(out, index=False)
    print(f"\n  -> {out.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--services", action="store_true",
                        help="list every ArcGIS service, then exit")
    parser.add_argument("--layers", metavar="SERVICE",
                        help="list layers on a service, e.g. PASR/PASR_WELL_PT")
    parser.add_argument("--fields", metavar="SERVICE/LAYER_ID",
                        help="list fields and one sample record, then exit")
    parser.add_argument("--download", choices=sorted(DATASETS),
                        help="download a named dataset: wells or fracs")
    args = parser.parse_args()

    if args.services:
        list_services()
    elif args.layers:
        list_layers(args.layers)
    elif args.fields:
        list_fields(args.fields)
    elif args.download:
        download(args.download)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
