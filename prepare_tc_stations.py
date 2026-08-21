"""Extract TC's own named compressor stations from the Segment Codes map.

Why this exists alongside the AER layer
---------------------------------------
AER gives exact geometry and installed power but no station name, and no
flow-direction attribute (BIDIRE_IND is empty on all 1,698 NGTL
segments). TC's outage tracker names facilities, so an AER-based layer
can never be linked to maintenance.

TC's "NGTL System - Segment Codes & Project Areas" map carries both
things AER lacks: the station names, and a distinct ESRI marker glyph
("X") for stations the legend calls "Compressor Station Multi-direction"
- i.e. the points where the system can physically reverse.

This script pulls those out so stations can be labelled and matched to
outage notices by name.

Accuracy
--------
Positions come from georeferencing the map page against town labels with
known coordinates (quadratic fit, outlier-rejected). Good to a few km -
fine for a labelled marker on a province-scale map, and deliberately NOT
used to join to AER licence numbers, which needs precision this cannot
deliver. See prepare_station_crosswalk.py for why that join fails.

Output
------
processed/tc_compressor_stations.geojson

Run
---
    python3 prepare_tc_stations.py
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pdfplumber
from shapely.geometry import Point
from shapely.ops import nearest_points

PROJECT_ROOT = Path("/Users/willgirling/Desktop/NGTL Project")
SEGMENT_MAP = PROJECT_ROOT / "NGTL_Segment_Codes_Map_Feb2025.pdf"
OUTPUT = PROJECT_ROOT / "processed" / "tc_compressor_stations.geojson"

# Town labels with known coordinates, used to georeference the page.
# Edmonton/Morinville/Leduc are excluded: they sit in the map's inset.
ANCHORS = {
    "Athabasca": (54.72, -113.29), "Banff": (51.18, -115.57),
    "Bowden": (51.93, -114.03), "Calgary": (51.05, -114.07),
    "Camrose": (53.02, -112.83), "Carstairs": (51.56, -114.10),
    "Claresholm": (50.03, -113.58), "Cochrane": (51.19, -114.47),
    "Didsbury": (51.66, -114.14), "Hinton": (53.41, -117.59),
    "Innisfail": (52.03, -113.95), "Jasper": (52.87, -118.08),
    "Lethbridge": (49.69, -112.83), "Lloydminster": (53.28, -110.01),
    "Nanton": (50.35, -113.77), "Ponoka": (52.68, -113.58),
    "Rimbey": (52.63, -114.24), "Sundre": (51.80, -114.64),
    "Taber": (49.79, -112.15), "Vulcan": (50.40, -113.25),
    "Wainwright": (52.84, -110.86), "Westlock": (54.15, -113.87),
    "Wetaskiwin": (52.97, -113.37), "Whitecourt": (54.14, -115.69),
}
# Pruning anchors hard drives the in-sample fit down but overfits: at 12
# anchors leave-one-out error is 9.5 km, at 18 it is 7.4 km. Tuned on
# leave-one-out, not on the in-sample residual.
MAX_ANCHOR_RESIDUAL_KM = 6.0
MIN_ANCHORS = 18

# A station's own marker glyph sits within the label's horizontal span,
# give or take this margin. Using the glyph rather than the start of the
# label text matters: label text begins west of the symbol, which put
# every station about 5 km too far west.
MARKER_SEARCH_MARGIN_PX = 40.0
MARKER_SEARCH_ROW_PX = 12.0

# An "X" marker within this page distance of a station label is taken to
# be that station's symbol. Beyond it, the glyph is the legend entry.
MULTI_DIRECTION_MAX_PX = 70.0

# Tokens that lead a label but belong to something else: ESRI glyph
# characters rendered as letters, and neighbouring map furniture.
NOISE_PREFIXES = {
    "X", "W", "G", "XW", "GG", "SALES", "APS", "APN", "APGP", "APWM",
    "APNI", "LDS", "REDL", "STN", "INT", "PEM", "NO",
}

ALBERTA_BOX = ((48.5, 60.5), (-121.5, -108.5))

# Compressor stations physically sit on the pipeline. The map-derived
# position carries a few km of georeferencing error, so each station is
# snapped onto the nearest NGTL pipeline when one is close enough. This
# uses a true physical constraint to absorb error rather than inventing
# a location - but a station further than this from any known NGTL pipe
# is left where it is and flagged, since snapping it would be a guess.
NGTL_PIPELINE_FILE = (
    PROJECT_ROOT / "processed" / "ngtl_operating_pipelines.geojson"
)
SNAP_MAX_KM = 25.0
WORKING_CRS = 3400          # NAD83 / Alberta 10-TM Forest, metres


def basis(x, y):
    return np.array([1, x, y, x * x, x * y, y * y], dtype=float)


def haversine_km(lat1, lon1, lat2, lon2):
    r = math.radians
    return 2 * 6371 * math.asin(math.sqrt(
        math.sin(r(lat2 - lat1) / 2) ** 2
        + math.cos(r(lat1)) * math.cos(r(lat2))
        * math.sin(r(lon2 - lon1) / 2) ** 2))


def clean_name(raw: str) -> str:
    """Recover the station name from a cluttered map label.

    The map is dense enough that neighbouring labels and marker glyphs
    land on the same text line. Station names are upper case, so the
    trailing run of upper-case tokens is the name; anything before a
    mixed-case word or a stray symbol belongs to something else.
    """
    text = raw.replace("’", "'")
    if re.search(r"\b[A-Z] [A-Z] [A-Z]\b", text):          # letter-spaced
        text = re.sub(r"(?<=\b[A-Z]) (?=[A-Z]\b)", "", text)

    tokens = text.split()
    kept: list[str] = []
    for token in reversed(tokens):
        if re.fullmatch(r"No\.\d+[A-Z]?", token) or re.fullmatch(
            r"[A-Z][A-Z0-9.'()&#/-]*", token
        ):
            kept.append(token)
        else:
            break

    tokens = list(reversed(kept))
    while len(tokens) > 1 and tokens[0] in NOISE_PREFIXES:
        tokens.pop(0)

    name = " ".join(tokens).strip()
    return re.sub(r"\s+", " ", name)


def fit_transform(anchor_px):
    keys = list(anchor_px)

    def solve(ks):
        m = np.array([basis(*anchor_px[k]) for k in ks])
        a, *_ = np.linalg.lstsq(m, np.array([ANCHORS[k][0] for k in ks]), rcond=None)
        b, *_ = np.linalg.lstsq(m, np.array([ANCHORS[k][1] for k in ks]), rcond=None)
        return a, b

    while True:
        a, b = solve(keys)
        res = {}
        for k in keys:
            v = basis(*anchor_px[k])
            res[k] = haversine_km(float(v @ a), float(v @ b), *ANCHORS[k])
        worst = max(res, key=res.get)
        if res[worst] <= MAX_ANCHOR_RESIDUAL_KM or len(keys) <= MIN_ANCHORS:
            rms = float(np.sqrt(np.mean(np.square(list(res.values())))))
            return a, b, keys, rms
        keys.remove(worst)


def main() -> None:
    if not SEGMENT_MAP.exists():
        raise SystemExit(f"Segment codes map not found: {SEGMENT_MAP}")

    with pdfplumber.open(SEGMENT_MAP) as pdf:
        page = pdf.pages[0]
        chars = page.chars
        words = page.extract_words(x_tolerance=1.2, y_tolerance=1.2)

    markers = [c for c in chars if c["fontname"].endswith("ESRIDefaultMarker")]
    multi = [c for c in markers if c["text"] == "X"]
    print(f"multi-direction 'X' glyphs on the map: {len(multi)}")

    anchor_px = {}
    for w in words:
        if w["text"] in ANCHORS and w["text"] not in anchor_px:
            anchor_px[w["text"]] = ((w["x0"] + w["x1"]) / 2,
                                    (w["top"] + w["bottom"]) / 2)
    a, b, kept, rms = fit_transform(anchor_px)
    print(f"georeference: {len(kept)} anchors, in-sample RMS {rms:.2f} km")

    # Each "X" belongs to exactly one station. Assign greedily by
    # distance so two neighbouring labels cannot both claim the same
    # glyph and end up stacked on identical coordinates.
    tokens_all = [w for w in words if w["text"].strip() == "CS"]
    pairs = []
    for m in multi:
        mx = (m["x0"] + m["x1"]) / 2
        my = (m["top"] + m["bottom"]) / 2
        for t in tokens_all:
            d = math.hypot(mx - t["x0"], my - (t["top"] + t["bottom"]) / 2)
            if d <= MULTI_DIRECTION_MAX_PX:
                pairs.append((d, id(m), id(t), mx, my))
    pairs.sort()
    claimed_marker, claimed_token, assigned = set(), set(), {}
    for d, mid, tid, mx, my in pairs:
        if mid in claimed_marker or tid in claimed_token:
            continue
        claimed_marker.add(mid)
        claimed_token.add(tid)
        assigned[tid] = (mx, my)

    features, unnamed = [], 0
    for token in tokens_all:
        cx = token["x0"]
        cy = (token["top"] + token["bottom"]) / 2

        line = [w for w in words
                if abs((w["top"] + w["bottom"]) / 2 - cy) < 5
                and w["x1"] <= cx + 1 and cx - w["x1"] < 260]
        line.sort(key=lambda w: w["x1"], reverse=True)

        parts, cursor = [], cx
        for w in line:
            if cursor - w["x1"] > 14:
                break
            parts.append(w)
            cursor = w["x0"]

        name = clean_name(" ".join(p["text"] for p in reversed(parts)))
        if not name:
            unnamed += 1
            continue

        is_multi = id(token) in assigned

        # Position from the station's own marker glyph where one can be
        # found on the same row within the label's span; the label's
        # left edge is only a fallback.
        candidates = [
            m for m in markers
            if abs(((m["top"] + m["bottom"]) / 2) - cy) < MARKER_SEARCH_ROW_PX
            and (cursor - MARKER_SEARCH_MARGIN_PX)
            <= ((m["x0"] + m["x1"]) / 2)
            <= (cx + MARKER_SEARCH_MARGIN_PX)
        ]
        if candidates:
            glyph = min(
                candidates,
                key=lambda m: abs(((m["x0"] + m["x1"]) / 2) - cursor),
            )
            px = (glyph["x0"] + glyph["x1"]) / 2
            py = (glyph["top"] + glyph["bottom"]) / 2
            source = "marker"
        else:
            px, py, source = cursor, cy, "label"

        v = basis(px, py)
        lat, lon = float(v @ a), float(v @ b)
        if not (ALBERTA_BOX[0][0] <= lat <= ALBERTA_BOX[0][1]
                and ALBERTA_BOX[1][0] <= lon <= ALBERTA_BOX[1][1]):
            continue

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "name": name,
                # Spaces stripped so letter-spaced map labels
                # ("SWARTZCREEK") still match tracker names
                # ("Swartz Creek A2" -> "SWARTZCREEK").
                "match_key": re.sub(r"[^A-Z]", "", name.upper()),
                "multi_direction": is_multi,
                "position_from": source,
            },
        })

    # --- snap onto the pipeline network -----------------------------
    snapped = 0
    if NGTL_PIPELINE_FILE.exists() and features:
        pipes = gpd.read_file(NGTL_PIPELINE_FILE).to_crs(WORKING_CRS)
        union = pipes.geometry.union_all()

        pts = gpd.GeoSeries(
            [Point(f["geometry"]["coordinates"]) for f in features],
            crs="EPSG:4326",
        ).to_crs(WORKING_CRS)

        # nearest_points, not project/interpolate: round-tripping a
        # distance-along-geometry through a large MultiLineString does
        # not reliably return the nearest point.
        moved = gpd.GeoSeries(
            [nearest_points(union, p)[0] for p in pts],
            crs=WORKING_CRS,
        )
        distances = [p.distance(m) / 1000 for p, m in zip(pts, moved)]
        moved_ll = moved.to_crs("EPSG:4326")

        for feature, dist, point in zip(features, distances, moved_ll):
            feature["properties"]["snap_km"] = round(float(dist), 2)
            if dist <= SNAP_MAX_KM:
                feature["geometry"]["coordinates"] = [point.x, point.y]
                feature["properties"]["snapped"] = True
                snapped += 1
            else:
                feature["properties"]["snapped"] = False
        print(f"  snapped {snapped}/{len(features)} stations onto the "
              f"NGTL network (within {SNAP_MAX_KM:.0f} km)")
    else:
        for feature in features:
            feature["properties"]["snapped"] = False
            feature["properties"]["snap_km"] = None

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )
    n_multi = sum(f["properties"]["multi_direction"] for f in features)
    print(f"\nwrote {len(features)} stations -> {OUTPUT.name}")
    print(f"  multi-direction: {n_multi}   single: {len(features)-n_multi}")
    if unnamed:
        print(f"  {unnamed} labels dropped (name unrecoverable from clutter)")


if __name__ == "__main__":
    main()
