
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import requests
import streamlit as st


# ============================================================
# CONFIG
# ============================================================

PROJECT_ROOT = Path("/Users/willgirling/Desktop/NGTL Project")
FLOW_FILE = PROJECT_ROOT / "processed" / "ngtl_daily_flows.csv"
OPS_FILE = PROJECT_ROOT / "processed" / "ngtl_operational_metrics.csv"

ASSET_DIR = PROJECT_ROOT / "assets"
ALBERTA_GEOJSON_FILE = ASSET_DIR / "alberta_boundary.geojson"
NGTL_PIPELINE_FILE = PROJECT_ROOT / "processed" / "ngtl_operating_pipelines.geojson"

ALBERTA_BOUNDARY_URL = (
    "https://geospatial.alberta.ca/titan/rest/services/"
    "boundary/goa_administrative_area/MapServer/0/query"
)

st.set_page_config(
    page_title="NGTL System Monitor",
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
            max-width: 1680px;
            padding-top: 1.1rem;
            padding-bottom: 2rem;
        }

        .title {
            font-size: 2rem;
            font-weight: 750;
            letter-spacing: -0.03em;
            margin-bottom: 0.1rem;
        }

        .subtitle {
            color: #9da7b4;
            margin-bottom: 0.8rem;
        }

        .metric-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.75rem;
        }

        .metric-card {
            border: 1px solid rgba(255,255,255,0.10);
            background: rgba(25,31,41,0.96);
            border-radius: 12px;
            padding: 0.85rem 0.95rem;
            min-height: 104px;
        }

        .metric-label {
            color: #9da7b4;
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
        }

        .metric-value {
            font-size: 1.45rem;
            font-weight: 750;
            margin-top: 0.12rem;
        }

        .metric-detail {
            color: #aab3bf;
            font-size: 0.77rem;
            line-height: 1.35;
            margin-top: 0.18rem;
        }

        .section-label {
            font-size: 1rem;
            font-weight: 700;
            margin-bottom: 0.4rem;
        }

        .small-note {
            color: #98a2af;
            font-size: 0.75rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# DATA LOADERS
# ============================================================

@st.cache_data(show_spinner=False)
def load_ngtl_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not FLOW_FILE.exists():
        raise FileNotFoundError(f"Missing flow file: {FLOW_FILE}")

    flows = pd.read_csv(FLOW_FILE)
    flows["GasDay"] = pd.to_datetime(flows["GasDay"], errors="coerce")
    flows = flows.dropna(subset=["GasDay"]).copy()

    for col in ["ProratedMMcfd", "ExtrapolatedMMcfd", "NextDayNominatedMMcfd"]:
        if col in flows.columns:
            flows[col] = pd.to_numeric(flows[col], errors="coerce")

    if OPS_FILE.exists():
        ops = pd.read_csv(OPS_FILE)
        ops["GasDay"] = pd.to_datetime(ops["GasDay"], errors="coerce")
        ops["NumericValue"] = pd.to_numeric(ops.get("NumericValue"), errors="coerce")
        ops = ops.dropna(subset=["GasDay"]).copy()
    else:
        ops = pd.DataFrame(
            columns=["GasDay", "Metric", "NumericValue", "TextValue", "SourceFile"]
        )

    return (
        flows.sort_values(["GasDay", "Item"]),
        ops.sort_values(["GasDay", "Metric"]),
    )


def filter_pipeline_geojson_by_diameter(
    geojson: dict | None,
    minimum_diameter_mm: float,
) -> dict | None:
    if not geojson:
        return None

    filtered_features = []
    for feature in geojson.get("features", []):
        properties = feature.get("properties") or {}
        diameter = pd.to_numeric(
            pd.Series([properties.get("OUT_DIAMET")]),
            errors="coerce",
        ).iloc[0]

        if pd.notna(diameter) and float(diameter) >= minimum_diameter_mm:
            filtered_features.append(feature)

    return {
        "type": "FeatureCollection",
        "features": filtered_features,
    }


@st.cache_data(show_spinner=False)
def load_pipeline_geojson() -> dict | None:
    if not NGTL_PIPELINE_FILE.exists():
        return None

    with NGTL_PIPELINE_FILE.open("r", encoding="utf-8") as f:
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


def pipeline_coordinates(geojson: dict | None) -> tuple[list, list]:
    if not geojson:
        return [], []

    lons: list = []
    lats: list = []

    for feature in geojson.get("features", []):
        geometry = feature.get("geometry") or {}
        geom_type = geometry.get("type")
        coordinates = geometry.get("coordinates") or []

        if geom_type == "LineString":
            for lon, lat, *_ in coordinates:
                lons.append(lon)
                lats.append(lat)
            lons.append(None)
            lats.append(None)

        elif geom_type == "MultiLineString":
            for line in coordinates:
                for lon, lat, *_ in line:
                    lons.append(lon)
                    lats.append(lat)
                lons.append(None)
                lats.append(None)

    return lons, lats


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


# ============================================================
# MATCHING AND SERIES HELPERS
# ============================================================

def normalize_label(value: str) -> str:
    value = str(value).upper()
    value = value.replace("&", " AND ")
    value = re.sub(r"^[*]+", "", value)
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def resolve_name(values: pd.Series, candidates: list[str]) -> str | None:
    originals = values.dropna().astype(str).unique().tolist()
    normalized_map = {normalize_label(v): v for v in originals}

    # Exact normalized match.
    for candidate in candidates:
        key = normalize_label(candidate)
        if key in normalized_map:
            return normalized_map[key]

    # Candidate tokens fully contained in the source label.
    for candidate in candidates:
        candidate_tokens = set(normalize_label(candidate).split())
        for normalized, original in normalized_map.items():
            source_tokens = set(normalized.split())
            if candidate_tokens and candidate_tokens.issubset(source_tokens):
                return original

    # Source-label tokens fully contained in the candidate.
    for candidate in candidates:
        candidate_tokens = set(normalize_label(candidate).split())
        for normalized, original in normalized_map.items():
            source_tokens = set(normalized.split())
            if source_tokens and source_tokens.issubset(candidate_tokens):
                return original

    # Final substring fallback for abbreviated AER/TC labels.
    for candidate in candidates:
        key = normalize_label(candidate)
        for normalized, original in normalized_map.items():
            if key in normalized or normalized in key:
                return original

    return None


def empty_datetime_series() -> pd.Series:
    return pd.Series(
        dtype="float64",
        index=pd.DatetimeIndex([], name="GasDay"),
    )


def build_flow_series(
    flows: pd.DataFrame,
    item_name: str | None,
    value_col: str = "ExtrapolatedMMcfd",
) -> pd.Series:
    if not item_name:
        return empty_datetime_series()

    subset = flows.loc[
        flows["Item"].astype(str) == str(item_name),
        ["GasDay", value_col],
    ].copy()

    if subset.empty:
        return empty_datetime_series()

    subset = subset.drop_duplicates("GasDay", keep="last").sort_values("GasDay")
    series = subset.set_index("GasDay")[value_col]
    series.index = pd.DatetimeIndex(series.index)
    return series


def build_ops_series(
    ops: pd.DataFrame,
    metric_name: str | None,
) -> pd.Series:
    if not metric_name:
        return empty_datetime_series()

    subset = ops.loc[
        ops["Metric"].astype(str) == str(metric_name),
        ["GasDay", "NumericValue"],
    ].copy()

    if subset.empty:
        return empty_datetime_series()

    subset = subset.drop_duplicates("GasDay", keep="last").sort_values("GasDay")
    series = subset.set_index("GasDay")["NumericValue"]
    series.index = pd.DatetimeIndex(series.index)
    return series


def value_on(series: pd.Series, day: pd.Timestamp) -> float:
    if series.empty:
        return math.nan

    series = series.copy()
    series.index = pd.DatetimeIndex(series.index).normalize()
    day = pd.Timestamp(day).normalize()

    if day not in series.index:
        return math.nan

    value = series.loc[day]
    return float(value.iloc[-1] if isinstance(value, pd.Series) else value)


def prior_value(series: pd.Series, day: pd.Timestamp) -> float:
    if series.empty:
        return math.nan

    series = series.copy()
    series.index = pd.DatetimeIndex(series.index).normalize()
    earlier = series.loc[series.index < pd.Timestamp(day).normalize()]
    return float(earlier.iloc[-1]) if not earlier.empty else math.nan


def snapshot(series: pd.Series, day: pd.Timestamp) -> dict[str, float]:
    current = value_on(series, day)
    previous = prior_value(series, day)

    history = series.copy()
    history.index = pd.DatetimeIndex(history.index).normalize()
    history = history.loc[history.index <= pd.Timestamp(day).normalize()]

    avg14 = float(history.tail(14).mean()) if not history.empty else math.nan
    avg30 = float(history.tail(30).mean()) if not history.empty else math.nan

    return {
        "current": current,
        "previous": previous,
        "change": current - previous
        if not pd.isna(current) and not pd.isna(previous)
        else math.nan,
        "avg14": avg14,
        "avg30": avg30,
        "vs14": current - avg14
        if not pd.isna(current) and not pd.isna(avg14)
        else math.nan,
        "vs30": current - avg30
        if not pd.isna(current) and not pd.isna(avg30)
        else math.nan,
    }


def mmcf_to_bcf(value: float) -> float:
    return float(value) / 1000.0 if not pd.isna(value) else math.nan


def fmt_bcf(value: float, absolute: bool = False) -> str:
    if pd.isna(value):
        return "—"
    value = mmcf_to_bcf(value)
    if absolute:
        value = abs(value)
    return f"{value:.2f}"


def direction_text(value: float) -> str:
    if pd.isna(value):
        return "No data"
    if value < 0:
        return "Outbound"
    if value > 0:
        return "Inbound"
    return "Flat"


def metric_card(
    label: str,
    snap: dict[str, float],
    unit: str = "Bcf/d",
    absolute: bool = False,
    direction: bool = False,
) -> str:
    current = fmt_bcf(snap["current"], absolute=absolute)
    change = (
        "—"
        if pd.isna(snap["change"])
        else f"{mmcf_to_bcf(snap['change']):+.2f}"
    )
    avg14 = fmt_bcf(snap["avg14"], absolute=absolute)
    avg30 = fmt_bcf(snap["avg30"], absolute=absolute)

    direction_line = (
        f"{direction_text(snap['current'])} · "
        if direction
        else ""
    )

    return f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{current} {unit}</div>
        <div class="metric-detail">
            {direction_line}Δ day: {change}<br>
            14d avg: {avg14} · 30d avg: {avg30}
        </div>
    </div>
    """


# ============================================================
# APP
# ============================================================

try:
    flows, ops = load_ngtl_data()
    alberta_geojson = load_alberta_geojson()
    ngtl_pipeline_geojson = load_pipeline_geojson()
except Exception as exc:
    st.error(str(exc))
    st.stop()

available_days = sorted(flows["GasDay"].dt.normalize().unique())
if not available_days:
    st.error("No valid gas days were found.")
    st.stop()

st.markdown('<div class="title">NGTL System Monitor</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="subtitle">Border flows, Alberta demand, storage and linepack</div>',
    unsafe_allow_html=True,
)

selected_day = st.select_slider(
    "Gas Day",
    options=available_days,
    value=available_days[-1],
    format_func=lambda x: pd.Timestamp(x).strftime("%b %d, %Y"),
)
selected_day = pd.Timestamp(selected_day).normalize()

flow_candidates = {
    "Empress": [
        "EMPRESS BORDER",
        "EMPRESS",
    ],
    "McNeill": [
        "MCNEILL BORDER",
        "MCNEILL",
        "MC NEILL BORDER",
    ],
    "Alberta–BC": [
        "ALBERTA-B.C. BDR",
        "ALBERTA BC BORDER",
        "ALBERTA B C BORDER",
        "AB BC BORDER",
    ],
    "Gordondale": [
        "GORDONDALE BORDER",
        "GORDONDALE",
        "GORDONDALE INTERCONNECT",
    ],
    "Groundbirch East": [
        "GROUNDBIRCH EAST",
        "GROUND BIRCH EAST",
        "GROUNDBIRCH",
    ],
    "Willow Valley": [
        "WILLOW VALLEY INTERCONNECT",
        "WILLOW VALLEY",
    ],
    "Intraprovincial": ["INTRAPROVINCIAL"],
    "Net Storage": ["TOTAL NET STORAGE"],
    "Total Deliveries": ["TOTAL NGTL DELIVERIES"],
    "Total Receipts": ["TOTAL NGTL RECEIPTS"],
}

ops_candidates = {
    "Field Receipts": ["NGTL FIELD RECEIPTS", "FIELD RECEIPTS"],
    "Linepack": ["END OF DAY LINEPACK"],
    "Linepack Target": ["LINEPACK TARGET"],
}

resolved_flow_names = {
    label: resolve_name(flows["Item"], candidates)
    for label, candidates in flow_candidates.items()
}
resolved_ops_names = {
    label: resolve_name(ops["Metric"], candidates)
    for label, candidates in ops_candidates.items()
}

flow_series = {
    label: build_flow_series(flows, resolved_name)
    for label, resolved_name in resolved_flow_names.items()
}
ops_series = {
    label: build_ops_series(ops, resolved_name)
    for label, resolved_name in resolved_ops_names.items()
}

flow_snaps = {
    label: snapshot(series, selected_day)
    for label, series in flow_series.items()
}
ops_snaps = {
    label: snapshot(series, selected_day)
    for label, series in ops_series.items()
}

# Approximate points for visual placement. These can be refined later.
border_points = pd.DataFrame(
    [
        # Northwest Alberta / northeast BC interconnect area
        {
            "label": "Gordondale",
            "display_name": "Gordondale Border",
            "lat": 55.80,
            "lon": -119.98,
            "label_side": "below",
        },
        {
            "label": "Groundbirch East",
            "display_name": "Groundbirch East",
            "lat": 55.78,
            "lon": -120.62,
            "label_side": "above",
        },
        {
            "label": "Willow Valley",
            "display_name": "Willow Valley Interconnect",
            "lat": 55.66,
            "lon": -120.55,
            "label_side": "below",
        },

        # Southern Alberta–BC export corridor near Crowsnest Pass
        {
            "label": "Alberta–BC",
            "display_name": "Alberta–BC Border",
            "lat": 49.63,
            "lon": -114.69,
            "label_side": "above",
        },

        # Eastern export corridor into Saskatchewan
        {
            "label": "Empress",
            "display_name": "Empress Border",
            "lat": 50.95,
            "lon": -110.01,
            "label_side": "above",
        },
        {
            "label": "McNeill",
            "display_name": "McNeill Border",
            "lat": 50.66,
            "lon": -110.02,
            "label_side": "below",
        },
    ]
)

for col in ["current", "avg14", "avg30", "change"]:
    border_points[col] = border_points["label"].map(
        lambda x: flow_snaps[x][col]
    )

selected_flow_rows = flows.loc[
    flows["GasDay"].dt.normalize() == selected_day
].copy()

def selected_flow_value(label: str, column: str) -> float:
    source_name = resolved_flow_names.get(label)
    if not source_name:
        return math.nan

    source_key = normalize_label(source_name)
    item_keys = selected_flow_rows["Item"].astype(str).map(normalize_label)

    values = selected_flow_rows.loc[
        item_keys == source_key,
        column,
    ]

    if values.empty:
        values = selected_flow_rows.loc[
            item_keys.str.contains(source_key, regex=False, na=False)
            | pd.Series(
                [source_key in key for key in item_keys],
                index=item_keys.index,
            ),
            column,
        ]

    return float(values.iloc[-1]) if not values.empty else math.nan


border_points["prorated"] = border_points["label"].map(
    lambda x: selected_flow_value(x, "ProratedMMcfd")
)
border_points["nominated"] = border_points["label"].map(
    lambda x: selected_flow_value(x, "NextDayNominatedMMcfd")
)

border_points["current_bcf_abs"] = border_points["current"].map(
    lambda x: abs(mmcf_to_bcf(x)) if not pd.isna(x) else math.nan
)
border_points["direction"] = border_points["current"].map(direction_text)
border_points["marker_size"] = border_points["current_bcf_abs"].fillna(0).map(
    lambda x: max(5, min(13, 4.5 + x * 1.6))
)


pipeline_control_col1, pipeline_control_col2 = st.columns([1, 1])

with pipeline_control_col1:
    show_ngtl_pipelines = st.checkbox(
        "Show NGTL pipelines",
        value=True,
        help="Operating natural-gas pipeline segments licensed to NOVA Gas Transmission Ltd.",
    )

with pipeline_control_col2:
    main_lines_only = st.checkbox(
        "Main transmission lines only",
        value=False,
        help=(
            "Hide smaller-diameter branches and gathering-style offshoots. "
            "This first version treats lines 600 mm and larger as main transmission."
        ),
    )

display_pipeline_geojson = ngtl_pipeline_geojson
if main_lines_only:
    display_pipeline_geojson = filter_pipeline_geojson_by_diameter(
        ngtl_pipeline_geojson,
        minimum_diameter_mm=600,
    )

map_layers = []

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
            get_line_color=[77, 163, 255, 170],
            highlight_color=[255, 209, 102, 255],
            line_width_min_pixels=1.2,
        )
    )

def tooltip_mmcf(value: float, absolute: bool = False) -> str:
    if pd.isna(value):
        return "—"
    converted = float(value)
    if absolute:
        converted = abs(converted)
    return f"{converted:,.0f}"


def relative_status(row: pd.Series, threshold_mmcf: float = 100.0) -> str:
    if pd.isna(row["current"]) or pd.isna(row["avg14"]) or pd.isna(row["avg30"]):
        return "neutral"

    current_mag = abs(float(row["current"]))
    diff14 = current_mag - abs(float(row["avg14"]))
    diff30 = current_mag - abs(float(row["avg30"]))

    if diff14 > threshold_mmcf and diff30 > threshold_mmcf:
        return "above"
    if diff14 < -threshold_mmcf and diff30 < -threshold_mmcf:
        return "below"
    if abs(diff14) <= threshold_mmcf and abs(diff30) <= threshold_mmcf:
        return "neutral"
    return "mixed"


STATUS_COLOURS = {
    "above": [70, 190, 120, 255],
    "below": [230, 92, 92, 255],
    "mixed": [235, 177, 74, 255],
    "neutral": [150, 160, 175, 255],
}


# Fixed callout positions around the map. These are presentation anchors,
# not facility coordinates.
callout_positions = {
    "Gordondale": {"callout_lon": -121.25, "callout_lat": 56.35},
    "Groundbirch East": {"callout_lon": -122.20, "callout_lat": 55.45},
    "Willow Valley": {"callout_lon": -121.55, "callout_lat": 54.65},
    "Alberta–BC": {"callout_lon": -116.10, "callout_lat": 49.25},
    "Empress": {"callout_lon": -108.75, "callout_lat": 51.35},
    "McNeill": {"callout_lon": -108.75, "callout_lat": 50.15},
}

for label, position in callout_positions.items():
    mask = border_points["label"] == label
    border_points.loc[mask, "callout_lon"] = position["callout_lon"]
    border_points.loc[mask, "callout_lat"] = position["callout_lat"]

border_points["status"] = border_points.apply(relative_status, axis=1)
border_points["status_colour"] = border_points["status"].map(STATUS_COLOURS)

def status_hex(status: str) -> str:
    return {
        "above": "#46be78",
        "below": "#e65c5c",
        "mixed": "#ebb14a",
        "neutral": "#969faf",
    }.get(status, "#969faf")


# Tighter, deliberately spaced anchors around the Alberta map.
callout_positions = {
    "Gordondale": {"callout_lon": -121.05, "callout_lat": 56.05},
    "Groundbirch East": {"callout_lon": -121.85, "callout_lat": 55.15},
    "Willow Valley": {"callout_lon": -121.15, "callout_lat": 54.35},
    "Alberta–BC": {"callout_lon": -115.95, "callout_lat": 49.22},
    "Empress": {"callout_lon": -108.75, "callout_lat": 51.25},
    "McNeill": {"callout_lon": -108.75, "callout_lat": 50.15},
}

for label, position in callout_positions.items():
    mask = border_points["label"] == label
    border_points.loc[mask, "callout_lon"] = position["callout_lon"]
    border_points.loc[mask, "callout_lat"] = position["callout_lat"]

border_points["status"] = border_points.apply(relative_status, axis=1)
border_points["status_colour"] = border_points["status"].map(STATUS_COLOURS)

border_points["callout_title"] = border_points["display_name"].str.upper()
border_points["callout_body"] = border_points.apply(
    lambda row: (
        f"Current      {tooltip_mmcf(row['current'], absolute=True)} "
        f"{row['direction'].lower()}\n"
        f"Prorated     {tooltip_mmcf(row['prorated'], absolute=True)}\n"
        f"Next nom.    {tooltip_mmcf(row['nominated'], absolute=True)}\n"
        f"14d avg      {tooltip_mmcf(row['avg14'], absolute=True)}\n"
        f"30d avg      {tooltip_mmcf(row['avg30'], absolute=True)}"
    ),
    axis=1,
)

# Small neutral point markers.
map_layers.append(
    pdk.Layer(
        "ScatterplotLayer",
        border_points,
        id="border-points",
        pickable=False,
        get_position="[lon, lat]",
        get_radius="marker_size * 550",
        radius_min_pixels=3,
        radius_max_pixels=8,
        get_fill_color=[245, 247, 250, 240],
        get_line_color=[25, 30, 40, 255],
        line_width_min_pixels=1,
        stroked=True,
    )
)

# Leader lines.
leader_paths = border_points.apply(
    lambda row: {
        "path": [
            [row["lon"], row["lat"]],
            [row["callout_lon"], row["callout_lat"]],
        ]
    },
    axis=1,
).tolist()

map_layers.append(
    pdk.Layer(
        "PathLayer",
        leader_paths,
        id="interconnect-leader-lines",
        get_path="path",
        get_color=[205, 213, 223, 150],
        get_width=1.1,
        width_min_pixels=1,
        width_max_pixels=2,
        pickable=False,
    )
)

# Compact geographic rectangles; intentionally much smaller than V14.
card_width_lon = 1.55
card_height_lat = 0.58

callout_polygons = []
for _, row in border_points.iterrows():
    left = row["callout_lon"] - card_width_lon / 2
    right = row["callout_lon"] + card_width_lon / 2
    bottom = row["callout_lat"] - card_height_lat / 2
    top = row["callout_lat"] + card_height_lat / 2

    callout_polygons.append(
        {
            "polygon": [
                [left, bottom],
                [right, bottom],
                [right, top],
                [left, top],
            ],
            "status_colour": row["status_colour"],
        }
    )

map_layers.append(
    pdk.Layer(
        "PolygonLayer",
        callout_polygons,
        id="interconnect-card-backgrounds",
        get_polygon="polygon",
        filled=True,
        stroked=True,
        get_fill_color=[22, 28, 38, 242],
        get_line_color="status_colour",
        line_width_min_pixels=2.3,
        pickable=False,
    )
)

# Fixed-size, left-aligned title and body.
border_points["title_lon"] = border_points["callout_lon"] - 0.64
border_points["title_lat"] = border_points["callout_lat"] + 0.20
border_points["body_lon"] = border_points["callout_lon"] - 0.64
border_points["body_lat"] = border_points["callout_lat"] + 0.05

map_layers.append(
    pdk.Layer(
        "TextLayer",
        border_points,
        id="interconnect-card-titles",
        get_position="[title_lon, title_lat]",
        get_text="callout_title",
        get_size=16,
        size_units='"pixels"',
        get_color=[250, 252, 255, 255],
        get_text_anchor='"start"',
        get_alignment_baseline='"center"',
        font_family="Arial, Helvetica, sans-serif",
        font_weight=700,
        pickable=False,
    )
)

map_layers.append(
    pdk.Layer(
        "TextLayer",
        border_points,
        id="interconnect-card-bodies",
        get_position="[body_lon, body_lat]",
        get_text="callout_body",
        get_size=14,
        size_units='"pixels"',
        get_color=[235, 239, 244, 255],
        get_text_anchor='"start"',
        get_alignment_baseline='"top"',
        font_family="Menlo, Monaco, monospace",
        line_height=1.25,
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
        <div style="font-size:18px; font-weight:750; margin-bottom:10px;">
            {tooltip_title}
        </div>
        <table style="border-collapse:collapse; width:100%; line-height:1.55;">
            <tr><td style="padding-right:16px; color:#aeb8c5;">Licence / line</td><td>{tooltip_line1}</td></tr>
            <tr><td style="padding-right:16px; color:#aeb8c5;">Diameter</td><td>{tooltip_line2}</td></tr>
            <tr><td style="padding-right:16px; color:#aeb8c5;">Substance</td><td>{tooltip_line3}</td></tr>
            <tr><td style="padding-right:16px; color:#aeb8c5;">Status</td><td>{tooltip_line4}</td></tr>
            <tr><td style="padding-right:16px; color:#aeb8c5;">Length</td><td>{tooltip_line5}</td></tr>
            <tr><td style="padding-right:16px; color:#aeb8c5;">Segment</td><td>{tooltip_line6}</td></tr>
        </table>
        """,
        "style": {
            "backgroundColor": "rgba(18, 22, 30, 0.98)",
            "color": "white",
            "fontSize": "14px",
            "padding": "15px 17px",
            "minWidth": "390px",
            "maxWidth": "460px",
            "border": "3px solid rgba(255,255,255,0.34)",
            "borderRadius": "10px",
            "boxShadow": "0 10px 30px rgba(0,0,0,0.38)",
        },
    },
)

map_col, system_col = st.columns([1.8, 1.0], gap="large")

with map_col:
    st.markdown(
        '<div class="section-label">Border and interconnect flows</div>',
        unsafe_allow_html=True,
    )
    st.pydeck_chart(deck, use_container_width=True, height=650)
    if ngtl_pipeline_geojson is None:
        st.warning(
            "NGTL pipeline layer not found at "
            f"{NGTL_PIPELINE_FILE}"
        )

    line_mode_text = (
        "Main transmission view: operating NGTL lines with diameter ≥600 mm."
        if main_lines_only
        else "Full NGTL view: all operating NGTL natural-gas segments."
    )

    st.caption(
        "Interconnect cards are compact fixed-format callouts. Border "
        "colour compares absolute current flow with the 14-day and 30-day averages: "
        "green = materially above both, red = below both, amber = mixed, grey = "
        f"near recent levels. Hover over pipelines for AER segment attributes. {line_mode_text}"
    )

with system_col:
    st.markdown(
        '<div class="section-label">Alberta system balance</div>',
        unsafe_allow_html=True,
    )

    linepack_snap = ops_snaps["Linepack"]
    linepack_target_snap = ops_snaps["Linepack Target"]
    linepack_gap = {
        "current": (
            linepack_snap["current"] - linepack_target_snap["current"]
            if not pd.isna(linepack_snap["current"])
            and not pd.isna(linepack_target_snap["current"])
            else math.nan
        ),
        "previous": math.nan,
        "change": math.nan,
        "avg14": math.nan,
        "avg30": math.nan,
        "vs14": math.nan,
        "vs30": math.nan,
    }

    system_metrics = [
        ("Field Receipts", ops_snaps["Field Receipts"], "Bcf/d"),
        ("Intraprovincial", flow_snaps["Intraprovincial"], "Bcf/d"),
        ("Total Deliveries", flow_snaps["Total Deliveries"], "Bcf/d"),
        ("Total Receipts", flow_snaps["Total Receipts"], "Bcf/d"),
        ("Net Storage", flow_snaps["Net Storage"], "Bcf/d"),
        ("Linepack vs Target", linepack_gap, "Bcf"),
    ]

    for row_start in range(0, len(system_metrics), 2):
        cols = st.columns(2)
        for col, (label, snap, unit) in zip(
            cols,
            system_metrics[row_start:row_start + 2],
        ):
            current = (
                "—"
                if pd.isna(snap["current"])
                else f"{mmcf_to_bcf(snap['current']):.2f} {unit}"
            )
            delta = (
                None
                if pd.isna(snap.get("change", math.nan))
                else f"{mmcf_to_bcf(snap['change']):+.2f} vs prior day"
            )
            with col:
                st.metric(label, current, delta)
                if unit == "Bcf/d":
                    st.caption(
                        f"14d {fmt_bcf(snap['avg14'])} · "
                        f"30d {fmt_bcf(snap['avg30'])}"
                    )

    st.markdown("#### Selected-day readout")
    readout_rows = []
    for label in [
        "Field Receipts",
        "Intraprovincial",
        "Total Deliveries",
        "Total Receipts",
        "Net Storage",
    ]:
        snap = (
            ops_snaps["Field Receipts"]
            if label == "Field Receipts"
            else flow_snaps[label]
        )
        readout_rows.append(
            {
                "Metric": label,
                "Current": mmcf_to_bcf(snap["current"]),
                "14d": mmcf_to_bcf(snap["avg14"]),
                "30d": mmcf_to_bcf(snap["avg30"]),
            }
        )

    st.dataframe(
        pd.DataFrame(readout_rows).set_index("Metric").style.format(
            "{:.2f}",
            na_rep="—",
        ),
        use_container_width=True,
        height=235,
    )

st.markdown("---")
st.markdown(
    '<div class="section-label">Current versus recent history</div>',
    unsafe_allow_html=True,
)

comparison_rows = []
for label in [
    "Empress",
    "McNeill",
    "Alberta–BC",
    "Gordondale",
    "Groundbirch East",
    "Willow Valley",
    "Intraprovincial",
    "Net Storage",
    "Total Deliveries",
]:
    snap = flow_snaps[label]
    comparison_rows.append(
        {
            "Metric": label,
            "Direction": direction_text(snap["current"]),
            "Current": mmcf_to_bcf(snap["current"]),
            "14d avg": mmcf_to_bcf(snap["avg14"]),
            "30d avg": mmcf_to_bcf(snap["avg30"]),
            "vs 14d": mmcf_to_bcf(snap["vs14"]),
            "vs 30d": mmcf_to_bcf(snap["vs30"]),
        }
    )

comparison_df = pd.DataFrame(comparison_rows).set_index("Metric")

st.dataframe(
    comparison_df.style.format(
        {
            "Current": "{:.2f}",
            "14d avg": "{:.2f}",
            "30d avg": "{:.2f}",
            "vs 14d": "{:+.2f}",
            "vs 30d": "{:+.2f}",
        },
        na_rep="—",
    ),
    use_container_width=True,
)

st.markdown("---")
st.markdown(
    '<div class="section-label">Historical context</div>',
    unsafe_allow_html=True,
)

chart_metric = st.selectbox(
    "Metric",
    [
        "Empress",
        "McNeill",
        "Alberta–BC",
        "Gordondale",
        "Groundbirch East",
        "Willow Valley",
        "Intraprovincial",
        "Net Storage",
        "Total Deliveries",
        "Field Receipts",
    ],
)

chart_series = (
    ops_series["Field Receipts"]
    if chart_metric == "Field Receipts"
    else flow_series[chart_metric]
)

chart_series = chart_series.loc[:selected_day].tail(180).dropna()

history_fig = go.Figure()
history_fig.add_trace(
    go.Scatter(
        x=chart_series.index,
        y=chart_series.values / 1000,
        mode="lines",
        name=chart_metric,
    )
)
history_fig.add_trace(
    go.Scatter(
        x=chart_series.index,
        y=chart_series.rolling(14, min_periods=3).mean() / 1000,
        mode="lines",
        name="14-day average",
    )
)
history_fig.add_trace(
    go.Scatter(
        x=chart_series.index,
        y=chart_series.rolling(30, min_periods=5).mean() / 1000,
        mode="lines",
        name="30-day average",
    )
)

history_fig.update_layout(
    height=400,
    margin=dict(l=10, r=10, t=10, b=10),
    hovermode="x unified",
    yaxis_title="Bcf/d",
    legend=dict(orientation="h", y=1.02, x=0),
)

st.plotly_chart(history_fig, use_container_width=True)

unresolved_interconnects = [
    label
    for label in [
        "Empress",
        "McNeill",
        "Alberta–BC",
        "Gordondale",
        "Groundbirch East",
        "Willow Valley",
    ]
    if resolved_flow_names.get(label) is None
]

if unresolved_interconnects:
    st.warning(
        "No source row was matched for: "
        + ", ".join(unresolved_interconnects)
        + ". Open Source-label diagnostics below to inspect the compiled item names."
    )

with st.expander("Source-label diagnostics"):
    diagnostics = pd.DataFrame(
        [
            {"Dashboard metric": k, "Resolved source label": v}
            for k, v in resolved_flow_names.items()
        ]
        + [
            {"Dashboard metric": k, "Resolved source label": v}
            for k, v in resolved_ops_names.items()
        ]
    )
    st.dataframe(diagnostics, use_container_width=True, hide_index=True)
