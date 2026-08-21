"""Download and normalise TC's NGTL outage capacity areas.

What this solves
----------------
Outages name a capacity table (EGAT, USJR, ...), not a pipe. Until now
there was no geometry to attach them to: AER pipeline data carries no
NGTL segment or corridor identifier, and TC's published maps are rasters.

TC's own outage map turns out to serve the area polygons directly:

    GET https://f51561ras5.execute-api.us-west-2.amazonaws.com/production/areas

Each area carries its vertex list, TC's own fill colour, and - valuably -
a monthly *base* capability series. That base is what makes outage
severity meaningful: derate is measured against the capability that
would otherwise apply that month, rather than against a proxy.

Same host as the CSR and GDSR endpoints, and it needs no credentials
(the app sends "Bearer undefined").

Outputs
-------
outage_areas_raw.json                    raw response, kept immutable
processed/ngtl_outage_areas.geojson      area polygons
processed/ngtl_area_capabilities.csv     monthly base capability

Notes
-----
- FHBC/FHSK are the map's acronyms; the outage export uses dopAcronym
  (FHZ8/FHZ9). Both are carried so either joins.
- LCLR, LCLD, RPTA and DPTA have no geometry at TC either - they are
  local points and plant turnarounds, which is why TC's own map footer
  says local outages are not displayed.

Run
---
    python3 prepare_outage_areas.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path("/Users/willgirling/Desktop/NGTL Project")
AREAS_URL = (
    "https://f51561ras5.execute-api.us-west-2.amazonaws.com/production/areas"
)
RAW_OUTPUT = PROJECT_ROOT / "outage_areas_raw.json"
GEOJSON_OUTPUT = PROJECT_ROOT / "processed" / "ngtl_outage_areas.geojson"
CAPABILITY_OUTPUT = PROJECT_ROOT / "processed" / "ngtl_area_capabilities.csv"

E3M3_TO_MMCFD = 35.3147 / 1000

HEADERS = {
    "accept": "*/*",
    "content-type": "application/json",
    "origin": "https://my.tccustomerexpress.com",
    "referer": "https://my.tccustomerexpress.com/",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
    ),
}


def parse_rgba(colour: str) -> list[int]:
    """TC gives fills as 'rgba(r, g, b, a)'; return an RGBA byte list."""
    if not colour or not colour.startswith("rgba"):
        return [150, 158, 172, 120]

    parts = colour[colour.index("(") + 1: colour.index(")")].split(",")
    r, g, b = (int(float(p)) for p in parts[:3])
    a = int(float(parts[3]) * 255) if len(parts) > 3 else 128

    return [r, g, b, a]


def main() -> None:
    print(f"Fetching {AREAS_URL} ...")
    response = requests.get(AREAS_URL, headers=HEADERS, timeout=45)
    response.raise_for_status()
    payload = response.json()

    if payload.get("message") != "Success" or "data" not in payload:
        raise SystemExit(f"Unexpected response shape: {list(payload)[:5]}")

    RAW_OUTPUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"  saved raw response -> {RAW_OUTPUT.name}")

    areas = payload["data"]
    print(f"  {len(areas)} areas returned")

    features, cap_rows = [], []
    for area in areas:
        acronym = area.get("acronym")
        locations = area.get("locations") or []

        for cap in area.get("capabilities") or []:
            cap_rows.append({
                "acronym": acronym,
                "dop_acronym": area.get("dopAcronym"),
                "start": cap.get("startDate"),
                "end": cap.get("endDate"),
                "base_capability_e3m3d": cap.get("capability"),
                "base_capability_mmcfd": (
                    (cap.get("capability") or 0) * E3M3_TO_MMCFD
                ),
            })

        if len(locations) < 3:
            print(f"    {acronym:6} no polygon ({len(locations)} vertices)")
            continue

        # Vertices come newest-id-first; ascending id traces the ring.
        ring = [
            [loc["lng"], loc["lat"]]
            for loc in sorted(locations, key=lambda p: p["id"])
        ]
        ring.append(ring[0])

        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {
                "acronym": acronym,
                "dop_acronym": area.get("dopAcronym"),
                "display_name": area.get("displayName"),
                "type_name": area.get("typeName"),
                "tc_colour": parse_rgba(area.get("color")),
                "notes": (area.get("notes") or "").strip(),
                "assumptions": (area.get("capabilityAssumptions") or "").strip(),
                "center_lat": area.get("centerLat"),
                "center_lng": area.get("centerLng"),
                "vertices": len(ring) - 1,
            },
        })
        print(f"    {acronym:6} polygon with {len(ring)-1} vertices")

    GEOJSON_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    GEOJSON_OUTPUT.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )
    print(f"\nwrote {len(features)} area polygons -> {GEOJSON_OUTPUT.name}")

    caps = pd.DataFrame(cap_rows)
    if not caps.empty:
        caps["start"] = pd.to_datetime(caps["start"], errors="coerce")
        caps["end"] = pd.to_datetime(caps["end"], errors="coerce")
        caps = caps.dropna(subset=["start"]).sort_values(["acronym", "start"])
        caps.to_csv(CAPABILITY_OUTPUT, index=False)
        print(f"wrote {len(caps)} monthly capability rows "
              f"-> {CAPABILITY_OUTPUT.name}")
        print(f"  covering {caps.start.min():%Y-%m} to {caps.end.max():%Y-%m} "
              f"for {caps.acronym.nunique()} areas")


if __name__ == "__main__":
    main()
