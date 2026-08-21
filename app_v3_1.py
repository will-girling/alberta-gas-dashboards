
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
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

    for candidate in candidates:
        key = normalize_label(candidate)
        if key in normalized_map:
            return normalized_map[key]

    for candidate in candidates:
        tokens = set(normalize_label(candidate).split())
        for normalized, original in normalized_map.items():
            if tokens and tokens.issubset(set(normalized.split())):
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
    "Empress": ["EMPRESS BORDER"],
    "McNeill": ["MCNEILL BORDER"],
    "Alberta–BC": ["ALBERTA-B.C. BDR", "ALBERTA BC BORDER"],
    "Gordondale": ["GORDONDALE BORDER"],
    "Groundbirch East": ["GROUNDBIRCH EAST"],
    "Willow Valley": ["WILLOW VALLEY INTERCONNECT"],
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
        {"label": "Gordondale", "lat": 55.82, "lon": -119.95},
        {"label": "Groundbirch East", "lat": 55.78, "lon": -120.62},
        {"label": "Alberta–BC", "lat": 54.40, "lon": -119.95},
        {"label": "Willow Valley", "lat": 54.10, "lon": -120.05},
        {"label": "Empress", "lat": 50.95, "lon": -110.02},
        {"label": "McNeill", "lat": 49.74, "lon": -110.02},
    ]
)

for col in ["current", "avg14", "avg30", "change"]:
    border_points[col] = border_points["label"].map(
        lambda x: flow_snaps[x][col]
    )

border_points["current_bcf_abs"] = border_points["current"].map(
    lambda x: abs(mmcf_to_bcf(x)) if not pd.isna(x) else math.nan
)
border_points["direction"] = border_points["current"].map(direction_text)
border_points["marker_size"] = border_points["current_bcf_abs"].fillna(0).map(
    lambda x: max(15, min(42, 13 + x * 5))
)

fig = go.Figure()

fig.add_trace(
    go.Choroplethmap(
        geojson=alberta_geojson,
        locations=["Alberta"],
        featureidkey="properties.PROV_NAME",
        z=[1],
        showscale=False,
        hoverinfo="skip",
        marker_line_width=1.5,
        marker_line_color="rgba(210,220,232,0.8)",
        colorscale=[
            [0, "rgba(60,72,90,0.45)"],
            [1, "rgba(60,72,90,0.45)"],
        ],
    )
)

fig.add_trace(
    go.Scattermap(
        lat=border_points["lat"],
        lon=border_points["lon"],
        mode="markers+text",
        text=border_points["label"],
        textposition="top center",
        marker=dict(
            size=border_points["marker_size"],
            opacity=0.88,
        ),
        customdata=border_points[
            ["current_bcf_abs", "direction", "avg14", "avg30", "change"]
        ].to_numpy(),
        hovertemplate=(
            "<b>%{text}</b><br>"
            "Current: %{customdata[0]:.2f} Bcf/d<br>"
            "Direction: %{customdata[1]}<br>"
            "14d avg: %{customdata[2]:.0f} MMcf/d<br>"
            "30d avg: %{customdata[3]:.0f} MMcf/d<br>"
            "Day change: %{customdata[4]:+.0f} MMcf/d"
            "<extra></extra>"
        ),
    )
)

fig.update_layout(
    map=dict(
        style="carto-darkmatter",
        center={"lat": 54.8, "lon": -115.0},
        zoom=4.25,
    ),
    margin=dict(l=0, r=0, t=0, b=0),
    height=650,
    showlegend=False,
)

map_col, system_col = st.columns([1.8, 1.0], gap="large")

with map_col:
    st.markdown(
        '<div class="section-label">Border and interconnect flows</div>',
        unsafe_allow_html=True,
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Marker positions are approximate and intended for dashboard layout. "
        "Flow direction follows the source sign convention."
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

    cards_html = (
        '<div class="metric-grid">'
        + metric_card("Field Receipts", ops_snaps["Field Receipts"])
        + metric_card("Intraprovincial", flow_snaps["Intraprovincial"])
        + metric_card("Total Deliveries", flow_snaps["Total Deliveries"])
        + metric_card("Total Receipts", flow_snaps["Total Receipts"])
        + metric_card("Net Storage", flow_snaps["Net Storage"])
        + metric_card("Linepack vs Target", linepack_gap, unit="Bcf")
        + "</div>"
    )
    st.markdown(cards_html, unsafe_allow_html=True)

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
