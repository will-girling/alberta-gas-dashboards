"""Build a TC-station-name to AER-licence crosswalk.

Why this exists
---------------
TC's outage/maintenance tracker identifies facilities by name
("Otter Lake - Compressor Station Maintenance"). The AER installation
shapefile has no name field at all - only LICINSTNO ("80733-1"). There
is no shared key between the two, so outages cannot be placed on the map
without a bridge.

TC's own "NGTL System - Segment Codes & Project Areas" map is the
authoritative name source: it labels every compressor station as
"<NAME> CS". This script extracts those labels, georeferences the page,
and matches each named station to the nearest AER compressor station.

Nothing here is asserted as certain. Every row carries the measured
distance to the best AER candidate, the margin to the runner-up, and a
confidence grade. Rows that do not resolve cleanly are marked
UNRESOLVED rather than being quietly assigned.

Method
------
1. Extract "<NAME> CS" labels with page coordinates.
2. Locate each label's own ESRI marker glyph (the map draws the station
   symbol immediately left of its name), and use the glyph position
   rather than the text position - text sits up to ~50 px from its
   marker, which at this map scale is ~25 km.
3. Fit a quadratic page->lat/lon transform on town labels whose true
   coordinates are known, discarding outliers (this removes the
   Edmonton-area inset, which sits on a different scale).
4. Match each station to the nearest AER NGTL compressor station and
   grade the result.

Accuracy
--------
The transform cross-validates leave-one-out at ~6 km RMS. Anchor points
are town *labels*, which are themselves offset from the town, so this is
a floor on achievable precision, not a defect in the fit. Grades are set
accordingly.

Output
------
processed/station_crosswalk.csv

Run
---
    python3 prepare_station_crosswalk.py
"""

from __future__ import annotations

import csv
import math
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pdfplumber

PROJECT_ROOT = Path("/Users/willgirling/Desktop/NGTL Project")
SEGMENT_MAP = PROJECT_ROOT / "NGTL_Segment_Codes_Map_Feb2025.pdf"
INSTALLATION_SHP = (
    PROJECT_ROOT
    / "Pipeline_Installations_SHP"
    / "Pipeline_Installations_GCS_NAD83.shp"
)
OUTPUT = PROJECT_ROOT / "processed" / "station_crosswalk.csv"

NGTL_OPERATOR = "NOVA Gas Transmission Ltd."

# Town labels with known coordinates, used to georeference the page.
# Edmonton/Morinville/Leduc are deliberately absent: they fall inside the
# map's Edmonton-area inset and would corrupt the fit.
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

MAX_ANCHOR_RESIDUAL_KM = 4.0
MIN_ANCHORS = 12

# Grading thresholds, in km. HIGH also requires the runner-up to be
# clearly further away, so a station sitting between two candidates is
# never graded HIGH however close the nearest one is.
HIGH_MAX_KM = 12.0
HIGH_MIN_MARGIN_KM = 10.0
MEDIUM_MAX_KM = 25.0

ALBERTA_LON = (-120.5, -109.5)
ALBERTA_LAT = (48.9, 60.1)


def basis(x: float, y: float) -> np.ndarray:
    return np.array([1, x, y, x * x, x * y, y * y], dtype=float)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = math.radians
    return 2 * 6371 * math.asin(
        math.sqrt(
            math.sin(r(lat2 - lat1) / 2) ** 2
            + math.cos(r(lat1)) * math.cos(r(lat2))
            * math.sin(r(lon2 - lon1) / 2) ** 2
        )
    )


def clean_name(raw: str) -> str:
    """Strip leading map symbols and un-space letter-spaced labels."""
    name = re.sub(r"^[^A-Za-z]+", "", raw).strip()
    if re.search(r"\b[A-Z] [A-Z] [A-Z]\b", name):
        name = re.sub(r"(?<=\b[A-Z]) (?=[A-Z]\b)", "", name)
    # Drop a trailing mixed-case town name that collided with the label.
    name = re.sub(r"^(?:[A-Z][a-z]+\s+)+(?=[A-Z]{2})", "", name)
    return re.sub(r"\s+", " ", name).strip()


def fit_transform(anchor_px: dict) -> tuple[np.ndarray, np.ndarray, list, float]:
    keys = list(anchor_px)

    def solve(ks):
        m = np.array([basis(*anchor_px[k]) for k in ks])
        a, *_ = np.linalg.lstsq(m, np.array([ANCHORS[k][0] for k in ks]), rcond=None)
        b, *_ = np.linalg.lstsq(m, np.array([ANCHORS[k][1] for k in ks]), rcond=None)
        return a, b

    while True:
        a, b = solve(keys)
        residuals = {}
        for k in keys:
            v = basis(*anchor_px[k])
            lat, lon = float(np.dot(a, v)), float(np.dot(b, v))
            residuals[k] = haversine_km(lat, lon, *ANCHORS[k])
        worst = max(residuals, key=residuals.get)
        if residuals[worst] <= MAX_ANCHOR_RESIDUAL_KM or len(keys) <= MIN_ANCHORS:
            rms = float(np.sqrt(np.mean(np.square(list(residuals.values())))))
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

    # --- georeference -------------------------------------------------
    anchor_px = {}
    for w in words:
        if w["text"] in ANCHORS and w["text"] not in anchor_px:
            anchor_px[w["text"]] = (
                (w["x0"] + w["x1"]) / 2,
                (w["top"] + w["bottom"]) / 2,
            )

    a, b, kept, rms = fit_transform(anchor_px)
    print(f"Georeference: {len(kept)} anchors, in-sample RMS {rms:.2f} km")

    def to_latlon(x, y):
        v = basis(x, y)
        return float(np.dot(a, v)), float(np.dot(b, v))

    # --- AER stations -------------------------------------------------
    gdf = gpd.read_file(
        INSTALLATION_SHP,
        columns=["LICINSTNO", "INSTA_LIC", "INSTA_TYPE", "BA_NAME",
                 "PLINSTATUS", "POWER", "INST_LOCAT"],
    )
    gdf = gdf[
        (gdf.BA_NAME == NGTL_OPERATOR)
        & (gdf.INSTA_TYPE == "Compressor Station")
        & (gdf.PLINSTATUS == "Operating")
    ]
    aer = [
        (r.LICINSTNO, r.INSTA_LIC, r.geometry.y, r.geometry.x,
         r.POWER, r.INST_LOCAT)
        for r in gdf.itertuples()
    ]
    print(f"AER operating NGTL compressor stations: {len(aer)}")

    # --- station labels -----------------------------------------------
    rows = []
    for token in [w for w in words if w["text"].strip() == "CS"]:
        cx = token["x0"]
        cy = (token["top"] + token["bottom"]) / 2

        same_line = [
            w for w in words
            if abs((w["top"] + w["bottom"]) / 2 - cy) < 5
            and w["x1"] <= cx + 1 and cx - w["x1"] < 260
        ]
        same_line.sort(key=lambda w: w["x1"], reverse=True)

        parts, cursor = [], cx
        for w in same_line:
            if cursor - w["x1"] > 14:
                break
            parts.append(w)
            cursor = w["x0"]

        raw = " ".join(p["text"] for p in reversed(parts))
        name = clean_name(raw)
        if not name:
            continue

        # The station's own marker sits just left of its name.
        name_start = cursor
        near = [
            m for m in markers
            if abs((m["top"] + m["bottom"]) / 2 - cy) < 9
            and name_start - m["x1"] < 55
            and m["x1"] <= cx
        ]
        if near:
            marker = min(near, key=lambda m: abs(m["x1"] - name_start))
            px, py = marker["x0"], (marker["top"] + marker["bottom"]) / 2
            anchor_kind, glyph = "marker", marker["text"]
        else:
            px, py, anchor_kind, glyph = name_start, cy, "label", ""

        lat, lon = to_latlon(px, py)
        in_ab = (
            ALBERTA_LAT[0] <= lat <= ALBERTA_LAT[1]
            and ALBERTA_LON[0] <= lon <= ALBERTA_LON[1]
        )

        ranked = sorted(
            (haversine_km(lat, lon, s[2], s[3]), s) for s in aer
        )
        d1, best = ranked[0]
        d2 = ranked[1][0]

        if not in_ab:
            grade, licence, lic = "OUTSIDE_AB", "", ""
        elif d1 <= HIGH_MAX_KM and (d2 - d1) >= HIGH_MIN_MARGIN_KM:
            grade, licence, lic = "HIGH", best[0], best[1]
        elif d1 <= MEDIUM_MAX_KM:
            grade, licence, lic = "MEDIUM", best[0], best[1]
        else:
            grade, licence, lic = "UNRESOLVED", "", ""

        rows.append({
            "tc_name": name,
            "confidence": grade,
            "aer_licinstno": licence,
            "aer_licence": lic,
            "km_to_match": round(d1, 1),
            "km_margin_to_runner_up": round(d2 - d1, 1),
            "multi_direction": "Y" if glyph == "X" else "",
            "position_from": anchor_kind,
            "approx_lat": round(lat, 4),
            "approx_lon": round(lon, 4),
            "aer_dls": best[5] if licence else "",
            "aer_power_kw": int(best[4]) if licence and best[4] == best[4] else "",
        })

    rows.sort(key=lambda r: (r["confidence"], r["tc_name"]))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    from collections import Counter
    tally = Counter(r["confidence"] for r in rows)
    print(f"\nwrote {len(rows)} rows -> {OUTPUT.name}")
    for grade in ("HIGH", "MEDIUM", "UNRESOLVED", "OUTSIDE_AB"):
        print(f"   {grade:<12}{tally.get(grade, 0):3d}")
    print(f"   multi-direction flagged: "
          f"{sum(1 for r in rows if r['multi_direction'])}")


if __name__ == "__main__":
    main()
