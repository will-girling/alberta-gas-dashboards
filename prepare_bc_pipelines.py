"""Download BC transmission pipelines from the BC Energy Regulator.

Why
---
The dashboard's western interconnects - Alberta/BC border, Gordondale,
Groundbirch East, Willow Valley - are where NGTL meets the BC system,
but the map stops at the provincial boundary, so those markers sit at
the edge of nothing. This adds the BC side.

Source
------
BCER "Pipeline Segments (Permitted)", the BC analogue of the AER
shapefile already used for Alberta. Open data under the BCER Open Data
Licence, updated nightly, queried live rather than downloaded by hand:

    https://geoweb-ags.bc-er.ca/arcgis/rest/services/PASR/
        PASR_PL_SEGMENT_LN/MapServer/0/query

Coverage caveat - important
---------------------------
This dataset contains only features collected on or after 11 July 2016.
Legacy infrastructure is therefore largely absent: Westcoast Energy shows
13 segments and Foothills (South B.C.) just 2, against systems that run
for hundreds of kilometres. So this layer shows recent build - the NGTL
BC extension around Groundbirch/Gordondale, Coastal GasLink, FortisBC -
and NOT the Westcoast T-South backbone that matters most for Station 2.
That geometry is CER-regulated and is not published openly.

The layer is honest about this: every segment carries its approval date,
and the dashboard labels the layer as partial.

Output
------
processed/bc_transmission_pipelines.geojson

Run
---
    python3 prepare_bc_pipelines.py
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path("/Users/willgirling/Desktop/NGTL Project")
OUTPUT = PROJECT_ROOT / "processed" / "bc_transmission_pipelines.geojson"

LAYER = (
    "https://geoweb-ags.bc-er.ca/arcgis/rest/services/PASR/"
    "PASR_PL_SEGMENT_LN/MapServer/0"
)
SERVICE = f"{LAYER}/query"

# Transmission only. The dataset is 51% gathering lines, which would bury
# the transmission network the dashboard is about.
#
# Substance is NOT available. The layer publishes 16 fields and none of
# them says what a pipe carries - confirmed by --inspect, not assumed.
# LINE_TYPE is function ('TR' transmission vs gathering), so oil
# transmission comes through it: Trans Mountain, Enbridge liquids,
# Pembina's oil systems.
#
# So the only discriminator the data actually supports is PROPONENT, the
# operator. That is a real limitation and the exclusion below is a
# maintained list, not a derived rule: an oil operator not on it will
# appear on the map. Run
#
#     python3 prepare_bc_pipelines.py --values PROPONENT
#
# to see every operator with a segment count, and add liquids operators
# as they show up.
WHERE = "LINE_TYPE='TR' AND STATUS IN ('Active','New')"

# Operators whose BC transmission is liquids, excluded from a gas map.
# Matched case-insensitively as substrings of PROPONENT, so corporate
# suffixes ("ULC", "Pipeline L.P.") do not need to be exact.
OIL_OPERATOR_TERMS: tuple[str, ...] = (
    # Present in the data, unambiguously liquids.
    "trans mountain",
    "parkland refining",           # refinery feed
    "pkm canada (jet fuel)",
    "vancouver airport fuel",      # jet fuel to YVR
    # Not currently present, kept so they never sneak in later.
    "kinder morgan",
    "pembina",
    "plains midstream",
    "inter pipeline",
    "enbridge pipelines",          # liquids arm, NOT Westcoast Energy gas
)

# Operators in the data whose product is unclear from the name alone.
# Deliberately NOT excluded: dropping a gas line by mistake is worse than
# carrying a short liquids line, and BCER gives nothing to resolve it.
UNCERTAIN_OPERATORS = (
    "Plateau Pipe Line Ltd.",
    "Tidewater Western Pipeline GP Ltd.",
    "Aux Sable Canada Ltd.",
)

FIELDS = [
    "OBJECTID", "PROJECT_NUMBER", "SEGMENT_NUMBER", "LINE_TYPE_DESC",
    "PHYSICAL_PIPE_LENGTH", "STATUS", "PROPONENT", "AUTHORITY_TYPE",
    "ACTIVITY_APPROVAL_DATE",
]

PAGE_SIZE = 1000            # service caps a single response at 2000
REQUEST_TIMEOUT = 120

# Operators worth distinguishing on the map; everything else is context.
KEY_OPERATORS = {
    "NGTL GP Ltd.": "NGTL (BC extension)",
    "Foothills Pipe Lines (South B.C.) Ltd.": "Foothills South BC",
    "Coastal GasLink Pipeline Ltd.": "Coastal GasLink",
    "Westcoast Energy GP Inc.": "Westcoast Energy",
    "Prince Rupert Gas Transmission Ltd.": "Prince Rupert Gas Transmission",
    "NorthRiver Midstream NEBC Connector GP Inc.": "NorthRiver NEBC Connector",
}


def is_oil_operator(proponent: str | None) -> bool:
    name = (proponent or "").lower()
    return any(term in name for term in OIL_OPERATOR_TERMS)


def inspect() -> None:
    """Print the layer's fields, to check what the source actually has."""
    meta = requests.get(LAYER, params={"f": "json"}, timeout=REQUEST_TIMEOUT).json()
    fields = meta.get("fields", [])
    print(f"{len(fields)} fields on the layer\n")
    for field in fields:
        print(f"  {field['name']:32} {field.get('alias', '')}")


def show_values(field: str) -> None:
    """Print distinct values of one field, with segment counts.

    Server-side group-by, so this is one request rather than pulling
    every geometry down to count them locally.
    """
    params = {
        "where": WHERE,
        "outFields": field,
        "groupByFieldsForStatistics": field,
        # Counting on the OID field returns 0 from this service; count a
        # plain attribute instead.
        "outStatistics": json.dumps([{
            "statisticType": "count",
            "onStatisticField": "SEGMENT_NUMBER",
            "outStatisticFieldName": "n",
        }]),
        "returnGeometry": "false",
        "f": "json",
    }
    response = requests.get(SERVICE, params=params, timeout=REQUEST_TIMEOUT)
    rows = response.json().get("features", [])
    if not rows:
        print(f"No values for {field} - is the field name right?")
        return

    print(f"=== {field}, transmission segments only\n")
    for row in sorted(rows, key=lambda r: -r["attributes"].get("n", 0)):
        attrs = row["attributes"]
        value = str(attrs.get(field))
        flag = ""
        if field == "PROPONENT":
            if is_oil_operator(value):
                flag = "  <- excluded as oil"
            elif value in UNCERTAIN_OPERATORS:
                flag = "  <- kept, product unclear"
        print(f"  {value:52} {attrs.get('n', 0):5d}{flag}")


def fetch_page(offset: int) -> dict:
    params = {
        "where": WHERE,
        "outFields": ",".join(FIELDS),
        "returnGeometry": "true",
        "outSR": "4326",                 # the rest of the project is WGS84
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
        "f": "geojson",
    }
    response = requests.get(SERVICE, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inspect", action="store_true",
        help="print the layer's field list, then exit",
    )
    parser.add_argument(
        "--values", metavar="FIELD",
        help="print distinct values of FIELD with counts, then exit",
    )
    args = parser.parse_args()

    if args.inspect:
        inspect()
        return
    if args.values:
        show_values(args.values)
        return

    print(f"Querying BCER: {WHERE}")

    features, offset = [], 0
    while True:
        page = fetch_page(offset)
        batch = page.get("features") or []
        features.extend(batch)
        print(f"  offset {offset:5d}: {len(batch)} features")
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        time.sleep(0.5)

    if not features:
        raise SystemExit("No features returned - check the WHERE clause.")

    # Drop liquids operators. Done here rather than in the WHERE clause
    # because the match is a substring over corporate names, which the
    # ArcGIS query syntax handles poorly and unreadably.
    dropped: dict[str, int] = {}
    kept = []
    for feature in features:
        operator = (feature.get("properties") or {}).get("PROPONENT")
        if is_oil_operator(operator):
            dropped[operator] = dropped.get(operator, 0) + 1
        else:
            kept.append(feature)

    if dropped:
        total = sum(dropped.values())
        print(f"\n  excluded {total} oil segments:")
        for operator, count in sorted(dropped.items(), key=lambda kv: -kv[1]):
            print(f"    {str(operator)[:44]:46} {count:5d}")
    features = kept

    for feature in features:
        props = feature.setdefault("properties", {})
        operator = props.get("PROPONENT") or "Unknown"
        props["operator_group"] = KEY_OPERATORS.get(operator, "Other BC operator")
        props["is_key_operator"] = operator in KEY_OPERATORS

        length_km = (props.get("PHYSICAL_PIPE_LENGTH") or 0) / 1000
        props["tooltip_title"] = KEY_OPERATORS.get(operator, operator)
        props["tooltip_line1"] = f"{operator}"
        props["tooltip_line2"] = (
            f"{props.get('LINE_TYPE_DESC', '—')} · {length_km:,.1f} km"
        )
        props["tooltip_line3"] = (
            f"Project {props.get('PROJECT_NUMBER', '—')} "
            f"seg {props.get('SEGMENT_NUMBER', '—')} · "
            f"{props.get('STATUS', '—')}"
        )
        props["tooltip_line4"] = (
            f"Authority: {props.get('AUTHORITY_TYPE', '—')} · BCER permitted"
        )
        props["tooltip_line5"] = "Post-2016 permits only — layer is partial"
        props["tooltip_line6"] = ""

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )

    size_kb = OUTPUT.stat().st_size / 1024
    print(f"\nwrote {len(features):,} BC transmission segments "
          f"-> {OUTPUT.name} ({size_kb:,.0f} KB)")

    tally: dict[str, int] = {}
    for feature in features:
        group = feature["properties"]["operator_group"]
        tally[group] = tally.get(group, 0) + 1
    print("\n  by operator group:")
    for group, count in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"    {group:32} {count:5d}")


if __name__ == "__main__":
    main()
