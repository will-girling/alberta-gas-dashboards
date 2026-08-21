from __future__ import annotations

import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import requests
import streamlit as st


# ============================================================
# CONFIG
# ============================================================

# Resolve relative to this file so the app runs anywhere -
# a laptop, a container, or Streamlit Community Cloud.
PROJECT_ROOT = Path(__file__).resolve().parent
CSR_FILE = PROJECT_ROOT / "CSR_Master.csv"

ASSET_DIR = PROJECT_ROOT / "assets"
ALBERTA_GEOJSON_FILE = ASSET_DIR / "alberta_boundary.geojson"

# Map layers are read from processed/map/ when it exists: same features
# and same properties, but coordinates rounded to ~1 m and vertices below
# a pixel removed, which is about a quarter of the payload deck.gl has to
# be handed on every rerun. Built by slim_map_layers.py. If a slim copy
# is missing the full file is used, so the dashboard works either way.
SLIM_DIR = PROJECT_ROOT / "processed" / "map"


def map_layer(name: str) -> Path:
    slim = SLIM_DIR / name
    return slim if slim.exists() else PROJECT_ROOT / "processed" / name


NGTL_PIPELINE_FILE = map_layer("ngtl_operating_pipelines.geojson")

# Built by prepare_installation_layers.py from the AER installation
# shapefile. Re-run that script if the AER source is refreshed.
# TC's own named compressor stations, from prepare_tc_stations.py.
# Used in preference to the AER layer because only TC publishes station
# names (needed to match outage notices) and the multi-direction flag.
# The AER layer (ngtl_compressor_stations.geojson, with installed power
# and licence numbers but no names) is still built by
# prepare_installation_layers.py if it is wanted for reference.
NGTL_COMPRESSOR_FILE = map_layer("tc_compressor_stations.geojson")
NGTL_METER_FILE = map_layer("ngtl_meter_stations.geojson")

# BC transmission pipelines from the BC Energy Regulator, built by
# prepare_bc_pipelines.py. Gives the western interconnects something to
# connect to instead of stopping dead at the provincial boundary.
# Deliberately drawn dimmer than the NGTL network: it is post-2016
# permits only, so it is real but incomplete (Westcoast T-South is
# largely missing, being CER-regulated and not openly published).
BC_PIPELINE_FILE = map_layer("bc_transmission_pipelines.geojson")
BC_PIPE_KEY = [96, 186, 232, 215]      # operators that connect to NGTL
BC_PIPE_OTHER = [96, 186, 232, 120]    # everything else, quieter
BC_PIPE_WIDTH_PX = 2.6

# deck.gl picks on the rendered geometry, so a thin line is a thin hover
# target. An invisible wider line underneath widens the catch area
# without thickening what you see. Alpha 0 still registers for picking.
BC_PIPE_HIT_WIDTH_PX = 11.0

# Built by prepare_outages.py from TC maintenance tracker exports.
OUTAGE_FILE = PROJECT_ROOT / "processed" / "ngtl_outages.csv"

# TC's own capacity-area polygons, from prepare_outage_areas.py. These
# are the areas drawn on TC's outage bulletin, so the dashboard shades
# the same geography they publish rather than an approximation.
OUTAGE_AREA_FILE = map_layer("ngtl_outage_areas.geojson")

# Built by prepare_outage_changes.py: what moved between the two most
# recent tracker publications. A published schedule is largely priced
# in; the change since last publication is the part that is not.
OUTAGE_CHANGES_FILE = (
    PROJECT_ROOT / "processed" / "ngtl_outage_changes.csv"
)

# Colours for change direction: worse, better, neutral-but-notable.
CHANGE_TONE = {
    "new": "#ff9e2c", "deepened": "#eb4034", "extended": "#eb4034",
    "reclassified": "#ff9e2c", "removed": "#40bf76", "eased": "#40bf76",
    "shortened": "#40bf76", "rescheduled": "#9ac9a5",
}

# Capacity tables that have a measurable CSR counterpart, so stated
# capability can be compared against what is actually flowing. Tables
# without one (delivery areas, individual receipt/delivery points) still
# appear in the outage list, just without a utilisation figure.
# "exact" means the CSR columns measure the same flow the capability
# refers to. "partial" means CSR covers only part of it (WGAT also
# includes the Alberta/Montana border, which CSR does not report) or
# more than it (Total Receipts includes receipts downstream of James
# River). Partial tables therefore show headroom but no utilisation
# percentage, since a figure over 100% would read as a breach when it
# is really just a mismatched denominator.
OUTAGE_TABLE_TO_CSR = {
    "EGAT": (["Empress Border Flow", "Mcneil Border Flow"], "exact"),
    "WGAT": (["Alberta-BC Border Flow"], "partial"),
    "FHZ8": (["Alberta-BC Border Flow"], "partial"),
    "USJR": (["Total Receipts"], "partial"),
}

# Which interconnect markers a capacity table constrains. Only gates
# whose geography is unambiguous are included: EGAT is the Empress and
# McNeill border pair, WGAT and FHZ8 both bear on the Alberta-BC border.
# The delivery areas (OSDA, NEDA) and local points are deliberately
# absent - they have no single marker to attach to.
OUTAGE_TABLE_TO_INTERCONNECT = {
    "EGAT": ["Empress", "McNeill"],
    "WGAT": ["Alberta–BC"],
    "FHZ8": ["Alberta–BC"],
}

# Outage ring colours, graded by how far the capacity table is derated
# below its own normal. Warm tones were reserved for exactly this while
# the deviation bands took the red/green range, so an outage ring reads
# as a separate signal from the flow-vs-baseline fill it surrounds.
OUTAGE_SEVERITY = {
    "severe":   {"colour": [235, 64, 52, 245],   "hex": "#eb4034",
                 "label": "Severe", "detail": "10%+ below normal capability"},
    "moderate": {"colour": [255, 158, 44, 240],  "hex": "#ff9e2c",
                 "label": "Moderate", "detail": "4-10% below"},
    "minor":    {"colour": [222, 205, 128, 220], "hex": "#decd80",
                 "label": "Minor", "detail": "under 4% below"},
    "unknown":  {"colour": [150, 158, 172, 200], "hex": "#969eac",
                 "label": "Severity unknown", "detail": ""},
}
SEVERITY_RANK = {"unknown": 0, "minor": 1, "moderate": 2, "severe": 3}

# Restriction wording that indicates firm service may be affected.
OUTAGE_IMPACT_MARKER = "potential"

# Two separate deviation baselines are in use.
#
# Interconnect markers are banded against the trailing 30 gas days of
# GDSR history, which is the only source long enough for a 30-day
# window. The six border/interconnect points agree closely between the
# two feeds (within 1.5% on levels), so the cross-source comparison
# holds up there.
GDSR_FLOWS_FILE = PROJECT_ROOT / "processed" / "ngtl_daily_flows.csv"
MARKER_BASELINE_WINDOW_DAYS = 30
MARKER_BASELINE_MIN_DAYS = 10

# The Alberta-wide panel is banded against CSR's own trailing history
# instead. Several Alberta metrics are not defined identically across
# the two feeds (CSR "Intraprovincial Demand" runs ~10%, roughly 4.5
# std dev, below GDSR INTRAPROVINCIAL), so a GDSR baseline would report
# a definitional offset as an operational deviation. Keeping both sides
# on CSR also means the spread already includes normal within-day
# movement.
#
# Raise this as the archive grows. Note the window is a request, not a
# guarantee: csr_baseline takes whatever observations fall inside it, so
# if the archive is shorter than the window the baseline is quietly built
# on less. The bubble reports its observation count, and
# baseline_coverage_days below surfaces the shortfall explicitly rather
# than letting a label claim more history than exists.
ALBERTA_BASELINE_WINDOW_DAYS = 14

# Half-hourly data gives ~48 observations/day; require a full day before
# reporting a band.
BASELINE_MIN_OBSERVATIONS = 48

ALBERTA_BOUNDARY_URL = (
    "https://geospatial.alberta.ca/titan/rest/services/"
    "boundary/goa_administrative_area/MapServer/0/query"
)

EXPECTED_COLUMNS = [
    "Timestamp",
    "NGTL-Field Receipts",
    "Groundbirch East Receipt",
    "Gordondale Receipt",
    "Total Receipts",
    "Intraprovincial Demand",
    "Empress Border Flow",
    "Mcneil Border Flow",
    "Alberta-BC Border Flow",
    "Willow Valley Interconnect",
    "Total Deliveries",
    "Current Linepack",
    "Linepack 4Hr Roc",
    "Net Storage Flow",
    "Flow Differential",
    "Linepack Target",
]

FLOW_COLUMNS = [
    "NGTL-Field Receipts",
    "Groundbirch East Receipt",
    "Gordondale Receipt",
    "Total Receipts",
    "Intraprovincial Demand",
    "Empress Border Flow",
    "Mcneil Border Flow",
    "Alberta-BC Border Flow",
    "Willow Valley Interconnect",
    "Total Deliveries",
    "Net Storage Flow",
    "Flow Differential",
]

LINEPACK_COLUMNS = [
    "Current Linepack",
    "Linepack 4Hr Roc",
    "Linepack Target",
]

INTERCONNECTS = [
    {
        "key": "Gordondale",
        "display_name": "Gordondale Receipt",
        "column": "Gordondale Receipt",
        "gdsr_item": "GORDONDALE",
        "lat": 55.80,
        "lon": -119.98,
        "label_side": "below",
        "direction": "Receipt into NGTL",
        "bearing_out": 270,
    },
    {
        "key": "Groundbirch East",
        "display_name": "Groundbirch East",
        "column": "Groundbirch East Receipt",
        "gdsr_item": "GROUNDBIRCH_EAST",
        "lat": 55.78,
        "lon": -120.62,
        "label_side": "above",
        "direction": "Receipt into NGTL",
        "bearing_out": 270,
    },
    {
        "key": "Willow Valley",
        "display_name": "Willow Valley",
        "column": "Willow Valley Interconnect",
        "gdsr_item": "WILLOW_VALLEY",
        "lat": 55.66,
        "lon": -120.55,
        "label_side": "below",
        "direction": "Interconnect flow",
        "bearing_out": 270,
    },
    {
        "key": "Alberta–BC",
        "display_name": "Alberta–BC Border",
        "column": "Alberta-BC Border Flow",
        "gdsr_item": "ALBERTA_BC",
        "lat": 49.63,
        "lon": -114.69,
        "label_side": "above",
        "direction": "Border flow",
        "bearing_out": 250,
    },
    {
        "key": "Empress",
        "display_name": "Empress Border",
        "column": "Empress Border Flow",
        "gdsr_item": "EMPRESS",
        "lat": 50.95,
        "lon": -110.01,
        "label_side": "above",
        "direction": "Border flow",
        "bearing_out": 90,
    },
    {
        "key": "McNeill",
        "display_name": "McNeill Border",
        "column": "Mcneil Border Flow",
        "gdsr_item": "MCNEILL",
        "lat": 50.66,
        "lon": -110.02,
        "label_side": "below",
        "direction": "Border flow",
        "bearing_out": 90,
    },
]

WHITE = [248, 248, 252, 255]
PIPELINE_BLUE = [77, 163, 255, 170]

# Compressor stations use the purple that the interconnect markers gave
# up when they moved to deviation colouring. Warm colours (orange/red)
# are deliberately left unused here so they remain available for the
# planned maintenance/outage overlay.
COMPRESSOR_PURPLE = [163, 122, 255, 235]
METER_SLATE = [120, 148, 176, 150]

# All compressor stations are drawn at the same size. Installed power
# is still available in the tooltip, but it is deliberately not encoded
# in the marker: size and colour are both left free so the maintenance
# overlay has room to work with.
COMPRESSOR_GLYPH = "\u25b2"          # single-direction
COMPRESSOR_MULTI_GLYPH = "\u25c6"    # multi-direction (can reverse)
COMPRESSOR_GLYPH_SIZE_PX = 60.0
METER_RADIUS_PX = 2.6

# Interconnect markers are a fixed size; colour alone carries the
# deviation signal. Bands are z-scores against that point's own
# trailing GDSR baseline, so each interconnect is judged against its
# own normal volatility rather than a shared absolute threshold.
MARKER_RADIUS_PIXELS = 18

# Flow-direction arrow sitting on each interconnect marker.
#
# The arrow is rotated to the compass bearing gas is actually travelling,
# rather than using an up/down glyph for in/out: "into the system" means
# eastbound at Empress and westbound at Gordondale, and an abstract
# up-arrow at both would say less than the map already shows. The
# triangle glyphs are spoken for by compressor stations, so an
# unambiguous arrow is used here.
#
# bearing_out on each interconnect is the direction gas leaves Alberta -
# east into Saskatchewan at Empress/McNeill, west into BC at the others.
# It is the side of the system the point sits on, which is a fact about
# geography, not a surveyed pipe heading. When flow reverses (positive,
# into NGTL) the arrow is turned 180 degrees.
# U+2794, a heavy wide-headed arrow: shaft plus head, so it reads as an
# arrow rather than as another triangle competing with the compressor
# glyphs. Deliberately not U+27A1, which many systems render as a colour
# emoji - a colour font ignores get_color and would also fight the
# deviation banding.
FLOW_ARROW_GLYPH = "➔"
# Sized against the dot, which is MARKER_RADIUS_PIXELS * 2 = 36 px
# across. A glyph only fills part of its em box - roughly 60% here - so
# a font size matching the dot diameter draws noticeably smaller than
# the dot. At this multiple the arrow overhangs the marker, which is
# wanted: the shaft sticking out the side gas is heading is what makes
# the direction legible at a glance.
FLOW_ARROW_SIZE_PX = MARKER_RADIUS_PIXELS * 4.6      # ~83 px
FLOW_ARROW_COLOUR = [252, 252, 255, 255]

DEVIATION_BANDS = [
    {
        "key": "deep_below",
        "label": "Well below normal",
        "detail": "2+ std dev below",
        "colour": [219, 46, 51, 245],
        "hex": "#db2e33",
    },
    {
        "key": "below",
        "label": "Below normal",
        "detail": "1–2 std dev below",
        "colour": [235, 122, 106, 240],
        "hex": "#eb7a6a",
    },
    {
        "key": "normal",
        "label": "Normal",
        "detail": "within 1 std dev",
        "colour": [154, 201, 165, 235],
        "hex": "#9ac9a5",
    },
    {
        "key": "above",
        "label": "Above normal",
        "detail": "1–2 std dev above",
        "colour": [64, 191, 118, 240],
        "hex": "#40bf76",
    },
    {
        "key": "deep_above",
        "label": "Well above normal",
        "detail": "2+ std dev above",
        "colour": [16, 216, 132, 245],
        "hex": "#10d884",
    },
]

BAND_BY_KEY = {band["key"]: band for band in DEVIATION_BANDS}

NO_BASELINE_BAND = {
    "key": "no_baseline",
    "label": "No baseline yet",
    "detail": "insufficient history",
    "colour": [130, 140, 155, 210],
    "hex": "#828c9b",
}


st.set_page_config(
    page_title="NGTL Current System Report",
    page_icon="◼",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# STYLE
# ============================================================

st.markdown(
    """
    <style>
        .block-container {
            max-width: 1700px;
            padding-top: 1.0rem;
            padding-bottom: 2rem;
        }

        .title {
            font-size: 2rem;
            font-weight: 760;
            letter-spacing: -0.03em;
            margin-bottom: 0.05rem;
        }

        .subtitle {
            color: #9da7b4;
            margin-bottom: 0.55rem;
        }

        .section-label {
            font-size: 1rem;
            font-weight: 700;
            margin-bottom: 0.4rem;
        }

        .timestamp-chip {
            display: inline-block;
            border: 1px solid rgba(255,255,255,0.12);
            background: rgba(25,31,41,0.96);
            border-radius: 8px;
            padding: 0.35rem 0.6rem;
            color: #c7d0dc;
            font-size: 0.82rem;
            margin-bottom: 0.4rem;
        }

        .small-note {
            color: #98a2af;
            font-size: 0.76rem;
        }

        /* Flow arrow beside the selected point's name. inline-block is
           required for transform to apply at all - it is ignored on a
           pure inline element. */
        .header-arrow {
            display: inline-block;
            margin-left: 0.45rem;
            font-size: 1.15em;
            line-height: 1;
            vertical-align: -0.08em;
            color: #dfe6ef;
        }

        .legend-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem 1.1rem;
            align-items: center;
            margin: 0.5rem 0 0.15rem 0;
        }

        /* Column form, used beside the map. One entry per line, with
           the swatches left-aligned so they scan vertically. */
        .legend-stack {
            display: flex;
            flex-direction: column;
            gap: 0.55rem;
            align-items: flex-start;
            margin: 0.2rem 0 0.15rem 0;
        }

        /* In the stack an entry may wrap onto two lines, so the swatch
           aligns to the first line rather than centring on the block,
           and the detail text sits under the label instead of after it. */
        /* The swatch, label and detail are siblings of one flex item,
           so the detail is pushed onto its own line with a full-width
           basis rather than display:block - a flex child is blockified
           and would otherwise stay on the same row. */
        .legend-stack .legend-item {
            align-items: flex-start;
            white-space: normal;
            line-height: 1.25;
            flex-wrap: wrap;
        }

        .legend-stack .legend-dot,
        .legend-stack .legend-area,
        .legend-stack .legend-diamond,
        .legend-stack .legend-ring,
        .legend-stack .legend-triangle {
            margin-top: 2px;
        }

        /* Indent to clear the swatch (11px + 0.4rem margin) so the
           detail lines up under the label above it. */
        .legend-stack .legend-detail {
            flex-basis: 100%;
            margin-left: 0;
            padding-left: calc(11px + 0.4rem);
        }

        .legend-item {
            display: inline-flex;
            align-items: center;
            color: #c7d0dc;
            font-size: 0.78rem;
            white-space: nowrap;
        }

        .legend-dot {
            width: 11px;
            height: 11px;
            border-radius: 50%;
            border: 1px solid rgba(248,248,252,0.85);
            margin-right: 0.4rem;
            flex: none;
        }

        .legend-area {
            width: 13px;
            height: 10px;
            border: 1.5px solid rgba(255,158,44,0.9);
            background: rgba(255,158,44,0.25);
            border-radius: 2px;
            margin-right: 0.4rem;
            flex: none;
        }

        .legend-diamond {
            width: 9px;
            height: 9px;
            transform: rotate(45deg);
            margin-right: 0.45rem;
            flex: none;
        }

        .legend-ring {
            width: 11px;
            height: 11px;
            border-radius: 50%;
            border: 2.5px solid currentColor;
            background: transparent;
            margin-right: 0.4rem;
            flex: none;
        }

        .legend-triangle {
            width: 0;
            height: 0;
            border-left: 6px solid transparent;
            border-right: 6px solid transparent;
            border-bottom: 11px solid currentColor;
            margin-right: 0.4rem;
            flex: none;
        }

        .legend-detail {
            color: #8a94a3;
            font-size: 0.72rem;
            margin-left: 0.32rem;
        }

        /* Deviation pill beneath a metric, sized to sit directly under
           Streamlit's native delta ("+0.11 vs prior obs.") as a second
           bubble on the same visual footing. */
        .metric-band {
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            border-radius: 0.5rem;
            padding: 0.06rem 0.5rem;
            font-size: 0.875rem;
            line-height: 1.6;
            font-weight: 600;
            margin: -0.35rem 0 0.3rem 0;
            white-space: nowrap;
        }

        .metric-band .band-sd {
            font-weight: 500;
            opacity: 0.82;
        }

        div[data-testid="stMetric"] {
            border-bottom: 1px solid rgba(255,255,255,0.07);
            padding-bottom: 0.45rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# DATA LOADERS
# ============================================================

@st.cache_data(show_spinner=False)
def load_csr_data(path: str, mtime_ns: int) -> pd.DataFrame:
    del mtime_ns  # cache invalidation only

    df = pd.read_csv(path)
    df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]

    missing = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            "CSR_Master.csv is missing expected columns: "
            + ", ".join(missing)
        )

    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df = df.dropna(subset=["Timestamp"]).copy()

    for col in EXPECTED_COLUMNS[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = (
        df.drop_duplicates(subset=["Timestamp"], keep="last")
        .sort_values("Timestamp")
        .reset_index(drop=True)
    )

    return df


@st.cache_data(show_spinner=False)
def load_pipeline_geojson(path: str, mtime_ns: int) -> dict | None:
    del mtime_ns

    pipeline_path = Path(path)
    if not pipeline_path.exists():
        return None

    with pipeline_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not data.get("features"):
        return None

    for feature in data.get("features", []):
        props = feature.setdefault("properties", {})
        company = props.get("COMP_NAME") or "NOVA Gas Transmission Ltd."

        props["tooltip_title"] = company
        props["tooltip_line1"] = (
            f"Licence {props.get('LICENCE_NO', '—')} · "
            f"Line {props.get('LINE_NO', '—')}"
        )
        props["tooltip_line2"] = (
            f"Diameter: {props.get('OUT_DIAMET', '—')} mm"
        )
        props["tooltip_line3"] = (
            f"Substance: {props.get('SUBSTANCE1', '—')}"
        )
        props["tooltip_line4"] = (
            f"Status: {props.get('SEG_STATUS', '—')}"
        )
        props["tooltip_line5"] = (
            f"Length: {props.get('SEG_LENGTH', '—')} km"
        )
        props["tooltip_line6"] = (
            f"Segment ID: {props.get('PLLICSEGID', '—')}"
        )

    return data


@st.cache_data(show_spinner=False)
def load_outages(path: str, mtime_ns: int) -> pd.DataFrame | None:
    """Load normalised maintenance outages (one row per outage-day)."""
    del mtime_ns

    outage_path = Path(path)
    if not outage_path.exists():
        return None

    df = pd.read_csv(outage_path)
    if "gas_day" not in df.columns:
        return None

    df["gas_day"] = pd.to_datetime(df["gas_day"], errors="coerce")
    df["capability_mmcfd"] = pd.to_numeric(
        df.get("capability_mmcfd"), errors="coerce"
    )

    return df.dropna(subset=["gas_day"])


@st.cache_data(show_spinner=False)
def load_installation_points(path: str, mtime_ns: int) -> pd.DataFrame | None:
    """Flatten a point-GeoJSON installation layer into a DataFrame.

    ScatterplotLayer wants columns rather than GeoJSON features, and
    working with a DataFrame keeps radius scaling and tooltip text in
    ordinary pandas rather than deck.gl accessor expressions.
    """
    del mtime_ns

    layer_path = Path(path)
    if not layer_path.exists():
        return None

    with layer_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for feature in data.get("features", []):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            continue

        lon, lat = geometry.get("coordinates", [None, None])[:2]
        if lon is None or lat is None:
            continue

        rows.append({**(feature.get("properties") or {}), "lon": lon, "lat": lat})

    if not rows:
        return None

    df = pd.DataFrame(rows)
    df["POWER"] = pd.to_numeric(df.get("POWER"), errors="coerce")

    return df


@st.cache_data(show_spinner=False)
def load_gdsr_flows(path: str, mtime_ns: int) -> pd.DataFrame | None:
    """Load the GDSR daily flow history used for interconnect baselines.

    CSR retains only ~7 days, so the 30-day marker baseline has to come
    from the daily GDSR archive. Returns None if unavailable, so the map
    degrades to neutral markers rather than failing.
    """
    del mtime_ns

    flows_path = Path(path)
    if not flows_path.exists():
        return None

    df = pd.read_csv(flows_path)
    df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]

    required = {"GasDay", "Item", "ExtrapolatedMMcfd"}
    if not required.issubset(df.columns):
        return None

    df["GasDay"] = pd.to_datetime(df["GasDay"], errors="coerce")
    df["ExtrapolatedMMcfd"] = pd.to_numeric(
        df["ExtrapolatedMMcfd"],
        errors="coerce",
    )
    df = df.dropna(subset=["GasDay", "Item"])

    return df[["GasDay", "Item", "ExtrapolatedMMcfd"]].copy()


def gdsr_baseline(
    flows: pd.DataFrame | None,
    item: str,
    as_of: pd.Timestamp,
) -> dict[str, float]:
    """Trailing 30-gas-day mean and std of absolute flow for one item.

    Magnitude is used because the GDSR archive preserves the TC Energy
    sign convention (negative = out of NGTL) while CSR reports these
    points unsigned; comparing magnitudes keeps the two on the same
    footing.
    """
    empty = {"mean": math.nan, "std": math.nan, "count": 0, "signed": False}

    if flows is None:
        return empty

    subset = flows.loc[
        (flows["Item"] == item) & (flows["GasDay"] <= as_of.normalize())
    ].sort_values("GasDay")

    if subset.empty:
        return empty

    values = (
        subset.tail(MARKER_BASELINE_WINDOW_DAYS)["ExtrapolatedMMcfd"]
        .abs()
        .dropna()
    )

    if len(values) < MARKER_BASELINE_MIN_DAYS:
        return {**empty, "count": len(values)}

    return {
        "mean": float(values.mean()),
        "std": float(values.std(ddof=0)),
        "count": int(len(values)),
        "signed": False,
    }


def csr_baseline(
    frame: pd.DataFrame,
    column: str,
    timestamp: pd.Timestamp,
    days: int = ALBERTA_BASELINE_WINDOW_DAYS,
) -> dict[str, float]:
    """Trailing CSR baseline for one column, ending at ``timestamp``.

    Both the current reading and the baseline come from the same CSR
    feed, so no cross-source reconciliation is needed and the spread
    already reflects normal within-day movement.

    Magnitudes are used, consistent with the project convention that
    relative activity is judged on flow magnitude rather than sign, so
    stronger outbound flow is not treated as a decline. The exception is
    a series that genuinely changes sign inside the window (Flow
    Differential does): folding that around zero would distort the
    baseline, so signed values are used instead.
    """
    start = timestamp - pd.Timedelta(days=days)

    values = frame.loc[
        (frame["Timestamp"] > start) & (frame["Timestamp"] <= timestamp),
        column,
    ].dropna()

    if len(values) < BASELINE_MIN_OBSERVATIONS:
        return {
            "mean": math.nan,
            "std": math.nan,
            "count": len(values),
            "signed": False,
        }

    crosses_zero = bool(values.min() < 0 < values.max())
    prepared = values if crosses_zero else values.abs()

    # How much history the baseline actually rests on. The window asks
    # for `days`; the archive may hold less, and a bubble labelled "vs
    # 14d" that is really 10 days of data overstates its own footing.
    stamps = frame.loc[values.index, "Timestamp"]
    covered = (stamps.max() - stamps.min()).total_seconds() / 86400

    return {
        "mean": float(prepared.mean()),
        "std": float(prepared.std(ddof=0)),
        "count": int(len(prepared)),
        "signed": crosses_zero,
        "window_days": days,
        "covered_days": float(covered),
    }


def deviation_zscore(current: float, base: dict[str, float]) -> float:
    """Signed z-score of the current reading vs its trailing baseline."""
    if pd.isna(current) or pd.isna(base["mean"]) or pd.isna(base["std"]):
        return math.nan

    if base["std"] <= 0:
        return math.nan

    return (abs(current) - base["mean"]) / base["std"]


def classify_deviation(z: float) -> dict:
    if pd.isna(z):
        return NO_BASELINE_BAND

    if z <= -2:
        return BAND_BY_KEY["deep_below"]
    if z <= -1:
        return BAND_BY_KEY["below"]
    if z < 1:
        return BAND_BY_KEY["normal"]
    if z < 2:
        return BAND_BY_KEY["above"]

    return BAND_BY_KEY["deep_above"]


@st.cache_data(show_spinner=False)
def load_alberta_geojson() -> dict:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    if ALBERTA_GEOJSON_FILE.exists():
        with ALBERTA_GEOJSON_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)

    params = {
        "where": "1=1",
        "outFields": "OBJECTID,PROV_NAME",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }

    response = requests.get(
        ALBERTA_BOUNDARY_URL,
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    geojson = response.json()

    if not geojson.get("features"):
        raise ValueError("The Alberta boundary service returned no features.")

    with ALBERTA_GEOJSON_FILE.open("w", encoding="utf-8") as f:
        json.dump(geojson, f)

    return geojson


def filter_pipeline_geojson_by_diameter(
    geojson: dict | None,
    minimum_diameter_mm: float,
) -> dict | None:
    if not geojson:
        return None

    features = []
    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        diameter = pd.to_numeric(
            pd.Series([props.get("OUT_DIAMET")]),
            errors="coerce",
        ).iloc[0]

        if pd.notna(diameter) and float(diameter) >= minimum_diameter_mm:
            features.append(feature)

    return {"type": "FeatureCollection", "features": features}


# ============================================================
# METRIC HELPERS
# ============================================================

def mmcf_to_bcf(value: float) -> float:
    return float(value) / 1000 if not pd.isna(value) else math.nan


def fmt_bcf(value: float, signed: bool = False) -> str:
    if pd.isna(value):
        return "—"

    bcf = mmcf_to_bcf(value)
    return f"{bcf:+.2f}" if signed else f"{bcf:.2f}"


def nearest_row(df: pd.DataFrame, timestamp: pd.Timestamp) -> pd.Series:
    exact = df.loc[df["Timestamp"] == timestamp]
    if not exact.empty:
        return exact.iloc[-1]

    idx = (df["Timestamp"] - timestamp).abs().idxmin()
    return df.loc[idx]


def prior_value(
    df: pd.DataFrame,
    column: str,
    timestamp: pd.Timestamp,
) -> float:
    earlier = df.loc[df["Timestamp"] < timestamp, ["Timestamp", column]]
    if earlier.empty:
        return math.nan
    return float(earlier.iloc[-1][column])


def trailing_average(
    df: pd.DataFrame,
    column: str,
    timestamp: pd.Timestamp,
    hours: int,
) -> float:
    start = timestamp - pd.Timedelta(hours=hours)
    subset = df.loc[
        (df["Timestamp"] > start) & (df["Timestamp"] <= timestamp),
        column,
    ]

    return float(subset.mean()) if not subset.empty else math.nan


def metric_snapshot(
    df: pd.DataFrame,
    column: str,
    timestamp: pd.Timestamp,
) -> dict[str, float]:
    row = nearest_row(df, timestamp)
    current = float(row[column]) if not pd.isna(row[column]) else math.nan
    previous = prior_value(df, column, timestamp)
    avg24 = trailing_average(df, column, timestamp, 24)
    avg7d = trailing_average(df, column, timestamp, 24 * 7)

    return {
        "current": current,
        "previous": previous,
        "change": (
            current - previous
            if not pd.isna(current) and not pd.isna(previous)
            else math.nan
        ),
        "avg24": avg24,
        "avg7d": avg7d,
        "vs24_mag": (
            abs(current) - abs(avg24)
            if not pd.isna(current) and not pd.isna(avg24)
            else math.nan
        ),
        "vs7d_mag": (
            abs(current) - abs(avg7d)
            if not pd.isna(current) and not pd.isna(avg7d)
            else math.nan
        ),
    }


def comparison_colour(value: float, tolerance_mmcf: float = 25) -> str:
    if pd.isna(value) or abs(value) <= tolerance_mmcf:
        return "#969faf"
    return "#46be78" if value > 0 else "#e65c5c"


def band_pill(band: dict, label: str, note: str) -> str:
    """Delta-style bubble rendered directly beneath a metric.

    Mirrors the shape and type scale of Streamlit's native metric delta
    ("+0.11 vs prior obs.") so the two read as a stacked pair, tinted
    with the band colour rather than Streamlit's red/green.
    """
    r, g, b = band["colour"][:3]

    return (
        f'<div class="metric-band" '
        f'style="background: rgba({r},{g},{b},0.16); color: {band["hex"]};">'
        f'{label}'
        f'<span class="band-sd">{note}</span>'
        f'</div>'
    )


def render_baseline_band(current: float, base: dict | None) -> None:
    """Render the deviation bubble for an Alberta-wide metric.

    Metrics without enough trailing CSR history render as an explicit
    grey bubble rather than being given a colour that would imply more
    confidence than the data supports.
    """
    if base is None:
        return

    z = deviation_zscore(current, base)

    if pd.isna(z):
        st.markdown(
            band_pill(
                NO_BASELINE_BAND,
                NO_BASELINE_BAND["label"],
                f"{base['count']}/{BASELINE_MIN_OBSERVATIONS} obs.",
            ),
            unsafe_allow_html=True,
        )
        return

    band = classify_deviation(z)

    # Say what the baseline actually spans. Once the archive is longer
    # than the window this reads as the plain window; while it is
    # shorter, the shortfall is on the face of the bubble instead of
    # being implied by a label the data cannot support.
    window = base.get("window_days", ALBERTA_BASELINE_WINDOW_DAYS)
    covered = base.get("covered_days")
    if covered is not None and covered < window - 0.5:
        against = f"{covered:.0f}d of {window}d"
    else:
        against = f"{window}d"

    st.markdown(
        band_pill(band, band["label"], f"{z:+.2f} sd vs {against}"),
        unsafe_allow_html=True,
    )


def display_metric(
    label: str,
    snap: dict[str, float],
    unit: str,
    signed: bool = False,
    caption: str | None = None,
    baseline: dict | None = None,
) -> None:
    current = snap["current"]

    if unit in {"Bcf/d", "Bcf", "Bcf / 4h"}:
        current_text = (
            "—"
            if pd.isna(current)
            else (
                f"{mmcf_to_bcf(current):+.2f} {unit}"
                if signed
                else f"{mmcf_to_bcf(current):.2f} {unit}"
            )
        )
        delta_text = (
            None
            if pd.isna(snap["change"])
            else f"{mmcf_to_bcf(snap['change']):+.2f} vs prior obs."
        )
    else:
        current_text = "—" if pd.isna(current) else f"{current:,.0f} {unit}"
        delta_text = (
            None
            if pd.isna(snap["change"])
            else f"{snap['change']:+,.0f} vs prior obs."
        )

    st.metric(label, current_text, delta_text)

    render_baseline_band(snap["current"], baseline)

    if caption:
        st.caption(caption)


# ============================================================
# LOAD DATA
# ============================================================

try:
    if not CSR_FILE.exists():
        raise FileNotFoundError(f"Missing CSR master file: {CSR_FILE}")

    csr_mtime = CSR_FILE.stat().st_mtime_ns
    csr = load_csr_data(str(CSR_FILE), csr_mtime)

    alberta_geojson = load_alberta_geojson()

    if NGTL_PIPELINE_FILE.exists():
        pipeline_mtime = NGTL_PIPELINE_FILE.stat().st_mtime_ns
        ngtl_pipeline_geojson = load_pipeline_geojson(
            str(NGTL_PIPELINE_FILE),
            pipeline_mtime,
        )
    else:
        ngtl_pipeline_geojson = None

    if GDSR_FLOWS_FILE.exists():
        gdsr_mtime = GDSR_FLOWS_FILE.stat().st_mtime_ns
        gdsr_flows = load_gdsr_flows(str(GDSR_FLOWS_FILE), gdsr_mtime)
    else:
        gdsr_flows = None

    if NGTL_COMPRESSOR_FILE.exists():
        compressors = load_installation_points(
            str(NGTL_COMPRESSOR_FILE),
            NGTL_COMPRESSOR_FILE.stat().st_mtime_ns,
        )
    else:
        compressors = None

    if NGTL_METER_FILE.exists():
        meter_stations = load_installation_points(
            str(NGTL_METER_FILE),
            NGTL_METER_FILE.stat().st_mtime_ns,
        )
    else:
        meter_stations = None

    if BC_PIPELINE_FILE.exists():
        with BC_PIPELINE_FILE.open("r", encoding="utf-8") as f:
            bc_pipelines = json.load(f)
    else:
        bc_pipelines = None

    if OUTAGE_FILE.exists():
        outages = load_outages(str(OUTAGE_FILE), OUTAGE_FILE.stat().st_mtime_ns)
    else:
        outages = None

    if OUTAGE_CHANGES_FILE.exists():
        outage_changes = pd.read_csv(OUTAGE_CHANGES_FILE)
        for _col in ("published", "previous_published", "start", "end"):
            if _col in outage_changes:
                outage_changes[_col] = pd.to_datetime(
                    outage_changes[_col], errors="coerce"
                )
    else:
        outage_changes = None

    if OUTAGE_AREA_FILE.exists():
        with OUTAGE_AREA_FILE.open("r", encoding="utf-8") as f:
            outage_areas = json.load(f)
    else:
        outage_areas = None

except Exception as exc:
    st.error(str(exc))
    st.stop()


if csr.empty:
    st.error("CSR_Master.csv contains no valid observations.")
    st.stop()


# ============================================================
# HEADER / TIMESTAMP CONTROL
# ============================================================

latest_timestamp = pd.Timestamp(csr["Timestamp"].max())
earliest_timestamp = pd.Timestamp(csr["Timestamp"].min())
available_timestamps = csr["Timestamp"].tolist()

st.markdown(
    '<div class="title">NGTL Current System Report</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="subtitle">'
    'Intraday NGTL flows, linepack, storage and interconnect monitoring'
    '</div>',
    unsafe_allow_html=True,
)

header_left, header_mid, header_right = st.columns([2.3, 1.0, 0.75])

with header_left:
    st.markdown(
        f'<div class="timestamp-chip">'
        f'Latest CSR observation: {latest_timestamp:%b %d, %Y %H:%M:%S}'
        f'</div>',
        unsafe_allow_html=True,
    )

with header_mid:
    if st.button("Jump to latest", use_container_width=True):
        st.session_state["csr_timestamp"] = latest_timestamp
        st.session_state["selected_interconnect"] = None

with header_right:
    if st.button("Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


if "csr_timestamp" not in st.session_state:
    st.session_state["csr_timestamp"] = latest_timestamp

if st.session_state["csr_timestamp"] not in available_timestamps:
    st.session_state["csr_timestamp"] = latest_timestamp


selected_timestamp = st.select_slider(
    "CSR observation",
    options=available_timestamps,
    value=st.session_state["csr_timestamp"],
    format_func=lambda x: pd.Timestamp(x).strftime("%b %d %H:%M"),
    key="csr_timestamp_slider",
)

selected_timestamp = pd.Timestamp(selected_timestamp)
st.session_state["csr_timestamp"] = selected_timestamp

selected_row = nearest_row(csr, selected_timestamp)


# ============================================================
# SNAPSHOTS
# ============================================================

snapshots = {
    col: metric_snapshot(csr, col, selected_timestamp)
    for col in EXPECTED_COLUMNS[1:]
}

linepack_gap_series = csr["Current Linepack"] - csr["Linepack Target"]
linepack_gap_df = pd.DataFrame(
    {
        "Timestamp": csr["Timestamp"],
        "Linepack vs Target": linepack_gap_series,
    }
)
linepack_gap_snap = metric_snapshot(
    linepack_gap_df,
    "Linepack vs Target",
    selected_timestamp,
)

# Trailing CSR baselines for the Alberta-wide panel. Every displayed
# metric is banded against its own recent history on the same feed.
ALBERTA_PANEL_COLUMNS = [
    "NGTL-Field Receipts",
    "Intraprovincial Demand",
    "Total Receipts",
    "Total Deliveries",
    "Net Storage Flow",
    "Flow Differential",
    "Current Linepack",
]

alberta_baselines = {
    column: csr_baseline(csr, column, selected_timestamp)
    for column in ALBERTA_PANEL_COLUMNS
}

linepack_gap_baseline = csr_baseline(
    linepack_gap_df,
    "Linepack vs Target",
    selected_timestamp,
)


# ============================================================
# INTERCONNECT MAP DATA
# ============================================================

border_points = pd.DataFrame(INTERCONNECTS)

border_points["current"] = border_points["column"].map(
    lambda c: snapshots[c]["current"]
)
border_points["previous"] = border_points["column"].map(
    lambda c: snapshots[c]["previous"]
)
border_points["avg24"] = border_points["column"].map(
    lambda c: snapshots[c]["avg24"]
)
border_points["avg7d"] = border_points["column"].map(
    lambda c: snapshots[c]["avg7d"]
)
border_points["vs24_mag"] = border_points["column"].map(
    lambda c: snapshots[c]["vs24_mag"]
)
border_points["vs7d_mag"] = border_points["column"].map(
    lambda c: snapshots[c]["vs7d_mag"]
)

# ---- active maintenance for the selected gas day ------------
# Resolved before the map is built so the markers and the maintenance
# panel below it are driven by exactly the same rows.

selected_gas_day = pd.Timestamp(selected_timestamp).normalize()

if outages is not None:
    active_outages = outages.loc[
        outages["gas_day"] == selected_gas_day
    ].copy()
else:
    active_outages = pd.DataFrame()

# interconnect key -> {"impact": bool, "notes": [str, ...]}
interconnect_outages: dict[str, dict] = {}

for row in active_outages.itertuples():
    for key in OUTAGE_TABLE_TO_INTERCONNECT.get(row.table_code, []):
        entry = interconnect_outages.setdefault(
            key, {"impact": False, "notes": [], "severity": "unknown",
                  "derate": 0.0}
        )
        restriction = str(getattr(row, "restriction", "") or "")
        if OUTAGE_IMPACT_MARKER in restriction.lower():
            entry["impact"] = True

        severity = str(getattr(row, "severity", "unknown") or "unknown")
        if SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK[entry["severity"]]:
            entry["severity"] = severity

        derate = float(getattr(row, "derate_pct", 0.0) or 0.0)
        entry["derate"] = max(entry["derate"], derate)

        entry["notes"].append(
            f"{row.table_code}: {row.facility} "
            f"({severity}, -{derate:.0f}%)"
        )


# ---- capacity areas shaded by today's severity --------------
# Areas are matched on either vocabulary: the outage export uses the
# dopAcronym (FHZ8), TC's area feed uses the map acronym (FHBC).

area_severity: dict[str, dict] = {}
for row in active_outages.itertuples():
    code = str(row.table_code)
    entry = area_severity.setdefault(
        code, {"severity": "unknown", "derate": 0.0, "count": 0,
               "facilities": []}
    )
    sev = str(getattr(row, "severity", "unknown") or "unknown")
    if SEVERITY_RANK.get(sev, 0) > SEVERITY_RANK[entry["severity"]]:
        entry["severity"] = sev
    entry["derate"] = max(entry["derate"],
                          float(getattr(row, "derate_pct", 0.0) or 0.0))
    entry["count"] += 1
    if row.facility not in entry["facilities"]:
        entry["facilities"].append(row.facility)

display_areas = None
if outage_areas:
    feats = []
    for feature in outage_areas.get("features", []):
        props = dict(feature.get("properties") or {})
        hit = (
            area_severity.get(props.get("dop_acronym"))
            or area_severity.get(props.get("acronym"))
        )
        band = OUTAGE_SEVERITY[hit["severity"]] if hit else None

        props["has_outage"] = bool(hit)
        props["severity"] = hit["severity"] if hit else "none"
        props["fill"] = (
            band["colour"][:3] + [110] if band
            else (props.get("tc_colour") or [150, 158, 172, 120])[:3] + [26]
        )
        props["outline"] = (
            band["colour"][:3] + [235] if band else [150, 158, 172, 90]
        )
        props["tooltip_title"] = (
            f"{props.get('display_name')} ({props.get('acronym')})"
        )
        props["tooltip_line1"] = (
            f"{hit['count']} outage(s) today · {band['label']} "
            f"(-{hit['derate']:.1f}% vs base)"
            if hit else "No maintenance on this gas day"
        )
        props["tooltip_line2"] = (
            ", ".join(hit["facilities"][:4]) if hit else ""
        )
        for i in range(3, 7):
            props[f"tooltip_line{i}"] = ""
        feats.append({**feature, "properties": props})
    display_areas = {"type": "FeatureCollection", "features": feats}


# ---- trailing GDSR baseline and deviation banding -----------
# Colour is the only visual channel carrying the deviation signal;
# marker size is deliberately constant so intensity is not confounded
# with flow size.

baselines = {
    row["key"]: gdsr_baseline(
        gdsr_flows,
        row["gdsr_item"],
        selected_timestamp,
    )
    for row in INTERCONNECTS
}

border_points["base_mean"] = border_points["key"].map(
    lambda k: baselines[k]["mean"]
)
border_points["base_std"] = border_points["key"].map(
    lambda k: baselines[k]["std"]
)
border_points["base_count"] = border_points["key"].map(
    lambda k: baselines[k]["count"]
)

border_points["z_score"] = border_points.apply(
    lambda r: deviation_zscore(r["current"], baselines[r["key"]]),
    axis=1,
)

border_points["band_key"] = border_points["z_score"].map(
    lambda z: classify_deviation(z)["key"]
)
border_points["band_label"] = border_points["z_score"].map(
    lambda z: classify_deviation(z)["label"]
)
border_points["marker_colour"] = border_points["z_score"].map(
    lambda z: classify_deviation(z)["colour"]
)

border_points["vs_base_mmcf"] = (
    border_points["current"].abs() - border_points["base_mean"]
)

# ---- flow-direction arrows ---------------------------------
# Direction is taken from GDSR, NOT from the CSR reading in "current".
#
# The two feeds do not share a sign convention. GDSR signs its flows -
# positive into NGTL, negative out of it, so Empress publishes as
# -4,133. CSR publishes the same flow unsigned, as +4,112: every CSR
# flow column is non-negative over the whole archive. Only Linepack ROC,
# Net Storage Flow and Flow Differential carry a real sign in CSR.
#
# So CSR cannot say which way gas is moving. Using it would have drawn
# every arrow as an inbound flow, including Empress and McNeill, which
# are Alberta's two big export points. The daily GDSR value is a gas day
# behind, which is the price of getting the direction right.
def gdsr_signed_latest(item: str) -> float:
    """Most recent signed GDSR reading for one item, or NaN."""
    if gdsr_flows is None:
        return math.nan
    rows = gdsr_flows.loc[
        (gdsr_flows["Item"] == item)
        & (gdsr_flows["GasDay"] <= selected_timestamp),
        "ExtrapolatedMMcfd",
    ].dropna()
    return float(rows.iloc[-1]) if len(rows) else math.nan


border_points["signed_flow"] = border_points["gdsr_item"].map(
    gdsr_signed_latest
)

# deck.gl measures get_angle counter-clockwise from east, while a
# bearing is clockwise from north, hence the 90 - bearing. The glyph
# already points east at angle 0, so no further offset is needed.
_flow_bearing = border_points.apply(
    lambda r: (
        r["bearing_out"]
        if r["signed_flow"] < 0
        else r["bearing_out"] + 180
    ),
    axis=1,
)
border_points["flow_angle"] = (90 - _flow_bearing) % 360

# No arrow where GDSR has no reading, or the flow is exactly zero:
# better a bare dot than an arrow asserting a direction the data does
# not support. Willow Valley genuinely reverses, so this is not
# hypothetical.
border_points["flow_arrow"] = np.where(
    border_points["signed_flow"].isna()
    | (border_points["signed_flow"] == 0),
    "",
    FLOW_ARROW_GLYPH,
)

border_points["flow_direction_text"] = np.where(
    border_points["signed_flow"].isna(),
    "Direction unavailable",
    np.where(
        border_points["signed_flow"] < 0, "Out of NGTL", "Into NGTL"
    ),
)

# ---- display-only marker spreading -------------------------
# At 36 px across, dots at neighbouring points overlap and hide each
# other: Empress and McNeill are 32 km apart, and Groundbirch East,
# Gordondale and Willow Valley sit inside a 40 km triangle.
#
# Each cluster is pushed apart from its own centroid by a fixed factor,
# so the arrangement stays true - relative bearings and spacing within
# the cluster are preserved, just magnified. This is cartographic
# displacement, the same thing a printed map does with crowded symbols.
#
# Critically these columns are used ONLY for drawing. lat/lon keep the
# real coordinates, so anything measuring distance or joining to
# geometry is untouched. Nothing currently does, but the separation is
# what keeps a display tweak from quietly becoming a data error.
MARKER_SPREAD_FACTOR = 2.4
MARKER_SPREAD_CLUSTERS = [
    ["Empress", "McNeill"],
    ["Groundbirch East", "Gordondale", "Willow Valley"],
]

border_points["lat_display"] = border_points["lat"]
border_points["lon_display"] = border_points["lon"]

for _cluster in MARKER_SPREAD_CLUSTERS:
    _mask = border_points["key"].isin(_cluster)
    if _mask.sum() < 2:
        continue
    _clat = border_points.loc[_mask, "lat"].mean()
    _clon = border_points.loc[_mask, "lon"].mean()
    border_points.loc[_mask, "lat_display"] = (
        _clat + (border_points.loc[_mask, "lat"] - _clat)
        * MARKER_SPREAD_FACTOR
    )
    border_points.loc[_mask, "lon_display"] = (
        _clon + (border_points.loc[_mask, "lon"] - _clon)
        * MARKER_SPREAD_FACTOR
    )

border_points["outage_active"] = border_points["key"].map(
    lambda k: k in interconnect_outages
)
border_points["outage_impact"] = border_points["key"].map(
    lambda k: interconnect_outages.get(k, {}).get("impact", False)
)
border_points["outage_note"] = border_points["key"].map(
    lambda k: " · ".join(interconnect_outages.get(k, {}).get("notes", []))
)
border_points["outage_severity"] = border_points["key"].map(
    lambda k: interconnect_outages.get(k, {}).get("severity", "unknown")
)
border_points["outage_derate"] = border_points["key"].map(
    lambda k: interconnect_outages.get(k, {}).get("derate", math.nan)
)
border_points["outage_ring_colour"] = border_points["outage_severity"].map(
    lambda sev: OUTAGE_SEVERITY.get(
        sev if isinstance(sev, str) else "unknown", OUTAGE_SEVERITY["unknown"]
    )["colour"]
)

border_points["tooltip_title"] = border_points["display_name"]
border_points["tooltip_line1"] = border_points.apply(
    lambda r: (
        f"{r['current']:,.0f} MMcf/d · {r['direction']}"
        if not pd.isna(r["current"])
        else "No current value"
    ),
    axis=1,
)
border_points["tooltip_line2"] = border_points.apply(
    lambda r: (
        f"{MARKER_BASELINE_WINDOW_DAYS}d normal: "
        f"{r['base_mean']:,.0f} MMcf/d "
        f"(± {r['base_std']:,.0f})"
        if not pd.isna(r["base_mean"])
        else "baseline unavailable"
    ),
    axis=1,
)
border_points["tooltip_line3"] = border_points.apply(
    lambda r: (
        f"{r['vs_base_mmcf']:+,.0f} MMcf/d vs "
        f"{MARKER_BASELINE_WINDOW_DAYS}d normal"
        if not pd.isna(r["vs_base_mmcf"])
        else ""
    ),
    axis=1,
)
border_points["tooltip_line4"] = border_points.apply(
    lambda r: (
        f"{r['band_label']} ({r['z_score']:+.1f} std dev)"
        if not pd.isna(r["z_score"])
        else r["band_label"]
    ),
    axis=1,
)
border_points["tooltip_line5"] = border_points.apply(
    lambda r: (
        f"⚠ Maintenance: {r['outage_note']}"
        if r["outage_active"]
        else "Click for detail"
    ),
    axis=1,
)
border_points["tooltip_line6"] = ""


# ============================================================
# INSTALLATION LAYER DATA
# ============================================================

if compressors is not None and not compressors.empty:
    compressors = compressors.copy()
    compressors["multi_direction"] = (
        compressors.get("multi_direction", False).fillna(False).astype(bool)
        if "multi_direction" in compressors
        else False
    )
    compressors["marker_glyph"] = np.where(
        compressors["multi_direction"],
        COMPRESSOR_MULTI_GLYPH,
        COMPRESSOR_GLYPH,
    )

    # Stations named in an outage active on the selected gas day take the
    # severity colour; everything else stays neutral.
    outage_keys = {}
    for row in active_outages.itertuples():
        key = re.sub(r"[^A-Z]", "", str(row.facility).upper())
        key = re.sub(r"(?:[A-Z]\d*|NO\d+[A-Z]?)$", "", key) or key
        rank = SEVERITY_RANK.get(str(row.severity), 0)
        if rank >= SEVERITY_RANK.get(outage_keys.get(key, "unknown"), 0):
            outage_keys[key] = str(row.severity)

    def match_outage(station_key) -> str:
        """Severity of any outage naming this station, else "" (not NA).

        An empty string rather than None/NaN: pandas' arrow-backed
        columns propagate pd.NA, which is truthy, so a null would sail
        through a plain `if sev` check and blow up the colour lookup.
        """
        if station_key is None or pd.isna(station_key):
            return ""

        station_key = str(station_key)
        for key, sev in outage_keys.items():
            if key and station_key and (key == station_key
                                        or key in station_key
                                        or station_key in key):
                return sev
        return ""

    compressors["outage_severity"] = (
        compressors["match_key"].map(match_outage).fillna("").astype(str)
    )
    compressors["under_maintenance"] = compressors["outage_severity"] != ""
    compressors["marker_colour"] = compressors["outage_severity"].map(
        lambda sev: OUTAGE_SEVERITY[sev]["colour"]
        if sev in OUTAGE_SEVERITY
        else COMPRESSOR_PURPLE
    )
    compressors["label_text"] = compressors["name"].fillna("").astype(str)

    compressors["tooltip_title"] = compressors["name"].fillna("Compressor station")
    compressors["tooltip_line1"] = np.where(
        compressors["multi_direction"],
        "Multi-direction compressor station (can reverse)",
        "Compressor station",
    )
    compressors["tooltip_line2"] = compressors.apply(
        lambda r: (
            f"\u26a0 Maintenance today \u00b7 {r['outage_severity']}"
            if r["under_maintenance"] else "No maintenance on this gas day"
        ),
        axis=1,
    )
    compressors["tooltip_line3"] = (
        compressors["snapped"].map(
            lambda v: (
                "Position snapped to the NGTL network"
                if bool(v) else "Position approximate \u2014 not on a known NGTL pipe"
            )
        )
        if "snapped" in compressors else "Position approximate"
    )
    for _i in range(4, 7):
        compressors[f"tooltip_line{_i}"] = ""

if meter_stations is not None and not meter_stations.empty:
    meter_stations = meter_stations.copy()

    meter_stations["tooltip_title"] = (
        "Meter station " + meter_stations["LICINSTNO"].astype(str)
    )
    meter_stations["tooltip_line1"] = (
        "Location: " + meter_stations["INST_LOCAT"].fillna("—").astype(str)
    )
    meter_stations["tooltip_line2"] = (
        "Field centre: " + meter_stations["FLD_CENTRE"].fillna("—").astype(str)
    )
    meter_stations["tooltip_line3"] = (
        "Licence " + meter_stations["INSTA_LIC"].fillna("—").astype(str)
        + " · " + meter_stations["PLINSTATUS"].fillna("—").astype(str)
    )
    meter_stations["tooltip_line4"] = meter_stations["BA_NAME"].fillna("—")
    meter_stations["tooltip_line5"] = ""
    meter_stations["tooltip_line6"] = ""


# ============================================================
# MAP CONTROLS
# ============================================================

(
    pipeline_control_col1,
    pipeline_control_col2,
    area_control_col,
    bc_control_col,
    station_control_col1,
    station_control_col2,
    context_col,
) = st.columns([0.9, 1.1, 0.95, 0.95, 1.1, 0.95, 1.05])

with pipeline_control_col1:
    show_ngtl_pipelines = st.checkbox(
        "Show NGTL pipelines",
        value=True,
        help=(
            "Operating natural-gas pipeline segments licensed to "
            "NOVA Gas Transmission Ltd."
        ),
    )

with pipeline_control_col2:
    main_lines_only = st.checkbox(
        "Main transmission lines only",
        value=False,
        help=(
            "For display purposes, this filters the processed NGTL layer "
            "to pipeline segments with diameter ≥600 mm."
        ),
    )

with area_control_col:
    show_outage_areas = st.checkbox(
        "Show capacity areas",
        value=True,
        disabled=outage_areas is None,
        help=(
            "TC's own outage capacity areas (USJR, EGAT, WGAT, OSDA, NEDA, "
            "Foothills BC/SK), shaded by the severity of maintenance active "
            "on the selected gas day. Station and interconnect maintenance "
            "colouring is independent of this toggle."
        ),
    )

with bc_control_col:
    show_bc_pipelines = st.checkbox(
        "Show BC pipelines",
        value=bc_pipelines is not None,
        disabled=bc_pipelines is None,
        help=(
            "BC Energy Regulator transmission pipelines, giving the "
            "western interconnects their BC-side context. Post-2016 "
            "permits only, so Westcoast T-South is largely absent."
        ),
    )

with station_control_col1:
    show_compressors = st.checkbox(
        "Show compressor stations",
        value=True,
        disabled=compressors is None,
        help=(
            "Operating NGTL compressor stations from the AER installation "
            "Named stations from TC's NGTL Segment Codes map. Diamonds "
            "are multi-direction stations; those named in an outage "
            "today take the severity colour."
        ),
    )

with station_control_col2:
    show_meter_stations = st.checkbox(
        "Show meter stations",
        value=False,
        disabled=meter_stations is None,
        help=(
            "Operating NGTL meter stations. There are 947 of them, so this "
            "is dense at province zoom."
        ),
    )

with context_col:
    st.caption(
        f"Available history: {earliest_timestamp:%b %d %H:%M} "
        f"to {latest_timestamp:%b %d %H:%M} · "
        f"{len(csr):,} unique observations."
    )

display_pipeline_geojson = ngtl_pipeline_geojson
if main_lines_only:
    display_pipeline_geojson = filter_pipeline_geojson_by_diameter(
        ngtl_pipeline_geojson,
        minimum_diameter_mm=600,
    )


# ============================================================
# MAP LAYERS
# ============================================================

map_layers: list[pdk.Layer] = []

map_layers.append(
    pdk.Layer(
        "GeoJsonLayer",
        alberta_geojson,
        id="alberta-boundary",
        stroked=True,
        filled=True,
        pickable=False,
        get_fill_color=[58, 68, 84, 80],
        get_line_color=[205, 215, 228, 190],
        line_width_min_pixels=1.5,
    )
)

if show_outage_areas and display_areas:
    map_layers.append(
        pdk.Layer(
            "GeoJsonLayer",
            display_areas,
            id="outage-areas",
            stroked=True,
            filled=True,
            pickable=True,
            auto_highlight=True,
            get_fill_color="properties.fill",
            get_line_color="properties.outline",
            line_width_min_pixels=1.8,
        )
    )

if show_bc_pipelines and bc_pipelines:
    # Wide transparent copy first so it sits *under* the visible line:
    # deck.gl picks the topmost layer, so if this were on top it would
    # swallow every hover and the visible line would never highlight.
    # Alpha 0 still registers for picking.
    map_layers.append(
        pdk.Layer(
            "GeoJsonLayer",
            bc_pipelines,
            id="bc-pipelines-hit",
            stroked=True,
            filled=False,
            pickable=True,
            auto_highlight=False,
            get_line_color=[0, 0, 0, 0],
            line_width_min_pixels=BC_PIPE_HIT_WIDTH_PX,
        )
    )

    map_layers.append(
        pdk.Layer(
            "GeoJsonLayer",
            bc_pipelines,
            id="bc-pipelines",
            stroked=True,
            filled=False,
            pickable=True,
            auto_highlight=True,
            get_line_color=(
                "properties.is_key_operator ? "
                f"{BC_PIPE_KEY} : {BC_PIPE_OTHER}"
            ),
            highlight_color=[255, 209, 102, 255],
            line_width_min_pixels=BC_PIPE_WIDTH_PX,
        )
    )

if show_ngtl_pipelines and display_pipeline_geojson:
    map_layers.append(
        pdk.Layer(
            "GeoJsonLayer",
            display_pipeline_geojson,
            id="ngtl-pipelines",
            stroked=True,
            filled=False,
            pickable=True,
            auto_highlight=True,
            get_line_color=PIPELINE_BLUE,
            highlight_color=[255, 209, 102, 255],
            line_width_min_pixels=1.2,
        )
    )

# Installations are drawn after the pipelines but before the
# interconnect markers, so the flow-deviation markers stay on top and
# remain the first thing picked.
if (
    show_meter_stations
    and meter_stations is not None
    and not meter_stations.empty
):
    map_layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            meter_stations,
            id="meter-stations",
            pickable=True,
            auto_highlight=True,
            get_position="[lon, lat]",
            get_radius=METER_RADIUS_PX,
            radius_units='"pixels"',
            radius_min_pixels=METER_RADIUS_PX,
            radius_max_pixels=METER_RADIUS_PX,
            get_fill_color=METER_SLATE,
            stroked=False,
        )
    )

if show_compressors and compressors is not None and not compressors.empty:
    # Drawn as triangles so compressor stations are distinguishable from
    # the circular interconnect markers by shape alone, leaving colour
    # free for the maintenance/outage overlay. deck.gl's ScatterplotLayer
    # only draws circles, so a TextLayer rendering a triangle glyph is
    # used instead - it keeps pixel sizing and picking behaviour.
    map_layers.append(
        pdk.Layer(
            "TextLayer",
            compressors,
            id="compressor-stations",
            pickable=True,
            auto_highlight=True,
            get_position="[lon, lat]",
            get_text="marker_glyph",
            get_size=COMPRESSOR_GLYPH_SIZE_PX,
            size_units='"pixels"',
            # deck.gl builds its font atlas from ASCII 32-128 by default,
            # which excludes U+25B2 and renders the markers invisible.
            # Must be a tuple: pydeck serialises a list as a JS accessor
            # expression ("@@=[...]") rather than the literal array
            # characterSet requires.
            character_set=(COMPRESSOR_GLYPH, COMPRESSOR_MULTI_GLYPH),
            get_color="marker_colour",
            get_text_anchor='"middle"',
            get_alignment_baseline='"center"',
            font_family="Arial, Helvetica, sans-serif",
            font_weight=700,
            billboard=True,
        )
    )

# Outage ring, drawn beneath the interconnect markers so it reads as a
# halo around the deviation-coloured fill rather than replacing it.
outage_points = border_points.loc[border_points["outage_active"]]
if not outage_points.empty:
    map_layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            outage_points,
            id="interconnect-outage-rings",
            pickable=False,
            get_position="[lon_display, lat_display]",
            get_radius=MARKER_RADIUS_PIXELS + 7,
            radius_units='"pixels"',
            radius_min_pixels=MARKER_RADIUS_PIXELS + 7,
            radius_max_pixels=MARKER_RADIUS_PIXELS + 7,
            filled=False,
            stroked=True,
            get_line_color="outage_ring_colour",
            line_width_min_pixels=3.5,
        )
    )

if show_compressors and compressors is not None and not compressors.empty:
    map_layers.append(
        pdk.Layer(
            "TextLayer",
            compressors,
            id="compressor-labels",
            pickable=False,
            get_position="[lon, lat]",
            get_text="label_text",
            get_size=11,
            size_units='"pixels"',
            get_color=[226, 222, 240, 210],
            get_text_anchor='"middle"',
            get_alignment_baseline='"top"',
            get_pixel_offset=[0, COMPRESSOR_GLYPH_SIZE_PX * 0.55],
            font_family="Arial, Helvetica, sans-serif",
            font_weight=600,
            billboard=True,
        )
    )

map_layers.append(
    pdk.Layer(
        "ScatterplotLayer",
        border_points,
        id="border-points",
        pickable=True,
        auto_highlight=True,
        get_position="[lon_display, lat_display]",
        get_radius=MARKER_RADIUS_PIXELS,
        radius_units='"pixels"',
        radius_min_pixels=MARKER_RADIUS_PIXELS,
        radius_max_pixels=MARKER_RADIUS_PIXELS,
        get_fill_color="marker_colour",
        get_line_color=WHITE,
        line_width_min_pixels=1.6,
        stroked=True,
    )
)

# Drawn after the dots so the arrow sits on top of the fill. Not
# pickable: the dot underneath owns the hover, and a second pickable
# layer at the same coordinates would steal it.
map_layers.append(
    pdk.Layer(
        "TextLayer",
        border_points,
        id="border-flow-arrows",
        pickable=False,
        get_position="[lon_display, lat_display]",
        get_text="flow_arrow",
        get_size=FLOW_ARROW_SIZE_PX,
        size_units='"pixels"',
        get_angle="flow_angle",
        # Same trap as the compressor glyphs: deck.gl builds its font
        # atlas from ASCII unless told otherwise, and a list serialises
        # as a JS accessor rather than a literal array, so this must
        # stay a tuple or the arrows render invisible.
        character_set=(FLOW_ARROW_GLYPH,),
        get_color=FLOW_ARROW_COLOUR,
        get_text_anchor='"middle"',
        get_alignment_baseline='"center"',
        font_family="Arial, Helvetica, sans-serif",
        billboard=True,
    )
)

labels_above = border_points.loc[
    border_points["label_side"] == "above"
].copy()

labels_below = border_points.loc[
    border_points["label_side"] == "below"
].copy()

map_layers.append(
    pdk.Layer(
        "TextLayer",
        labels_above,
        id="border-labels-above",
        get_position="[lon_display, lat_display]",
        get_text="display_name",
        get_size=14,
        size_units='"pixels"',
        get_color=[245, 245, 250, 255],
        get_text_anchor='"middle"',
        get_alignment_baseline='"bottom"',
        get_pixel_offset=[0, -13],
        font_family="Arial, Helvetica, sans-serif",
        font_weight=650,
        pickable=False,
    )
)

map_layers.append(
    pdk.Layer(
        "TextLayer",
        labels_below,
        id="border-labels-below",
        get_position="[lon_display, lat_display]",
        get_text="display_name",
        get_size=14,
        size_units='"pixels"',
        get_color=[245, 245, 250, 255],
        get_text_anchor='"middle"',
        get_alignment_baseline='"top"',
        get_pixel_offset=[0, 13],
        font_family="Arial, Helvetica, sans-serif",
        font_weight=650,
        pickable=False,
    )
)

deck = pdk.Deck(
    layers=map_layers,
    initial_view_state=pdk.ViewState(
        latitude=54.7,
        longitude=-114.8,
        zoom=4.1,
        pitch=0,
        bearing=0,
    ),
    map_style="dark",
    tooltip={
        "html": """
        <div style="font-size:16px; font-weight:700;">
            {tooltip_title}
        </div>
        <div style="margin-top:5px; color:#c1cad6;">
            {tooltip_line1}
        </div>
        <div style="margin-top:3px; color:#aeb8c5;">{tooltip_line2}</div>
        <div style="margin-top:3px; color:#aeb8c5;">{tooltip_line3}</div>
        <div style="margin-top:3px; color:#aeb8c5;">{tooltip_line4}</div>
        <div style="margin-top:3px; color:#aeb8c5;">{tooltip_line5}</div>
        <div style="margin-top:3px; color:#aeb8c5;">{tooltip_line6}</div>
        """,
        "style": {
            "backgroundColor": "rgba(18,22,30,0.98)",
            "color": "white",
            "fontSize": "13px",
            "padding": "12px 14px",
            "minWidth": "260px",
            "border": "2px solid rgba(255,255,255,0.24)",
            "borderRadius": "8px",
        },
    },
)


# ============================================================
# MAP + RHS
# ============================================================

# The map is given a portrait aspect on purpose: Alberta spans about 11
# degrees of latitude against 7 of longitude at this extent, so a wide
# frame spent most of its pixels on empty BC and Saskatchewan. A narrow
# tall frame fits the province and puts Empress and the BC border points
# further apart on screen.
#
# The legend moves into its own column beside the map rather than
# wrapping underneath it, which a narrow map would otherwise turn into
# four or five stacked rows.
map_col, legend_col, system_col = st.columns(
    [1.25, 0.55, 1.0], gap="large"
)

with map_col:
    st.markdown(
        '<div class="section-label">NGTL system geography</div>',
        unsafe_allow_html=True,
    )

    map_event = st.pydeck_chart(
        deck,
        use_container_width=True,
        height=880,
        on_select="rerun",
        selection_mode="single-object",
        key="csr_system_map",
    )

    try:
        selected_objects = map_event.selection.get("objects", {})
        selected_border_objects = selected_objects.get("border-points", [])

        if selected_border_objects:
            selected_label = selected_border_objects[0].get("key")
            if selected_label:
                st.session_state["selected_interconnect"] = selected_label
    except Exception:
        pass

    if ngtl_pipeline_geojson is None:
        st.warning(
            "NGTL pipeline layer not found at "
            f"{NGTL_PIPELINE_FILE}"
        )

    legend_items = "".join(
        f'<span class="legend-item">'
        f'<span class="legend-dot" style="background:{band["hex"]};"></span>'
        f'{band["label"]}'
        f'<span class="legend-detail">{band["detail"]}</span>'
        f'</span>'
        for band in DEVIATION_BANDS
    )

    if border_points["band_key"].eq("no_baseline").any():
        legend_items += (
            f'<span class="legend-item">'
            f'<span class="legend-dot" '
            f'style="background:{NO_BASELINE_BAND["hex"]};"></span>'
            f'{NO_BASELINE_BAND["label"]}'
            f'<span class="legend-detail">'
            f'{NO_BASELINE_BAND["detail"]}</span>'
            f'</span>'
        )

    if show_outage_areas and display_areas:
        shaded = [f for f in display_areas["features"]
                  if f["properties"]["has_outage"]]
        if shaded:
            legend_items += (
                '<span class="legend-item">'
                '<span class="legend-area"></span>'
                f'Capacity area · {len(shaded)} with maintenance'
                '<span class="legend-detail">shaded by severity</span>'
                '</span>'
            )

    if not outage_points.empty:
        present = sorted(
            outage_points["outage_severity"].unique(),
            key=lambda sv: -SEVERITY_RANK.get(sv, 0),
        )
        for sev in present:
            band = OUTAGE_SEVERITY[sev]
            legend_items += (
                '<span class="legend-item">'
                '<span class="legend-ring" style="border-color:'
                f'{band["hex"]};"></span>'
                f'Maintenance · {band["label"]}'
                f'<span class="legend-detail">{band["detail"]}</span>'
                '</span>'
            )

    if show_bc_pipelines and bc_pipelines:
        legend_items += (
            '<span class="legend-item">'
            '<span class="legend-dot" style="background:rgb('
            f'{BC_PIPE_KEY[0]},{BC_PIPE_KEY[1]},{BC_PIPE_KEY[2]});"></span>'
            'BC pipelines'
            '<span class="legend-detail">BCER, post-2016 permits</span>'
            '</span>'
        )

    if show_compressors and compressors is not None and not compressors.empty:
        n_multi = int(compressors["multi_direction"].sum())
        n_maint = int(compressors["under_maintenance"].sum())
        if n_multi:
            legend_items += (
                '<span class="legend-item">'
                '<span class="legend-diamond" style="background:rgb('
                f'{COMPRESSOR_PURPLE[0]},{COMPRESSOR_PURPLE[1]},'
                f'{COMPRESSOR_PURPLE[2]});"></span>'
                f'Multi-direction ({n_multi})'
                '<span class="legend-detail">can reverse flow</span>'
                '</span>'
            )
        if n_maint:
            legend_items += (
                '<span class="legend-item">'
                '<span class="legend-triangle" style="border-bottom-color:'
                f'{OUTAGE_SEVERITY["moderate"]["hex"]};"></span>'
                f'Station on maintenance ({n_maint})'
                '</span>'
            )
        legend_items += (
            '<span class="legend-item">'
            '<span class="legend-triangle" style="border-bottom-color:rgb('
            f'{COMPRESSOR_PURPLE[0]},{COMPRESSOR_PURPLE[1]},'
            f'{COMPRESSOR_PURPLE[2]});"></span>'
            'Compressor station'
            '</span>'
        )

    if (
        show_meter_stations
        and meter_stations is not None
        and not meter_stations.empty
    ):
        legend_items += (
            '<span class="legend-item">'
            '<span class="legend-dot" style="background:rgb('
            f'{METER_SLATE[0]},{METER_SLATE[1]},{METER_SLATE[2]});"></span>'
            'Meter station'
            '</span>'
        )

    # Held rather than drawn here: the legend renders in its own column
    # further down, beside the map instead of beneath it.
    legend_html = f'<div class="legend-stack">{legend_items}</div>'

    if gdsr_flows is None:
        st.warning(
            "GDSR daily flow history not found at "
            f"{GDSR_FLOWS_FILE} — interconnect markers cannot be "
            "coloured against a 30-day baseline."
        )

    if compressors is None:
        st.info(
            "Compressor station layer not found. Run "
            "`python3 prepare_installation_layers.py` to build it from the "
            "AER installation shapefile."
        )
    elif show_compressors:
        station_note = (
            f"{len(compressors)} named NGTL compressor stations from TC's "
            f"Segment Codes map, {int(compressors['multi_direction'].sum())} "
            "of them multi-direction (diamonds). Positions are derived from "
            "that map and are approximate to a few km; they are not tied to "
            "AER licence geometry."
        )
        st.caption(station_note)

    line_mode_text = (
        "Main transmission view: operating NGTL lines ≥600 mm."
        if main_lines_only
        else "Full NGTL view: all processed operating NGTL gas segments."
    )

    st.caption(
        "Interconnect markers are coloured by how the current reading "
        "compares with that point's own trailing "
        f"{MARKER_BASELINE_WINDOW_DAYS}-gas-day GDSR baseline, measured "
        "in standard deviations. Marker size is fixed. "
        "Click a marker to replace the Alberta-wide panel with "
        "point-specific intraday metrics. Hover pipelines or stations for "
        f"AER attributes. {line_mode_text}"
    )


with legend_col:
    st.markdown(
        '<div class="section-label">Legend</div>',
        unsafe_allow_html=True,
    )
    st.markdown(legend_html, unsafe_allow_html=True)


with system_col:
    selected_interconnect = st.session_state.get("selected_interconnect")

    if selected_interconnect:
        selected = border_points.loc[
            border_points["key"] == selected_interconnect
        ]

        if selected.empty:
            st.session_state["selected_interconnect"] = None
            st.rerun()

        selected = selected.iloc[0]
        snap = snapshots[selected["column"]]

        header_col, reset_col = st.columns([4, 1])

        with header_col:
            # Same glyph and same rotation as the map marker, so the
            # panel and the dot agree at a glance. CSS rotation is
            # clockwise from east while deck.gl's get_angle is
            # counter-clockwise, hence the negation.
            if selected["flow_arrow"]:
                header_arrow = (
                    f'<span class="header-arrow" style="transform:rotate('
                    f'{-selected["flow_angle"]:.0f}deg);" title="'
                    f'{selected["flow_direction_text"]}">'
                    f'{FLOW_ARROW_GLYPH}</span>'
                )
            else:
                header_arrow = ""

            st.markdown(
                f'<div class="section-label">{selected["display_name"]}'
                f'{header_arrow}</div>',
                unsafe_allow_html=True,
            )

        with reset_col:
            if st.button(
                "AB",
                help="Return to Alberta system metrics",
                use_container_width=True,
            ):
                st.session_state["selected_interconnect"] = None
                st.rerun()

        current_text = (
            "—"
            if pd.isna(snap["current"])
            else f"{mmcf_to_bcf(snap['current']):.2f} Bcf/d"
        )
        delta_text = (
            None
            if pd.isna(snap["change"])
            else f"{mmcf_to_bcf(snap['change']):+.2f} vs prior obs."
        )

        st.metric(
            "Current flow",
            current_text,
            delta_text,
        )
        st.caption(
            f"{selected['direction']} · source field: {selected['column']}"
        )

        avg_col1, avg_col2 = st.columns(2)

        with avg_col1:
            st.metric(
                "24h average",
                (
                    "—"
                    if pd.isna(snap["avg24"])
                    else f"{mmcf_to_bcf(snap['avg24']):.2f} Bcf/d"
                ),
            )

        with avg_col2:
            st.metric(
                "7d average",
                (
                    "—"
                    if pd.isna(snap["avg7d"])
                    else f"{mmcf_to_bcf(snap['avg7d']):.2f} Bcf/d"
                ),
            )

        st.markdown(
            f'<div class="legend-row">'
            f'<span class="legend-item">'
            f'<span class="legend-dot" '
            f'style="background:{classify_deviation(selected["z_score"])["hex"]};">'
            f'</span>'
            f'{selected["band_label"]}'
            f'<span class="legend-detail">'
            + (
                f'{selected["z_score"]:+.1f} std dev vs '
                f'{MARKER_BASELINE_WINDOW_DAYS}d'
                if not pd.isna(selected["z_score"])
                else "no baseline yet"
            )
            + '</span></span></div>',
            unsafe_allow_html=True,
        )

        detail_rows = pd.DataFrame(
            {
                "Metric": [
                    "Current",
                    "Prior observation",
                    "24h average",
                    "7d average",
                    f"{MARKER_BASELINE_WINDOW_DAYS}d normal",
                    "vs 24h magnitude",
                    "vs 7d magnitude",
                    f"vs {MARKER_BASELINE_WINDOW_DAYS}d magnitude",
                ],
                "MMcf/d": [
                    snap["current"],
                    snap["previous"],
                    snap["avg24"],
                    snap["avg7d"],
                    selected["base_mean"],
                    snap["vs24_mag"],
                    snap["vs7d_mag"],
                    selected["vs_base_mmcf"],
                ],
            }
        ).set_index("Metric")

        # The comparison rows are banded on the same scale as the
        # deviation bubble above them, rather than on a flat green/red
        # threshold. A difference in MMcf/d is converted to standard
        # deviations of this point's own GDSR baseline and passed
        # through classify_deviation, so a row reading "Below normal"
        # red is the same statement, in the same colour, as the bubble.
        #
        # All three rows are scaled by that one baseline std even though
        # two of them are measured against 24h and 7d means. Using each
        # window's own spread would make the colours incomparable
        # between rows; a common yardstick is the point of banding them.
        RELATIVE_ROWS = {
            "vs 24h magnitude",
            "vs 7d magnitude",
            f"vs {MARKER_BASELINE_WINDOW_DAYS}d magnitude",
        }

        baseline_std = selected["base_std"]

        def colour_relative_rows(row):
            styles = [""] * len(row)

            if row.name not in RELATIVE_ROWS:
                return styles

            value = row.iloc[0]
            if pd.isna(value) or pd.isna(baseline_std) or baseline_std == 0:
                return styles

            band = classify_deviation(value / baseline_std)
            styles[0] = f"color: {band['hex']}; font-weight: 700;"
            return styles

        st.dataframe(
            (
                detail_rows.style
                .format({"MMcf/d": "{:+,.0f}"}, na_rep="—")
                .apply(colour_relative_rows, axis=1)
            ),
            use_container_width=True,
            height=325,
        )

        st.caption(
            "Comparison rows use absolute flow magnitude, banded on the "
            "same scale as the marker above: each difference is measured "
            "in standard deviations of this point's own trailing "
            f"{MARKER_BASELINE_WINDOW_DAYS}-gas-day GDSR baseline. Green "
            "= stronger flow magnitude than normal, red = weaker, with "
            "the deeper shade beyond 2 std dev."
        )

    else:
        st.markdown(
            '<div class="section-label">Alberta system balance</div>',
            unsafe_allow_html=True,
        )

        # First row
        c1, c2 = st.columns(2)

        with c1:
            snap = snapshots["NGTL-Field Receipts"]
            base = alberta_baselines["NGTL-Field Receipts"]
            display_metric(
                "Field Receipts",
                snap,
                "Bcf/d",
                caption=(
                    f"24h {fmt_bcf(snap['avg24'])} · "
                    f"7d {fmt_bcf(snap['avg7d'])}"
                ),
                baseline=base,
            )

        with c2:
            snap = snapshots["Intraprovincial Demand"]
            base = alberta_baselines["Intraprovincial Demand"]
            display_metric(
                "Intraprovincial Demand",
                snap,
                "Bcf/d",
                caption=(
                    f"24h {fmt_bcf(snap['avg24'])} · "
                    f"7d {fmt_bcf(snap['avg7d'])}"
                ),
                baseline=base,
            )

        # Second row
        c1, c2 = st.columns(2)

        with c1:
            snap = snapshots["Total Receipts"]
            base = alberta_baselines["Total Receipts"]
            display_metric(
                "Total Receipts",
                snap,
                "Bcf/d",
                caption=(
                    f"24h {fmt_bcf(snap['avg24'])} · "
                    f"7d {fmt_bcf(snap['avg7d'])}"
                ),
                baseline=base,
            )

        with c2:
            snap = snapshots["Total Deliveries"]
            base = alberta_baselines["Total Deliveries"]
            display_metric(
                "Total Deliveries",
                snap,
                "Bcf/d",
                caption=(
                    f"24h {fmt_bcf(snap['avg24'])} · "
                    f"7d {fmt_bcf(snap['avg7d'])}"
                ),
                baseline=base,
            )

        # Third row
        c1, c2 = st.columns(2)

        with c1:
            snap = snapshots["Net Storage Flow"]
            base = alberta_baselines["Net Storage Flow"]
            display_metric(
                "Net Storage Flow",
                snap,
                "Bcf/d",
                signed=True,
                caption=(
                    f"24h {fmt_bcf(snap['avg24'], signed=True)} · "
                    f"7d {fmt_bcf(snap['avg7d'], signed=True)}"
                ),
                baseline=base,
            )

        with c2:
            snap = snapshots["Flow Differential"]
            base = alberta_baselines["Flow Differential"]
            display_metric(
                "Flow Differential",
                snap,
                "Bcf/d",
                signed=True,
                caption=(
                    f"Receipts minus deliveries · "
                    f"24h {fmt_bcf(snap['avg24'], signed=True)}"
                ),
                baseline=base,
            )

        # Fourth row
        c1, c2 = st.columns(2)

        with c1:
            snap = snapshots["Current Linepack"]
            base = alberta_baselines["Current Linepack"]
            display_metric(
                "Current Linepack",
                snap,
                "Bcf",
                caption=(
                    f"Target {fmt_bcf(snapshots['Linepack Target']['current'])} Bcf"
                ),
                baseline=base,
            )

        with c2:
            display_metric(
                "Linepack vs Target",
                linepack_gap_snap,
                "Bcf",
                signed=True,
                baseline=linepack_gap_baseline,
                caption=(
                    f"4h ROC "
                    f"{fmt_bcf(snapshots['Linepack 4Hr Roc']['current'], signed=True)} Bcf"
                ),
            )

        st.markdown("#### Selected observation")

        rhs_table = pd.DataFrame(
            {
                "Metric": [
                    "Field Receipts",
                    "Intraprovincial Demand",
                    "Total Receipts",
                    "Total Deliveries",
                    "Net Storage Flow",
                    "Flow Differential",
                    "Current Linepack",
                    "Linepack Target",
                    "Linepack 4Hr ROC",
                ],
                "Value": [
                    mmcf_to_bcf(selected_row["NGTL-Field Receipts"]),
                    mmcf_to_bcf(selected_row["Intraprovincial Demand"]),
                    mmcf_to_bcf(selected_row["Total Receipts"]),
                    mmcf_to_bcf(selected_row["Total Deliveries"]),
                    mmcf_to_bcf(selected_row["Net Storage Flow"]),
                    mmcf_to_bcf(selected_row["Flow Differential"]),
                    mmcf_to_bcf(selected_row["Current Linepack"]),
                    mmcf_to_bcf(selected_row["Linepack Target"]),
                    mmcf_to_bcf(selected_row["Linepack 4Hr Roc"]),
                ],
                "Unit": [
                    "Bcf/d",
                    "Bcf/d",
                    "Bcf/d",
                    "Bcf/d",
                    "Bcf/d",
                    "Bcf/d",
                    "Bcf",
                    "Bcf",
                    "Bcf / 4h",
                ],
            }
        ).set_index("Metric")

        st.dataframe(
            rhs_table.style.format({"Value": "{:+.2f}"}, na_rep="—"),
            use_container_width=True,
            height=325,
        )


# ============================================================
# INTRADAY HISTORY
# ============================================================

st.markdown("---")
st.markdown(
    '<div class="section-label">Intraday system history</div>',
    unsafe_allow_html=True,
)

history_window = st.segmented_control(
    "History window",
    options=["24 hours", "3 days", "7 days", "All"],
    default="All",
)

window_hours = {
    "24 hours": 24,
    "3 days": 72,
    "7 days": 168,
    "All": None,
}[history_window]

history = csr.loc[csr["Timestamp"] <= selected_timestamp].copy()

if window_hours is not None:
    history = history.loc[
        history["Timestamp"]
        >= selected_timestamp - pd.Timedelta(hours=window_hours)
    ]

chart_col1, chart_col2 = st.columns(2, gap="large")

with chart_col1:
    st.markdown("#### Linepack")

    linepack_fig = go.Figure()

    linepack_fig.add_trace(
        go.Scatter(
            x=history["Timestamp"],
            y=history["Current Linepack"] / 1000,
            mode="lines",
            name="Current Linepack",
        )
    )

    linepack_fig.update_layout(
        height=390,
        margin=dict(l=10, r=10, t=15, b=10),
        hovermode="x unified",
        yaxis_title="Bcf",
        legend=dict(orientation="h", y=1.03, x=0),
    )

    st.plotly_chart(linepack_fig, use_container_width=True)


with chart_col2:
    st.markdown("#### System receipts and deliveries")

    balance_fig = go.Figure()

    balance_fig.add_trace(
        go.Scatter(
            x=history["Timestamp"],
            y=history["Total Receipts"] / 1000,
            mode="lines",
            name="Total Receipts",
        )
    )

    balance_fig.add_trace(
        go.Scatter(
            x=history["Timestamp"],
            y=history["Total Deliveries"] / 1000,
            mode="lines",
            name="Total Deliveries",
        )
    )

    balance_fig.update_layout(
        height=390,
        margin=dict(l=10, r=10, t=15, b=10),
        hovermode="x unified",
        yaxis_title="Bcf/d",
        legend=dict(orientation="h", y=1.03, x=0),
    )

    st.plotly_chart(balance_fig, use_container_width=True)


# ============================================================
# MAINTENANCE AND CAPACITY
# ============================================================

st.markdown("---")
st.markdown(
    '<div class="section-label">Maintenance and stated capability</div>',
    unsafe_allow_html=True,
)

if outages is None:
    st.info(
        "No outage data loaded. Drop maintenance tracker exports into "
        "`outages/` and run `python3 prepare_outages.py`."
    )
else:
    active = active_outages

    if outage_changes is not None and len(outage_changes):
        latest_pub = outage_changes["published"].max()
        prior_pub = outage_changes["previous_published"].max()
        with st.expander(
            f"What changed since the previous publication "
            f"({len(outage_changes)} change"
            f"{'s' if len(outage_changes) != 1 else ''})",
            expanded=False,
        ):
            st.caption(
                f"Comparing the tracker published {prior_pub:%b %d %H:%M} "
                f"with {latest_pub:%b %d %H:%M}. TC republishes the full "
                "schedule each business day, so this is the change log "
                "they do not publish directly. Everything already on the "
                "calendar is largely priced in; these rows are what moved."
            )

            chips = "".join(
                f'<span class="legend-item">'
                f'<span class="legend-dot" style="background:'
                f'{CHANGE_TONE.get(kind, "#969eac")};"></span>'
                f'{kind}<span class="legend-detail">{count}</span>'
                f'</span>'
                for kind, count in (
                    outage_changes["change"].str.split("|").explode()
                    .value_counts().items()
                )
            )
            st.markdown(
                f'<div class="legend-row">{chips}</div>',
                unsafe_allow_html=True,
            )

            change_table = outage_changes.rename(columns={
                "table_code": "Table", "facility": "Facility",
                "work_type": "Work", "change": "Change", "detail": "Detail",
                "capability_mmcfd": "Capability (MMcf/d)",
                "restriction": "Restriction",
            })
            display_cols = [
                c for c in ["Table", "Facility", "Work", "Change", "Detail",
                            "Capability (MMcf/d)", "Restriction"]
                if c in change_table
            ]
            st.dataframe(
                change_table[display_cols].style.format(
                    {"Capability (MMcf/d)": "{:,.0f}"}, na_rep="—"
                ),
                use_container_width=True,
                hide_index=True,
            )
    elif outage_changes is not None:
        st.caption(
            "No changes between the two most recent tracker publications."
        )
    else:
        st.caption(
            "Publication-over-publication changes not available. Run "
            "`python3 prepare_outage_changes.py` with at least two exports "
            "in `outages/`."
        )

    st.caption(
        f"Outages active on {selected_gas_day:%b %d, %Y} · "
        f"archive covers {outages['gas_day'].min():%b %d} to "
        f"{outages['gas_day'].max():%b %d, %Y}. Capability is published "
        "in 10³m³/d and converted to MMcf/d."
    )

    if active.empty:
        st.success("No maintenance outages listed for this gas day.")
    else:
        # Capability vs measured flow, for the tables CSR can measure.
        measurable = [
            code for code in active["table_code"].unique()
            if code in OUTAGE_TABLE_TO_CSR
        ]

        if measurable:
            cols = st.columns(min(len(measurable), 4))
            for col, code in zip(cols, measurable):
                grp = active.loc[active["table_code"] == code]
                capability = float(grp["capability_mmcfd"].min())
                columns, coverage = OUTAGE_TABLE_TO_CSR[code]
                actual = float(
                    sum(
                        snapshots[c]["current"]
                        for c in columns
                        if not pd.isna(snapshots[c]["current"])
                    )
                )
                headroom = capability - abs(actual)

                with col:
                    st.metric(
                        f"{code} capability",
                        f"{mmcf_to_bcf(capability):.2f} Bcf/d",
                        (
                            f"{mmcf_to_bcf(headroom):+.2f} Bcf/d headroom"
                            if coverage == "exact"
                            else None
                        ),
                        delta_color="normal" if headroom >= 0 else "inverse",
                    )
                    if coverage == "exact":
                        util = (
                            abs(actual) / capability * 100
                            if capability else math.nan
                        )
                        st.caption(
                            f"flowing {mmcf_to_bcf(actual):.2f} Bcf/d · "
                            f"{util:.0f}% utilised"
                        )
                    else:
                        st.caption(
                            f"CSR proxy {mmcf_to_bcf(actual):.2f} Bcf/d · "
                            "partial coverage, not directly comparable"
                        )

            st.caption(
                "Utilisation is only shown for EGAT, where CSR measures the "
                "same flow the capability refers to (Empress plus McNeill). "
                "WGAT, FHZ8 and USJR are marked partial: WGAT also covers "
                "the Alberta/Montana border, which CSR does not report, and "
                "Total Receipts includes volumes downstream of James River, "
                "so a percentage there would be misleading. Delivery areas "
                "and individual receipt/delivery points have no CSR "
                "counterpart at all and appear only in the table below."
            )

        # Impacted segments, named from TC's own segment legend.
        segment_rows = active.loc[
            active["segment_codes"].fillna("").astype(str) != ""
        ]
        if not segment_rows.empty:
            chips = {}
            for row in segment_rows.itertuples():
                nums = str(row.segment_numbers).split("|")
                names = str(row.segment_names).split("|")
                for num, nm in zip(nums, names):
                    key = (num, nm)
                    rank = SEVERITY_RANK.get(row.severity, 0)
                    if rank >= SEVERITY_RANK.get(chips.get(key, "unknown"), 0):
                        chips[key] = row.severity

            html = "".join(
                f'<span class="legend-item">'
                f'<span class="legend-ring" style="border-color:'
                f'{OUTAGE_SEVERITY[sev]["hex"]};"></span>'
                f'Segment {num}'
                f'<span class="legend-detail">{nm}</span>'
                f'</span>'
                for (num, nm), sev in sorted(
                    chips.items(), key=lambda kv: int(kv[0][0])
                )
            )
            st.markdown(
                f'<div class="legend-row">{html}</div>',
                unsafe_allow_html=True,
            )
            st.caption(
                "Segments named in the outage's stated area, decoded "
                "against TC's segment-code legend and coloured by the "
                "severity of the outage citing them. The capacity *area* "
                "each outage affects is shaded on the map above, using "
                "TC's own published polygons. Individual numbered segments "
                "are not drawn: TC publishes no geometry for them, and AER "
                "pipeline data carries no NGTL segment number, so the "
                "corridor boundary would have to be invented."
            )

        outage_table = (
            active[[
                "table_code", "table_label", "facility", "work_type",
                "capability_mmcfd", "severity", "derate_pct",
                "restriction", "start", "end",
            ]]
            .rename(columns={
                "table_code": "Table",
                "table_label": "Capacity table",
                "facility": "Facility",
                "work_type": "Work",
                "capability_mmcfd": "Capability (MMcf/d)",
                "severity": "Severity",
                "derate_pct": "Derate %",
                "restriction": "Restriction",
                "start": "Start",
                "end": "End",
            })
            .sort_values(["Severity", "Table", "Facility"])
        )
        outage_table["Start"] = pd.to_datetime(
            outage_table["Start"]
        ).dt.strftime("%b %d")
        outage_table["End"] = pd.to_datetime(
            outage_table["End"]
        ).dt.strftime("%b %d")

        st.dataframe(
            outage_table.style
            .format(
                {"Capability (MMcf/d)": "{:,.0f}", "Derate %": "{:.1f}%"},
                na_rep="—",
            )
            .map(
                lambda v: (
                    f"color: {OUTAGE_SEVERITY[v]['hex']}; font-weight: 700;"
                    if v in OUTAGE_SEVERITY else ""
                ),
                subset=["Severity"],
            ),
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# METRIC EXPLORER
# ============================================================

st.markdown("---")

explorer_labels = {
    "Field Receipts": "NGTL-Field Receipts",
    "Groundbirch East": "Groundbirch East Receipt",
    "Gordondale": "Gordondale Receipt",
    "Total Receipts": "Total Receipts",
    "Intraprovincial Demand": "Intraprovincial Demand",
    "Empress Border Flow": "Empress Border Flow",
    "McNeill Border Flow": "Mcneil Border Flow",
    "Alberta-BC Border Flow": "Alberta-BC Border Flow",
    "Willow Valley": "Willow Valley Interconnect",
    "Total Deliveries": "Total Deliveries",
    "Current Linepack": "Current Linepack",
    "Linepack 4Hr ROC": "Linepack 4Hr Roc",
    "Net Storage Flow": "Net Storage Flow",
    "Flow Differential": "Flow Differential",
    "Linepack Target": "Linepack Target",
}

# Linepack is a stock in Bcf; everything else is a rate in Bcf/d. With
# multi-select the two can now be picked together, so stocks go on a
# right-hand axis rather than being silently plotted against a scale
# they do not belong to.
STOCK_COLUMNS = {"Current Linepack", "Linepack Target", "Linepack (total)"}

# Series that get the right-hand axis. Only the linepack level, and the
# reason is units rather than scale: everything else on these charts is
# a rate in Bcf/d, while linepack is a stock in Bcf. Keeping the left
# axis purely rates means the bars, Flow Differential and linepack
# change all share one honest scale, and the one quantity measured in
# different units gets its own.
RIGHT_AXIS_COLUMNS = {"Linepack (total)"}

# Explicit palette so a series and its rolling mean share a colour.
# Plotly's default cycle would give the mean the next colour along and
# make two metrics look like four.
# Fallback cycle for series with no assigned colour. Ordered so
# neighbours in the cycle are far apart in hue.
EXPLORER_PALETTE = [
    "#4da3ff", "#ff9e2c", "#40bf76", "#eb7a6a",
    "#b48ce8", "#f2d16b", "#5ad2d2", "#f28cc0",
]

# Fixed colour per series, so a flow keeps its identity between the two
# explorers and between the levels and change views - a colour that
# moves when the selection changes is a colour that carries no meaning.
#
# Built on the Okabe-Ito palette, which is designed to stay distinct
# under all three common types of colour blindness. The pairs that
# matter most here are the ones that sit adjacent in the stack:
# Intraprovincial (vermillion) against Net storage (purple), and Field
# Receipts (green) against Net Interprovincial (blue).
#
# Two deliberate departures from a plain qualitative palette:
#   - Other deliveries is grey, because it is a derived remainder
#     rather than a measured flow, and should not compete for
#     attention with the things that are.
#   - Flow Differential is near-white and heavier, because it is the
#     total rather than a component.
# Each set was chosen by maximising the smallest pairwise CIELAB
# distance within its own chart, evaluated under normal vision and
# under simulated deuteranopia, protanopia and tritanopia at once. The
# first attempt looked fine on screen and fell to a distance of 7 under
# protanopia - two oranges that are obvious to me and identical to
# roughly one man in twelve. The sets below hold above 27 in every case,
# which is why they mix lightness as well as hue rather than being six
# equally bright colours.
SERIES_COLOURS = {
    # system decomposition
    "Field Receipts": "#00a878",           # green - Alberta supply
    "Net Interprovincial": "#6ec6ff",      # light blue - crosses a border
    "Intraprovincial Demand": "#d64550",   # red - burned at home
    "Storage injection": "#0072b2",        # deep blue - gas leaving into storage
    "Storage withdrawal": "#f0e442",       # yellow - gas coming back out
    "Other deliveries": "#8d97a5",         # grey - derived remainder
    "Fuel & unaccounted": "#6b6f7a",       # darker grey - also derived
    "Linepack change": "#f2f4f8",          # near-white - the total
    "Linepack (total)": "#a88add",         # violet - a stock, not a flow
    "Flow Differential": "#ffd166",        # amber - receipts minus deliveries
    "Flow Differential change": "#c8952b",  # darker amber - its move
    # interprovincial points
    "Empress Border Flow": "#f0a13c",
    "Mcneil Border Flow": "#a0522d",
    "Alberta-BC Border Flow": "#0072b2",
    "Groundbirch East Receipt": "#00a878",
    "Gordondale Receipt": "#6ec6ff",
    "Willow Valley Interconnect": "#8d97a5",
    "Net Interprovincial (total)": "#f2f4f8",
}


# How much slack to leave on the right axis beyond the data. At 1.0 the
# series fills the plot, which makes a noisy rate look dramatic - a
# 0.2 Bcf/d wobble drawn floor to ceiling reads like a crisis. Above 1
# the axis is wider than it needs to be and the line is damped in
# proportion. 1.7 keeps the shape legible without overstating it.
RIGHT_AXIS_HEADROOM = 1.7

# Padding on the stock axis, as a multiple of the data's own span on
# each side. The series occupies 1/(1+2*pad) of the plot height, so 1.5
# leaves it using about a quarter: enough to read the shape of linepack
# without a 3% wiggle sweeping the full height and drawing the eye away
# from the flows, which are the subject of the chart.
RIGHT_AXIS_STOCK_PAD = 1.5


def _aligned_ranges(
    left: list[float],
    right: list[float],
    pad: float = 0.08,
    headroom: float = RIGHT_AXIS_HEADROOM,
) -> tuple[list[float], list[float]] | None:
    """Ranges for two axes that put zero at the same screen height.

    Two independent autoscaled axes place their zeros wherever they
    like, so a total line can appear above bars it is smaller than, or
    cross zero at a different height than the bars do. Since both axes
    here measure the same units and the zero line carries the meaning -
    gas in above, gas out below - they have to agree on where zero is.
    """
    if not left or not right:
        return None

    lo1, hi1 = min(left), max(left)
    lo2, hi2 = min(right), max(right)

    lo1, hi1 = min(lo1, 0.0), max(hi1, 0.0)
    lo2, hi2 = min(lo2, 0.0), max(hi2, 0.0)

    span1, span2 = hi1 - lo1, hi2 - lo2
    if span1 <= 0 or span2 <= 0:
        return None

    lo1 -= span1 * pad
    hi1 += span1 * pad

    # Fraction of the plot height that sits below zero on the left axis.
    below = -lo1 / (hi1 - lo1)
    if not 0 < below < 1:
        return None

    # Scale the right axis so its zero lands at the same fraction.
    # Multiplying the span by headroom keeps that fraction intact -
    # both edges scale about the same split - while giving the series
    # room, so it moves within the plot rather than across all of it.
    span2 = max(hi2 / (1 - below), -lo2 / below) * (1 + pad) * headroom
    return [lo1, hi1], [-span2 * below, span2 * (1 - below)]


def _translucent(hex_colour: str, alpha: float = 0.42) -> str:
    """Hex to rgba, so a stacked fill keeps its line's colour."""
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def render_metric_explorer(
    title: str,
    labels: dict[str, str],
    default: list[str],
    key: str,
    note: str = "",
    frame: pd.DataFrame | None = None,
    stackable: bool = False,
    line_columns: tuple[str, ...] = (),
    modes: tuple[str, ...] = (
        "Lines", "Stacked area", "Stacked bars (daily)",
    ),
) -> None:
    """Draw one multi-select CSR explorer.

    Shared by both explorers so they cannot drift apart in behaviour -
    only the metric list and defaults differ. ``frame`` allows an
    explorer to plot a prepared table instead of raw CSR.
    """
    source = history if frame is None else frame
    st.markdown(
        f'<div class="section-label">{title}</div>',
        unsafe_allow_html=True,
    )
    if note:
        st.caption(note)

    chosen = st.multiselect(
        "Metrics",
        options=list(labels.keys()),
        default=[d for d in default if d in labels],
        key=f"explorer_{key}",
    )

    if not chosen:
        st.info("Select at least one metric.")
        return

    # Bars are daily because CSR is half-hourly: 734 bars would be
    # sub-pixel slivers. One bar per gas day is the resolution the eye
    # can read a composition at, and it matches how the flows are
    # contracted and settled.
    if not stackable:
        chart_mode = "Lines"
    elif len(modes) == 1:
        # A chart with one sensible view does not need a control.
        chart_mode = modes[0]
    else:
        chart_mode = st.radio(
            "View",
            options=list(modes),
            index=0,
            horizontal=True,
            key=f"explorer_mode_{key}",
            help=(
                "Stacked views fill inflows above zero and outflows "
                "below. Bars average each gas day, which reads more "
                "cleanly than half-hourly fills."
            ),
        )

    stacked = chart_mode != "Lines"

    # Anything that is not an explicit line or area view draws as bars.
    # Written as an exclusion rather than a list of bar-mode names: an
    # earlier version tested for the mode labels and silently fell back
    # to an area chart when one of them was renamed.
    as_bars = chart_mode not in ("Lines", "Stacked area")

    # Clustered draws each flow as its own bar side by side rather than
    # summed into a band. Nothing is added together, so a bar's height
    # is that flow's own size and the sides of zero still mean gas in
    # and gas out. The total then has to move to its own axis: it is
    # ~2% of the components, and on a shared scale it is a flat line.
    as_clustered = chart_mode.startswith("Clustered")

    # Levels answer "how big is each flow"; changes answer "what moved
    # the total". They are different questions and the second is the one
    # a small residual like Flow Differential is actually asking - in
    # levels it is 2.5% of the gas on the chart and unreadable, while
    # its period-over-period change is the same size as the changes in
    # the components that drive it.
    as_change = chart_mode.startswith("What changed")

    control_left, control_right = st.columns(2)

    # Bar interval. CSR publishes about every 30 minutes, so "30 min"
    # is the raw feed with no aggregation - the finest the source
    # supports. Coarser intervals average, which is correct for rates.
    bar_freq, bar_freq_label = "D", "gas day"
    if as_bars:
        with control_right:
            bar_choice = st.selectbox(
                "Bar interval",
                options=["30 min (raw)", "2 hours", "6 hours", "1 day"],
                index=0,
                key=f"explorer_freq_{key}",
                help=(
                    "Finer intervals show intraday shape - nomination "
                    "cycles, storage swings - at the cost of bar width. "
                    "Over a long span the bars become hairlines; zoom "
                    "the chart to read them."
                ),
            )
        bar_freq, bar_freq_label = {
            "30 min (raw)": ("30min", "30 min"),
            "2 hours": ("2h", "2 h"),
            "6 hours": ("6h", "6 h"),
            "1 day": ("D", "gas day"),
        }[bar_choice]

    with control_left:
        show_mean = st.checkbox(
            f"Show {ALBERTA_BASELINE_WINDOW_DAYS}-day rolling mean",
            value=len(chosen) == 1 and not stacked,
            key=f"explorer_mean_{key}",
            disabled=stacked,
            help=(
                "Dashed line per metric, in the same colour. Busy with "
                "several metrics selected, and unreadable over a stack."
            ),
        )

    show_mean = show_mean and not stacked

    columns = [labels[c] for c in chosen]
    has_rate = any(c not in STOCK_COLUMNS for c in columns)
    has_stock = any(c in STOCK_COLUMNS for c in columns)

    fig = go.Figure()
    left_values: list[float] = []
    right_values: list[float] = []

    # Same window as the Alberta panel's baseline, so the explorer and
    # the deviation bubbles answer the same question. Follows
    # ALBERTA_BASELINE_WINDOW_DAYS, so widening the baseline widens this.
    window = ALBERTA_BASELINE_WINDOW_DAYS * 48

    for i, name in enumerate(chosen):
        column = labels[name]
        if column not in source.columns:
            continue

        series = source[["Timestamp", column]].dropna()
        if series.empty:
            continue

        if as_bars:
            # Mean, not sum: these are rates in MMcf/d, so averaging the
            # interval's observations gives that interval's rate.
            # Summing would multiply by the number of readings.
            series = (
                series.set_index("Timestamp")[column]
                .resample(bar_freq).mean().dropna()
            )
            if as_change:
                # Differencing every series, including the total,
                # preserves the identity: if the levels sum to the
                # total, so do their changes. Each bar is then that
                # component's contribution to the move in the total.
                series = series.diff().dropna()
            series = series.reset_index()

        colour = SERIES_COLOURS.get(
            column, EXPLORER_PALETTE[i % len(EXPLORER_PALETTE)]
        )
        stock = column in STOCK_COLUMNS
        is_line_total = column in line_columns
        # Only rates of change go to the right axis. Everything else -
        # the flows, the net, and the linepack level - shares the left
        # one, because they are all the same order of magnitude:
        # linepack sits near 20.6 and field receipts near 13.9, so they
        # read against each other perfectly well. Linepack *change* is
        # about 0.2, a hundredth of that, and is the one series that
        # genuinely needs its own scale.
        axis = "y2" if column in RIGHT_AXIS_COLUMNS else "y"

        # Stacking rules:
        #  - a net/total series is never stacked, or it would be added
        #    on top of the very components it is the sum of;
        #  - inflows and outflows go in separate stack groups. Plotly
        #    accumulates within a group, so mixing signs in one group
        #    would net them into a single band and lose the split. Two
        #    groups fill upward and downward from zero instead.
        #  - a stock on a second axis is never stacked either.
        # A line column is an aggregate of other series in the same
        # chart, so it is never stacked - doing so would add a total on
        # top of the very parts it sums.
        is_total = column in line_columns
        stack_this = stacked and not is_total and not stock and not as_clustered

        if stack_this:
            group = "inflow" if series[column].mean() >= 0 else "outflow"
        else:
            group = None

        plotted = (series[column] / 1000).tolist()
        (right_values if axis == "y2" else left_values).extend(
            v for v in plotted if v == v
        )

        if as_bars and (stack_this or (as_clustered and not is_total)):
            fig.add_trace(
                go.Bar(
                    x=series["Timestamp"],
                    y=series[column] / 1000,
                    name=f"Δ {name}" if as_change else name,
                    marker=dict(
                        color=_translucent(colour, 0.85),
                        line=dict(width=0),
                    ),
                    yaxis=axis,
                )
            )
        else:
            fig.add_trace(
                go.Scatter(
                    x=series["Timestamp"],
                    y=series[column] / 1000,
                    mode="lines",
                    name=name,
                    line=dict(
                        color=colour,
                        # A total drawn over a stack reads as the
                        # summary line, not as one more component.
                        width=2.8 if (stacked and is_total) else 1.9,
                    ),
                    yaxis=axis,
                    stackgroup=group,
                    fillcolor=(
                        _translucent(colour) if stack_this else None
                    ),
                )
            )

        if show_mean and not stock:
            fig.add_trace(
                go.Scatter(
                    x=series["Timestamp"],
                    y=(
                        series[column]
                        .rolling(
                            window,
                            min_periods=BASELINE_MIN_OBSERVATIONS,
                        )
                        .mean()
                        / 1000
                    ),
                    mode="lines",
                    name=f"{name} · {ALBERTA_BASELINE_WINDOW_DAYS}d mean",
                    line=dict(color=colour, width=1.2, dash="dot"),
                    yaxis=axis,
                    showlegend=len(chosen) == 1,
                    hoverinfo="skip",
                )
            )

    layout = dict(
        height=420,
        margin=dict(l=10, r=10, t=15, b=10),
        hovermode="x unified",
        yaxis_title=(
            ("Δ Bcf/d vs prior " + bar_freq_label)
            if as_change
            else ("Bcf/d" if has_rate else "Bcf")
        ),
        legend=dict(orientation="h", y=1.03, x=0),
    )
    if as_bars:
        # "relative" is what stacks mixed signs correctly: positives
        # accumulate upward and negatives downward from zero. Plain
        # "stack" would net them into one bar and lose the split.
        # Clustered puts them side by side instead, adding nothing.
        layout["barmode"] = "group" if as_clustered else "relative"
        layout["bargap"] = 0.25 if as_clustered else 0.15
        if as_clustered:
            layout["bargroupgap"] = 0.05

    if right_values:
        # The right axis carries a stock, not a rate, so it is NOT
        # zero-aligned with the left. Linepack sits near 20.6 Bcf and
        # never approaches zero; forcing zero onto its axis would
        # squash fifteen days of movement into a flat band at the top.
        # It is scaled to its own range instead, which is why the two
        # axes deliberately do not share a baseline here.
        low, high = min(right_values), max(right_values)
        span = (high - low) or max(abs(high), 1.0) * 0.02
        layout["yaxis2"] = dict(
            title="Bcf (linepack)",
            overlaying="y",
            side="right",
            showgrid=False,
            zeroline=False,
            range=[
                low - span * RIGHT_AXIS_STOCK_PAD,
                high + span * RIGHT_AXIS_STOCK_PAD,
            ],
        )

    fig.update_layout(**layout)
    st.plotly_chart(fig, use_container_width=True, key=f"chart_{key}")

    if as_bars:
        bar_count = (
            source.set_index("Timestamp")
            .resample(bar_freq).size().gt(0).sum()
        )
        crowded = (
            " — narrow at this span, drag on the chart to zoom into a "
            "few days"
            if bar_count > 120
            else ""
        )
        if as_change:
            st.caption(
                f"{bar_count} bars, one per {bar_freq_label}. Each "
                "segment is that flow's change from the previous "
                "period, so the segments add up to the change in the "
                f"total line{crowded}."
            )
        else:
            st.caption(
                f"{bar_count} bars, one per {bar_freq_label}, each the "
                f"mean rate over that interval{crowded}."
            )


# ---- system flow decomposition -----------------------------
# Every component of the system balance, each counted exactly once.
#
# The aggregates (Total Receipts, Total Deliveries) are deliberately
# absent: they are sums of the components below and stacking them
# alongside would double the system. Verified against the archive:
#
#   Total Receipts  = Field + Groundbirch East + Gordondale
#                     (mean absolute residual 36 MMcf/d, ~0.25%)
#   Flow Differential = Total Receipts - Total Deliveries  (exact)
#
# Total Deliveries has no published breakdown that closes, so two
# components are derived rather than read:
#
#   Net storage - Net Storage Flow as published. Its own sign already
#     carries the role: negative is gas leaving into storage, which is
#     a delivery; positive is gas returning, which is a receipt. What
#     confirmed it belongs in the delivery side is a correlation
#     between the unexplained delivery term and Net Storage Flow of
#     -0.968, which is what identified it.
#   Other deliveries - what remains of Total Deliveries after the named
#     points and storage injections. It runs 377-1,113 MMcf/d, never
#     negative, and is presumed to be the "Other Borders" that GDSR
#     publishes and CSR does not. Named for what it is, not guessed at.
#
# The components sum to Flow Differential to within 36 MMcf/d on
# average, so the stack closes.
DECOMPOSITION_TOTAL = "Linepack change"
DECOMP_NET_INTERPROV = "Net Interprovincial"
LINEPACK_LEVEL = "Linepack (total)"
FLOW_DIFFERENTIAL = "Flow Differential"
FLOW_DIFFERENTIAL_CHANGE = "Flow Differential change"


def build_decomposition_frame() -> pd.DataFrame:
    """Non-overlapping components of the CSR system balance."""
    frame = history[["Timestamp"]].copy()

    net_storage = history["Net Storage Flow"]
    injection = (-net_storage).clip(lower=0)
    withdrawal = net_storage.clip(lower=0)

    named_deliveries = (
        history["Intraprovincial Demand"]
        + history["Empress Border Flow"]
        + history["Mcneil Border Flow"]
        + history["Alberta-BC Border Flow"]
        + history["Willow Valley Interconnect"]
    )
    other = history["Total Deliveries"] - named_deliveries - injection

    # Receipts positive, deliveries negative, so the stack fills up and
    # down from zero and the two sides read against each other.
    #
    # The six border points are collapsed into one net segment rather
    # than shown individually: this chart is the system balance, and the
    # individual interconnects have their own explorer below. Net is a
    # legitimate stack segment here because the parts are NOT separately
    # on the chart - it is the only place those flows are counted.
    frame["Field Receipts"] = history["NGTL-Field Receipts"]
    frame[DECOMP_NET_INTERPROV] = (
        history["Groundbirch East Receipt"]
        + history["Gordondale Receipt"]
        - history["Empress Border Flow"]
        - history["Mcneil Border Flow"]
        - history["Alberta-BC Border Flow"]
        - history["Willow Valley Interconnect"]
    )
    frame["Intraprovincial Demand"] = -history["Intraprovincial Demand"]
    # Storage split by the sign of Net Storage Flow and named for what
    # each direction is, rather than left as one series called "net".
    # Negative flow is gas going into storage - an injection, and a
    # delivery, so it sits below the line. Positive is gas coming back
    # out - a withdrawal, a receipt, above the line.
    #
    # The two are exclusive by construction and sum to Net Storage Flow,
    # so the balance is unchanged: this is naming and colour, not
    # arithmetic. Worth the second legend entry because injection and
    # withdrawal are different market events - one competes with
    # exports for supply, the other adds to it - and a single signed
    # series makes the switch between them easy to miss.
    frame["Storage injection"] = -injection
    frame["Storage withdrawal"] = withdrawal
    frame["Other deliveries"] = -other

    # ---- closing the balance on linepack --------------------
    # Flow Differential is receipts minus deliveries, so it ought to be
    # the rate linepack accumulates. Measured against the archive it is
    # not: it runs about 318 MMcf/d above the actual rate of change,
    # 2.2% of receipts, steadily and in one direction.
    #
    # That is gas which leaves the system without being a delivery -
    # compressor fuel, plus lost-and-unaccounted-for. CSR does not
    # publish it. Leaving it out meant the stack summed to a number the
    # pipe never saw, so it is carried explicitly as a segment and the
    # total becomes the linepack change itself.
    #
    # The rate is differenced at raw cadence and then averaged like
    # every other series, so it aggregates the same way at any bar
    # interval.
    elapsed_days = (
        history["Timestamp"].diff().dt.total_seconds() / 86400
    )
    linepack_rate = history["Current Linepack"].diff() / elapsed_days

    # Guard against a stale or duplicated timestamp turning into a
    # division by ~zero and a spike of thousands of MMcf/d.
    linepack_rate = linepack_rate.where(elapsed_days > 0.005)

    fuel_and_unaccounted = history["Flow Differential"] - linepack_rate

    frame["Fuel & unaccounted"] = -fuel_and_unaccounted
    frame[DECOMPOSITION_TOTAL] = linepack_rate
    # The level itself, for context beside the change.
    frame[LINEPACK_LEVEL] = history["Current Linepack"]

    # Flow Differential as published, plus its period-over-period move.
    # Worth having beside linepack change rather than instead of it:
    # the two are the same quantity measured two ways, and the gap
    # between them is the fuel and unaccounted term. Plotting both puts
    # that gap on the chart instead of asking anyone to take it on
    # trust.
    frame[FLOW_DIFFERENTIAL] = history["Flow Differential"]
    frame[FLOW_DIFFERENTIAL_CHANGE] = history["Flow Differential"].diff()

    return frame


decomposition_history = build_decomposition_frame()

decomposition_labels = {
    "Field Receipts": "Field Receipts",
    DECOMP_NET_INTERPROV: DECOMP_NET_INTERPROV,
    "Intraprovincial Demand": "Intraprovincial Demand",
    "Storage injection": "Storage injection",
    "Storage withdrawal": "Storage withdrawal",
    "Fuel & unaccounted": "Fuel & unaccounted",
    "Other deliveries": "Other deliveries",
    DECOMPOSITION_TOTAL: DECOMPOSITION_TOTAL,
    LINEPACK_LEVEL: LINEPACK_LEVEL,
    FLOW_DIFFERENTIAL: FLOW_DIFFERENTIAL,
    FLOW_DIFFERENTIAL_CHANGE: FLOW_DIFFERENTIAL_CHANGE,
}

render_metric_explorer(
    "System flow decomposition",
    decomposition_labels,
    default=[
        "Field Receipts",
        DECOMP_NET_INTERPROV,
        "Intraprovincial Demand",
        "Storage injection",
        "Storage withdrawal",
        "Fuel & unaccounted",
        "Other deliveries",
        DECOMPOSITION_TOTAL,
    ],
    key="decomp",
    frame=decomposition_history,
    stackable=True,
    line_columns=(
        DECOMPOSITION_TOTAL, LINEPACK_LEVEL,
        FLOW_DIFFERENTIAL, FLOW_DIFFERENTIAL_CHANGE,
    ),
    modes=("Flows (levels)",),
    note=(
        "What filled or drained the pipe over each interval. Gas in is "
        "above zero, gas out below — storage injections always below "
        "the line. **Clustered** gives each flow its own bar and moves "
        "the total to the right axis, since it is ~2% of the "
        "components and unreadable on a shared scale; **Flows "
        "(levels)** stacks them so they visibly sum to the total. Fuel & unaccounted is the "
        "gap between receipts-minus-deliveries and the linepack the "
        "pipe really holds, about 2.2% of receipts: compressor fuel "
        "and lost-and-unaccounted-for, which CSR does not publish.  \n"
        "**What changed** is a different question — each flow's move "
        "versus the prior period, signed by which way that move pushed "
        "linepack. There a delivery easing off plots above zero, "
        "because less gas left the pipe. Useful for attributing a "
        "swing, but the bars are movements, not flows."
    ),
)

st.markdown("---")

render_metric_explorer(
    "CSR metric explorer",
    explorer_labels,
    default=["Field Receipts"],
    key="all",
)

st.markdown("---")

# Interprovincial, not intraprovincial: the points where gas crosses a
# provincial boundary. "Intraprovincial Demand" is Alberta-internal
# consumption and is deliberately absent - it is the complement of these
# flows, not one of them.
interprovincial_labels = {
    "Empress Border Flow": "Empress Border Flow",
    "McNeill Border Flow": "Mcneil Border Flow",
    "Alberta-BC Border Flow": "Alberta-BC Border Flow",
    "Groundbirch East": "Groundbirch East Receipt",
    "Gordondale": "Gordondale Receipt",
    "Willow Valley": "Willow Valley Interconnect",
}

# ---- signing the interprovincial series --------------------
# CSR publishes these unsigned, so the sign has to come from GDSR, which
# signs positive into NGTL and negative out of it. Each CSR observation
# is signed by the GDSR reading for the gas day it falls in.
#
# Per-day rather than one fixed sign per point: Willow Valley genuinely
# reverses, and hardcoding a direction would misreport exactly the days
# worth noticing. Where GDSR has no reading for a day the point's most
# common historical sign is used, so a gap degrades to that point's
# usual direction rather than dropping the observation.
#
# Gas-day boundary: GDSR is keyed to a gas day and CSR to a wall clock,
# and the two are matched on calendar date here. A reversal is therefore
# placed to within a day, not to the hour.
INTERPROV_GDSR_ITEM = {
    "Empress Border Flow": "EMPRESS",
    "Mcneil Border Flow": "MCNEILL",
    "Alberta-BC Border Flow": "ALBERTA_BC",
    "Groundbirch East Receipt": "GROUNDBIRCH_EAST",
    "Gordondale Receipt": "GORDONDALE",
    "Willow Valley Interconnect": "WILLOW_VALLEY",
}

NET_INTERPROV_LABEL = "Net Interprovincial (total)"


def build_interprovincial_frame() -> pd.DataFrame | None:
    """CSR magnitudes signed by GDSR direction, plus their net."""
    if gdsr_flows is None:
        return None

    frame = history[["Timestamp"]].copy()
    dates = frame["Timestamp"].dt.normalize()

    signed_columns = []
    for column, item in INTERPROV_GDSR_ITEM.items():
        if column not in history.columns:
            continue

        daily = gdsr_flows.loc[gdsr_flows["Item"] == item]
        if daily.empty:
            continue

        by_day = (
            daily.set_index(daily["GasDay"].dt.normalize())[
                "ExtrapolatedMMcfd"
            ]
            .groupby(level=0).last()
        )
        signs = np.sign(by_day).replace(0, np.nan)

        fallback = signs.mode()
        fallback = float(fallback.iloc[0]) if not fallback.empty else 1.0

        frame[column] = (
            history[column].abs()
            * dates.map(signs).fillna(fallback).to_numpy()
        )
        signed_columns.append(column)

    if not signed_columns:
        return None

    # Net is only defined where every leg is present. A partial sum
    # would read as a swing in the balance when it is really a missing
    # reading at one point.
    # Linepack is not an interprovincial flow, but it is the context
    # for one: exports are what drain the pipe. Offered on both charts
    # so either can be read against it.
    elapsed = frame["Timestamp"].diff().dt.total_seconds() / 86400
    frame[DECOMPOSITION_TOTAL] = (
        history["Current Linepack"].diff() / elapsed
    ).where(elapsed > 0.005)
    frame[LINEPACK_LEVEL] = history["Current Linepack"]

    complete = frame[signed_columns].notna().all(axis=1)
    frame[NET_INTERPROV_LABEL] = frame[signed_columns].sum(axis=1)
    frame.loc[~complete, NET_INTERPROV_LABEL] = np.nan

    return frame


interprovincial_history = build_interprovincial_frame()

if interprovincial_history is not None:
    interprovincial_labels[NET_INTERPROV_LABEL] = NET_INTERPROV_LABEL
    interprovincial_labels[DECOMPOSITION_TOTAL] = DECOMPOSITION_TOTAL
    interprovincial_labels[LINEPACK_LEVEL] = LINEPACK_LEVEL

render_metric_explorer(
    "Interprovincial flow explorer",
    interprovincial_labels,
    default=[
        "Empress Border Flow",
        "McNeill Border Flow",
        "Alberta-BC Border Flow",
        "Groundbirch East",
        "Gordondale",
        "Willow Valley",
        NET_INTERPROV_LABEL,
    ],
    key="interprov",
    frame=interprovincial_history,
    stackable=True,
    line_columns=(NET_INTERPROV_LABEL, DECOMPOSITION_TOTAL, LINEPACK_LEVEL),
    # Same view set as the system decomposition, so the two charts
    # behave identically and a mode learned on one carries over.
    modes=("Flows (levels)",),
    note=(
        "All six border-crossing points stacked, with their net drawn "
        "as a line — receipts from BC above zero, exports below. "
        "Positive is into NGTL, negative out: CSR publishes these "
        "unsigned, so the sign comes from GDSR for each gas day — per "
        "day, not fixed, because Willow Valley reverses. The net is the "
        "sum of the six and excludes Other Borders, which CSR does not "
        "report, so it nets the measured points rather than the whole "
        "system."
    ),
)


# ============================================================
# DATA QUALITY / STATUS
# ============================================================

with st.expander("CSR data status"):
    duplicate_count = int(
        csr["Timestamp"].duplicated(keep=False).sum()
    )

    latest_age_minutes = (
        pd.Timestamp.now() - latest_timestamp
    ).total_seconds() / 60

    status_df = pd.DataFrame(
        [
            {
                "Check": "Unique observations",
                "Value": f"{len(csr):,}",
            },
            {
                "Check": "Earliest timestamp",
                "Value": str(earliest_timestamp),
            },
            {
                "Check": "Latest timestamp",
                "Value": str(latest_timestamp),
            },
            {
                "Check": "Latest observation age",
                "Value": f"{latest_age_minutes:.1f} minutes",
            },
            {
                "Check": "Duplicate timestamps after load",
                "Value": duplicate_count,
            },
            {
                "Check": "Feeder file",
                "Value": str(CSR_FILE),
            },
        ]
    )

    st.dataframe(
        status_df,
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "CSR_Master.csv is reloaded automatically when its filesystem "
        "modification time changes. Use Refresh data to force a reload."
    )
