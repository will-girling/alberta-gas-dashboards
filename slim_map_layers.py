"""Shrink the map's GeoJSON layers to what the browser actually needs.

Why
---
Every vertex and every property byte in these files is serialised into
the page and shipped to deck.gl on each rerun. The sources are
survey-grade regulatory data, which is the right thing for a regulator
and the wrong thing for a province-scale map:

  - Coordinates carry 13-14 decimal places. That is nanometre precision
    on a map where one screen pixel is roughly 400 m.
  - BC segments average 130 vertices each, some spaced a few metres
    apart, none of which survive rasterisation at this zoom.
  - Roughly a third of each file is properties, and the app reads none
    of them directly - the preparation scripts have already flattened
    what is needed into tooltip_* strings, so the original attributes
    ride along unused.

Cutting those three things is lossless at the zoom levels this dashboard
uses, and takes the payload from ~9.4 MB to ~1.5 MB.

What is NOT done here
---------------------
No feature is dropped and no attribute the app reads is discarded, so
this changes rendering speed and nothing else. Simplification tolerance
is deliberately conservative - see TOLERANCE_DEG.

Output
------
processed/map/<same name>.geojson

The originals are left untouched: they stay the reference copy, and the
dashboard falls back to them if a slim file is missing.

Run
---
    python3 slim_map_layers.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path("/Users/willgirling/Desktop/NGTL Project")
SOURCE_DIR = PROJECT_ROOT / "processed"
OUTPUT_DIR = SOURCE_DIR / "map"

LAYERS = [
    # Every operating gas pipeline in Alberta, not just NGTL. Context
    # for the production map: a well matters commercially because of
    # what it can reach.
    "major_operating_gas_pipelines.geojson",
    "ngtl_operating_pipelines.geojson",
    "bc_transmission_pipelines.geojson",
    "ngtl_meter_stations.geojson",
    "tc_compressor_stations.geojson",
    "ngtl_outage_areas.geojson",
]

# 5 decimal places is about 1.1 m at this latitude - far below one screen
# pixel, so nothing visible changes.
COORD_DECIMALS = 5

# Douglas-Peucker tolerance in degrees. 0.0003 deg is roughly 30 m: below
# a pixel at the zoom this map opens at, and well below the few-km
# georeferencing error already accepted on the station layer. Raising it
# much beyond this starts visibly cutting corners on tight river
# crossings, which is where pipelines genuinely do bend sharply.
TOLERANCE_DEG = 0.0003

# Properties are kept by default. An earlier version of this script used
# a global allowlist of "fields the app reads" and was wrong: several
# layers build their tooltips inside the dashboard from raw regulatory
# fields rather than in the preparation script, so an allowlist blanked
# the meter-station and capacity-area tooltips. Dropping is now opt-in
# per layer and only where every field has been checked against the app.
#
# The saving from dropping properties is small next to the geometry
# saving anyway - it is not worth the risk of a silently empty tooltip.
PROPERTY_DROP: dict[str, set[str]] = {
    # Province-wide gas pipelines. Only the production app reads this
    # file - the NGTL dashboard uses ngtl_operating_pipelines instead -
    # so the AER attributes it does not display can go. Kept:
    # COMP_NAME and OUT_DIAMET for styling and filtering, SUBSTANCE1
    # and SEG_STATUS for the tooltip, LICENCE_NO to trace a segment
    # back to the source.
    "major_operating_gas_pipelines.geojson": {
        "LINE_NO", "LIC_LI_NO", "PLLICSEGID", "BA_CODE", "SEG_LENGTH",
        "FROM_FAC", "TO_FAC", "PIPE_MAOP", "BIDIRE_IND",
        "SUBSTANCE2", "SUBSTANCE3", "GEOM_SRCE",
    },
    # BCER attributes superseded by the tooltip_* strings that
    # prepare_bc_pipelines.py writes. Verified: none appear in the app.
    "bc_transmission_pipelines.geojson": {
        "OBJECTID", "PROJECT_NUMBER", "SEGMENT_NUMBER", "LINE_TYPE_DESC",
        "PHYSICAL_PIPE_LENGTH", "STATUS", "PROPONENT", "AUTHORITY_TYPE",
        "ACTIVITY_APPROVAL_DATE",
    },
}


def round_coords(coords, dp: int = COORD_DECIMALS):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], dp), round(coords[1], dp)]
    return [round_coords(c, dp) for c in coords]


def douglas_peucker(points: list, tolerance: float) -> list:
    """Drop vertices that do not change the line's shape.

    Iterative rather than recursive: some BC segments carry thousands of
    vertices and Python's recursion limit is not worth fighting.
    """
    if len(points) < 3:
        return points

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]

    while stack:
        start, end = stack.pop()
        if end - start < 2:
            continue

        x1, y1 = points[start][0], points[start][1]
        x2, y2 = points[end][0], points[end][1]
        dx, dy = x2 - x1, y2 - y1
        norm = (dx * dx + dy * dy) ** 0.5 or 1e-12

        worst, worst_i = 0.0, start
        for i in range(start + 1, end):
            x, y = points[i][0], points[i][1]
            dist = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / norm
            if dist > worst:
                worst, worst_i = dist, i

        if worst > tolerance:
            keep[worst_i] = True
            stack.append((start, worst_i))
            stack.append((worst_i, end))

    return [p for p, k in zip(points, keep) if k]


def slim_geometry(geometry: dict) -> dict | None:
    coords = geometry.get("coordinates")
    kind = geometry.get("type")
    if not coords or not kind:
        return None

    coords = round_coords(coords)

    if kind == "LineString":
        coords = douglas_peucker(coords, TOLERANCE_DEG)
    elif kind == "MultiLineString":
        coords = [douglas_peucker(part, TOLERANCE_DEG) for part in coords]
    # Points and polygons are left alone: points have one vertex, and the
    # outage-area polygons are already coarse.

    return {"type": kind, "coordinates": coords}


def count_vertices(coords) -> int:
    if isinstance(coords[0], (int, float)):
        return 1
    return sum(count_vertices(c) for c in coords)


def slim_file(name: str) -> tuple[int, int] | None:
    source = SOURCE_DIR / name
    if not source.exists():
        print(f"  {name}: not present, skipped")
        return None

    raw = source.read_text(encoding="utf-8")
    data = json.loads(raw)
    drop = PROPERTY_DROP.get(name, set())

    features, before, after = [], 0, 0
    for feature in data.get("features", []):
        geometry = feature.get("geometry") or {}
        if geometry.get("coordinates"):
            before += count_vertices(geometry["coordinates"])

        slim = slim_geometry(geometry)
        if slim is None:
            continue
        after += count_vertices(slim["coordinates"])

        props = {
            k: v for k, v in (feature.get("properties") or {}).items()
            if k not in drop
        }
        features.append(
            {"type": "Feature", "geometry": slim, "properties": props}
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_DIR / name
    # No indentation and no spaces after separators: this file is read by
    # a machine, and whitespace is a meaningful share of the payload.
    target.write_text(
        json.dumps(
            {"type": "FeatureCollection", "features": features},
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    old, new = len(raw), target.stat().st_size
    print(
        f"  {name:42} {old / 1e6:6.2f} -> {new / 1e6:5.2f} MB "
        f"({100 - new / old * 100:2.0f}% smaller, "
        f"{before:,} -> {after:,} vertices)"
    )
    return old, new


def main() -> None:
    print(f"Slimming map layers -> {OUTPUT_DIR}\n")

    results = [slim_file(name) for name in LAYERS]
    done = [r for r in results if r]
    if not done:
        raise SystemExit("Nothing to slim - are the source layers built?")

    old = sum(r[0] for r in done)
    new = sum(r[1] for r in done)
    print(
        f"\n  total {old / 1e6:.2f} -> {new / 1e6:.2f} MB "
        f"({100 - new / old * 100:.0f}% smaller)"
    )


if __name__ == "__main__":
    sys.exit(main())
