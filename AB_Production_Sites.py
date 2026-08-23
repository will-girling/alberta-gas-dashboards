"""Alberta production sites — well-level output, operator and product.

Standalone from the NGTL dashboard by design: different data cadence
(monthly and two months behind, versus half-hourly), different question,
and a much larger point count.

Data
----
processed/map/ab_wells_<product>.geojson        wells above threshold
processed/map/ab_well_townships_<product>.geojson   the aggregated tail
processed/map/ab_operators.json                 operator name lookup
processed/map/major_operating_gas_pipelines.geojson   AER gas pipelines

Built by prepare_well_map_layer.py and slim_map_layers.py.

Run
---
    streamlit run AB_Production_Sites.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

import ab_plays

# Resolve relative to this file so the app runs anywhere -
# a laptop, a container, or Streamlit Community Cloud.
PROJECT_ROOT = Path(__file__).resolve().parent
MAP_DIR = PROJECT_ROOT / "processed" / "map"
PRODUCTION = PROJECT_ROOT / "processed" / "ab_well_production_located.parquet"

# Precomputed outputs, used when the parquets are absent. A deployed
# copy ships these (0.7 MB) instead of 241 MB of well-month data; a
# local checkout has the parquets and stays fully interactive.
DEPLOY_DIR = PROJECT_ROOT / "processed" / "deploy"

PIPELINE_FILE = MAP_DIR / "major_operating_gas_pipelines.geojson"
NGTL_FILE = MAP_DIR / "ngtl_operating_pipelines.geojson"

# Gas plants that recover C5+ from the gas stream. This exists because
# the well condensate layer is structurally incomplete: Petrinex books a
# volume at the facility that measures it, so an operator sending raw gas
# to a third-party deep-cut plant has its condensate recorded against the
# plant and never against the well. Well records carry 68,000 b/d for
# Alberta; the real stream is roughly 372,000. These points are where the
# rest is actually recovered. Built by prepare_plant_condensate.py.
PLANT_COND_FILE = MAP_DIR / "ab_plant_condensate.geojson"

# Warm amber against the cool well palette - these are a different kind
# of object (midstream infrastructure, not production) and should not be
# mistaken for a well at a glance.
PLANT_COLOUR = [255, 170, 60, 225]
OPERATOR_FILE = MAP_DIR / "ab_operators.json"
FACILITY_FILE = MAP_DIR / "ab_facilities.json"

# Vintage bands. Horizontal multi-frac drilling took over Alberta gas
# from roughly 2010, so the breaks are chosen to separate that era from
# what came before rather than being evenly spaced.
VINTAGE_BANDS = [
    (2020, "2020 and newer", [16, 216, 132, 235]),
    (2014, "2014-2019", [64, 191, 118, 225]),
    (2008, "2008-2013", [242, 209, 107, 215]),
    (2000, "2000-2007", [235, 122, 106, 215]),
    (0, "Before 2000", [120, 144, 168, 190]),
]

PRODUCTS = {
    "Gas": ("gas", "MMcf/d"),
    "Condensate": ("cond", "bbl/d"),
    "Crude oil": ("crude_oil", "bbl/d"),
    # In-situ SAGD and thermal heavy oil. Mined oil sands are absent:
    # Petrinex withholds facility type OS entirely, so roughly 1.3
    # MMbbl/d from Suncor Base Plant, CNRL Horizon, Imperial Kearl and
    # Syncrude appears nowhere in this data.
    "Bitumen (in-situ)": ("bitumen", "bbl/d"),
}

# Wells are coloured by output against their own distribution rather
# than an absolute scale, because a 20 MMcf/d Montney well and a 0.2
# MMcf/d shallow gas well are both normal for their type. Quantile
# breaks keep every band populated.
OUTPUT_BANDS = [
    {"label": "Top 1%", "colour": [16, 216, 132, 235]},
    {"label": "Top 5%", "colour": [64, 191, 118, 225]},
    {"label": "Top 25%", "colour": [242, 209, 107, 215]},
    {"label": "Rest", "colour": [120, 144, 168, 190]},
]
QUANTILES = [0.99, 0.95, 0.75]

# Distinct hues for the largest operators when colouring by firm.
# Twelve is about the limit before colours stop being tellable apart;
# everything beyond that is deliberately pooled into grey rather than
# given a near-duplicate hue that implies a distinction you cannot see.
OPERATOR_PALETTE = [
    [0, 168, 120, 230], [110, 198, 255, 230], [214, 69, 80, 230],
    [240, 228, 66, 230], [168, 138, 221, 230], [0, 114, 178, 230],
    [230, 159, 0, 230], [90, 210, 210, 230], [244, 122, 182, 230],
    [160, 82, 45, 230], [127, 184, 0, 230], [196, 121, 172, 230],
]
OPERATOR_OTHER = [130, 140, 155, 170]
MAX_OPERATOR_COLOURS = 12

# deck.gl's ScatterplotLayer draws circles only. A TextLayer rendering a
# filled-square glyph is the way to get square markers - same approach
# as the compressor stations on the NGTL map. character_set must be a
# tuple: a list serialises as a JS accessor rather than a literal array
# and the markers render invisible.
SQUARE_GLYPH = "\u25a0"

TOWNSHIP_COLOUR = [96, 186, 232, 150]
PIPELINE_COLOUR = [150, 120, 200, 130]
NGTL_COLOUR = [77, 163, 255, 190]

# A well's symbol scales with the square root of its rate: area then
# reads as volume, which is how the eye compares circles. Linear radius
# would make a 20 MMcf/d well 100x the area of a 0.2 one.
MIN_RADIUS_PX = 2.2
MAX_RADIUS_PX = 22.0

st.set_page_config(
    page_title="Alberta Production Sites",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
        .section-label {
            font-size: 0.78rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #98a2af;
            margin: 0.2rem 0 0.4rem 0;
        }
        /* Two columns using CSS multi-column: entries flow down the
           first and continue in the second, which fills the dead space
           on the right without needing to split the list in Python. */
        .legend-stack {
            column-count: 2;
            column-gap: 1.1rem;
            column-fill: balance;
        }
        .legend-item {
            display: inline-flex;
            align-items: flex-start;
            flex-wrap: wrap;
            color: #dfe6ef;
            font-size: 0.95rem;
            line-height: 1.3;
            margin-bottom: 0.6rem;
            width: 100%;
            /* Stop an entry being split across the column break. */
            break-inside: avoid;
            -webkit-column-break-inside: avoid;
        }
        .legend-dot {
            width: 17px; height: 17px; border-radius: 50%;
            border: 1.5px solid rgba(248,248,252,0.9);
            margin: 2px 0.5rem 0 0; flex: none;
        }
        .legend-square {
            width: 17px; height: 17px; border-radius: 3px;
            border: 1.5px solid rgba(248,248,252,0.9);
            margin: 2px 0.5rem 0 0; flex: none;
        }
        .legend-line {
            width: 20px; height: 4px; border-radius: 2px;
            margin: 8px 0.5rem 0 0; flex: none;
        }
        .legend-detail {
            flex-basis: 100%;
            padding-left: calc(17px + 0.5rem);
            color: #a7b2c0;
            font-size: 0.85rem;
        }
        /* One column when the pane is narrow, or entries get too cramped
           to read. */
        @media (max-width: 640px) {
            .legend-stack { column-count: 1; }
        }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def load_geojson(path: str, mtime_ns: int) -> dict | None:
    del mtime_ns
    file = Path(path)
    if not file.exists():
        return None
    return json.loads(file.read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def load_operators(path: str, mtime_ns: int) -> list[str]:
    del mtime_ns
    file = Path(path)
    if not file.exists():
        return []
    return json.loads(file.read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def load_points(path: str, mtime_ns: int) -> pd.DataFrame:
    """GeoJSON points to a frame, which is what pydeck's layers want."""
    del mtime_ns
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = []
    for feature in data.get("features", []):
        lon, lat = feature["geometry"]["coordinates"][:2]
        rows.append({**feature.get("properties", {}), "lon": lon, "lat": lat})
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def load_history(path: str, mtime_ns: int) -> pd.DataFrame | None:
    """Monthly history, from the parquet or the precomputed rollup."""
    del mtime_ns
    file = Path(path)
    if file.exists():
        return pd.read_parquet(
            file, columns=[
                "production_month", "product_class", "operator",
                "rate_mmcfd", "rate_bbld", "well_id",
            ],
        )

    fallback = DEPLOY_DIR / "monthly_history.csv"
    if fallback.exists():
        return pd.read_csv(fallback)
    return None


def mtime(path: Path) -> int:
    return path.stat().st_mtime_ns if path.exists() else 0


st.markdown(
    '<div class="section-label">Alberta production sites</div>',
    unsafe_allow_html=True,
)

operators = load_operators(str(OPERATOR_FILE), mtime(OPERATOR_FILE))
facilities = load_operators(str(FACILITY_FILE), mtime(FACILITY_FILE))
if not operators:
    st.error(
        "Operator lookup not found. Run prepare_well_map_layer.py first."
    )
    st.stop()

# ---- controls ----------------------------------------------
(
    product_col, play_col, colour_col, operator_col, threshold_col,
    tail_col, pipe_col, ngtl_col,
) = st.columns([0.95, 1.5, 0.95, 1.5, 1.0, 0.8, 0.8, 0.7])

with product_col:
    product_label = st.selectbox("Product", list(PRODUCTS))

with play_col:
    chosen_plays = st.multiselect(
        "Play", options=list(ab_plays.PLAYS),
        default=["Montney (Alberta)", "Deep Basin"],
        help=(
            "Wells binned by bottom-hole location. Approximate — plays "
            "overlap in the subsurface and the Duvernay cannot be "
            "separated from the Deep Basin. Empty shows all."
        ),
    )

with colour_col:
    colour_by = st.selectbox(
        "Colour by",
        ["Output", "Operator", "Operator + output", "Vintage", "Play"],
        index=1,
        help=(
            "Output ranks wells against each other. Operator gives each "
            "of the top firms a hue. Operator + output keeps the hue "
            "and varies its intensity with the well's rate, so you see "
            "who holds what and which of their wells carry it. Vintage "
            "is spud year."
        ),
    )

slug, units = PRODUCTS[product_label]
wells_path = MAP_DIR / f"ab_wells_{slug}.geojson"
tail_path = MAP_DIR / f"ab_well_townships_{slug}.geojson"

if not wells_path.exists():
    st.error(f"{wells_path.name} not found. Run prepare_well_map_layer.py.")
    st.stop()

wells = load_points(str(wells_path), mtime(wells_path)).copy()
wells["operator"] = wells["o"].map(
    lambda i: operators[i] if 0 <= i < len(operators) else "Unknown"
)
if "f" in wells.columns and facilities:
    wells["facility"] = wells["f"].fillna(-1).map(
        lambda i: facilities[int(i)] if 0 <= int(i) < len(facilities) else ""
    )
else:
    wells["facility"] = ""
for optional in ("y", "d"):
    if optional not in wells.columns:
        wells[optional] = pd.NA

wells["play"] = ab_plays.assign(wells)

with operator_col:
    ranked = (
        wells.groupby("operator")["r"].sum().sort_values(ascending=False)
    )
    chosen_operators = st.multiselect(
        "Operator", options=list(ranked.index),
        help="Ranked by output. Empty shows all.",
    )

with threshold_col:
    floor = float(wells["r"].min())
    ceiling = float(wells["r"].quantile(0.999))
    min_rate = st.slider(
        f"Min rate ({units})",
        min_value=round(floor, 2), max_value=round(ceiling, 2),
        value=round(floor, 2),
    )

with tail_col:
    show_tail = st.checkbox("Small wells", value=False,
                            help="Sub-threshold wells, aggregated")
with pipe_col:
    show_pipelines = st.checkbox("Gas pipelines", value=True,
                                 help="All AER operating gas pipelines")
with ngtl_col:
    show_ngtl = st.checkbox("NGTL", value=False)
    show_plants = st.checkbox(
        "C5+ plants", value=False,
        help=(
            "Gas plants by condensate recovered. Where Alberta's C5+ is "
            "actually measured — the well condensate layer misses about "
            "four fifths of it."
        ),
    )

marker_col, size_col, scale_col, _spacer = st.columns([1.0, 1.1, 1.4, 3.0])

with marker_col:
    marker_shape = st.radio(
        "Marker", ["Circle", "Square"], horizontal=True,
        help=(
            "Squares tile more predictably than circles at small sizes "
            "and read better when you are comparing operators side by "
            "side rather than judging magnitude."
        ),
    )

with size_col:
    size_mode = st.radio(
        "Size", ["By output", "Uniform"], horizontal=True,
        help=(
            "Uniform gives every well the same footprint, so colour is "
            "the only variable — the right choice for seeing who holds "
            "what across a play."
        ),
    )

with scale_col:
    marker_px = st.slider(
        "Marker size (px)", 1.0, 14.0,
        3.0, 0.5,
    )

# ---- filtering ---------------------------------------------
filtered = wells[wells["r"] >= min_rate]
if chosen_plays:
    filtered = filtered[filtered["play"].isin(chosen_plays)]
if chosen_operators:
    filtered = filtered[filtered["operator"].isin(chosen_operators)]

if filtered.empty:
    st.warning("No wells match these filters.")
    st.stop()

# Bands are computed on the filtered set, so the colours describe what
# is on screen rather than a distribution that has been filtered away.
breaks = [filtered["r"].quantile(q) for q in QUANTILES]


def band_index(rate: float) -> int:
    for i, edge in enumerate(breaks):
        if rate >= edge:
            return i
    return len(breaks)


def vintage_index(year) -> int:
    if year is None or year != year:
        return len(VINTAGE_BANDS)
    for i, (floor_year, _, _) in enumerate(VINTAGE_BANDS):
        if year >= floor_year:
            return i
    return len(VINTAGE_BANDS)


UNKNOWN_COLOUR = [90, 98, 112, 150]

if colour_by == "Operator + output":
    # Hue carries the firm, intensity carries the rate. Two variables on
    # one channel works here only because the hues are far apart and the
    # intensity ramp is coarse - four steps, not a continuous gradient,
    # which would be unreadable against a dark basemap.
    ranking = filtered.groupby("operator")["r"].sum().sort_values(
        ascending=False
    )
    named = list(ranking.head(MAX_OPERATOR_COLOURS).index)
    lookup = {name: OPERATOR_PALETTE[i] for i, name in enumerate(named)}

    quartile = filtered["r"].rank(pct=True)

    def shade(operator: str, pct: float) -> list[int]:
        base = lookup.get(operator, OPERATOR_OTHER)
        # Lift toward white and raise alpha as the well gets bigger, so
        # a firm's best wells read as its brightest.
        if pct >= 0.99:
            lift, alpha = 0.45, 255
        elif pct >= 0.90:
            lift, alpha = 0.22, 240
        elif pct >= 0.50:
            lift, alpha = 0.0, 215
        else:
            lift, alpha = -0.35, 170
        rgb = [
            int(max(0, min(255, c + (255 - c) * lift if lift > 0
                           else c * (1 + lift))))
            for c in base[:3]
        ]
        return rgb + [alpha]

    filtered = filtered.assign(band=filtered["operator"])
    filtered["colour"] = [
        shade(op, pct)
        for op, pct in zip(filtered["operator"], quartile)
    ]
elif colour_by == "Operator":
    ranking = filtered.groupby("operator")["r"].sum().sort_values(
        ascending=False
    )
    named = list(ranking.head(MAX_OPERATOR_COLOURS).index)
    lookup = {name: OPERATOR_PALETTE[i] for i, name in enumerate(named)}
    filtered = filtered.assign(band=filtered["operator"])
    filtered["colour"] = filtered["operator"].map(
        lambda n: lookup.get(n, OPERATOR_OTHER)
    )
elif colour_by == "Play":
    filtered = filtered.assign(band=filtered["play"])
    filtered["colour"] = filtered["play"].map(
        lambda n: (ab_plays.PLAY_COLOURS.get(n, [140, 148, 162, 180])[:3]
                   + [225])
    )
elif colour_by == "Vintage":
    filtered = filtered.assign(band=filtered["y"].map(vintage_index))
    filtered["colour"] = filtered["band"].map(
        lambda i: VINTAGE_BANDS[i][2] if i < len(VINTAGE_BANDS)
        else UNKNOWN_COLOUR
    )
else:
    filtered = filtered.assign(band=filtered["r"].map(band_index))
    filtered["colour"] = filtered["band"].map(
        lambda i: OUTPUT_BANDS[i]["colour"]
    )

# Uniform gives every well the same footprint so colour carries all the
# information. By output scales on sqrt of rate, so symbol *area* tracks
# volume - linear radius would make a 20 MMcf/d well a hundred times the
# area of a 0.2 one.
peak = float(filtered["r"].max()) or 1.0
if size_mode == "Uniform":
    filtered["radius"] = marker_px
else:
    floor_px = max(marker_px * 0.28, 1.0)
    filtered["radius"] = filtered["r"].map(
        lambda r: floor_px
        + (marker_px * 2.6 - floor_px) * math.sqrt(max(r, 0) / peak)
    )

filtered["tooltip_title"] = filtered["n"].where(
    filtered["n"].astype(bool), filtered["u"]
)
filtered["tooltip_line1"] = (
    filtered["r"].map(lambda r: f"{r:,.2f} {units}")
    + filtered["y"].map(
        lambda y: f" · spud {int(y)}" if y == y and y else ""
    )
    + filtered["d"].map(
        lambda d: f" · {int(d):,} m" if d == d and d else ""
    )
)
filtered["tooltip_line2"] = "Operator: " + filtered["operator"]
filtered["tooltip_line3"] = filtered["facility"].map(
    lambda f: f"Reports to {f}" if f else ""
)
filtered["tooltip_line4"] = "UWI " + filtered["u"].astype(str)
filtered["tooltip_line5"] = filtered.get(
    "m", pd.Series(0, index=filtered.index)
).fillna(0).map(
    lambda v: "Location matched by survey position, not exact well"
    if v else ""
)

# ---- layers ------------------------------------------------
layers: list[pdk.Layer] = []

# Play outlines, under every other layer. Only the selected plays are
# drawn - all nine at once is unreadable and the boxes overlap.
outline_plays = chosen_plays or (
    list(ab_plays.PLAYS) if colour_by == "Play" else []
)
if outline_plays:
    boxes = pd.DataFrame([{
        "polygon": ab_plays.polygon(name),
        "name": name,
        "fill": ab_plays.PLAY_COLOURS.get(name, [140, 148, 162, 45]),
        "tooltip_title": name,
        "tooltip_line1": ab_plays.blurb(name),
        "tooltip_line2": "", "tooltip_line3": "",
        "tooltip_line4": "", "tooltip_line5": "",
    } for name in outline_plays])
    layers.append(pdk.Layer(
        "PolygonLayer", boxes, id="play-boxes",
        pickable=False, stroked=True, filled=True,
        get_polygon="polygon",
        get_fill_color="fill",
        get_line_color=[200, 214, 228, 150],
        line_width_min_pixels=1.2,
    ))

if show_pipelines:
    pipelines = load_geojson(str(PIPELINE_FILE), mtime(PIPELINE_FILE))
    if pipelines:
        layers.append(pdk.Layer(
            "GeoJsonLayer", pipelines, id="gas-pipelines",
            stroked=True, filled=False, pickable=True,
            get_line_color=PIPELINE_COLOUR,
            line_width_min_pixels=1.0,
        ))

if show_ngtl:
    ngtl = load_geojson(str(NGTL_FILE), mtime(NGTL_FILE))
    if ngtl:
        layers.append(pdk.Layer(
            "GeoJsonLayer", ngtl, id="ngtl-pipelines",
            stroked=True, filled=False, pickable=False,
            get_line_color=NGTL_COLOUR,
            line_width_min_pixels=1.8,
        ))

# Drawn last of the context layers so plants sit above the pipelines they
# connect to, but they are added before the wells so a well stays
# clickable where the two overlap - which in the Montney is everywhere.
if show_plants and PLANT_COND_FILE.exists():
    plants = load_points(str(PLANT_COND_FILE), mtime(PLANT_COND_FILE))
    if not plants.empty:
        plants = plants.copy()
        # Square root so area reads as volume, same convention as the
        # wells. Floored so a small plant is still findable.
        peak = float(plants["r"].max()) or 1.0
        plants["radius"] = 6.0 + 26.0 * (plants["r"] / peak) ** 0.5
        plants["tooltip_title"] = plants["n"]
        plants["tooltip_line1"] = plants["r"].map(
            lambda v: f"{v:,.0f} bbl/d C5+ recovered"
        )
        # Labelled "processor" deliberately. Pembina and Keyera top this
        # list and own none of the gas they handle - a viewer reading
        # this as ownership would draw the wrong conclusion entirely.
        plants["tooltip_line2"] = "Processor: " + plants["o"].astype(str)
        plants["tooltip_line3"] = plants["l"].astype(str)
        plants["tooltip_line4"] = plants["t"].map(
            {"GP": "Gas plant", "GS": "Gas gathering system"}
        ).fillna("")
        plants["tooltip_line5"] = "Not attributed to the gas owner"
        layers.append(pdk.Layer(
            "ScatterplotLayer", plants, id="c5-plants",
            get_position=["lon", "lat"],
            get_radius="radius", radius_units="pixels",
            get_fill_color=PLANT_COLOUR,
            get_line_color=[26, 31, 43, 230],
            stroked=True, line_width_min_pixels=1.4,
            pickable=True,
        ))

# Drawn under the wells: it is context for where the tail sits, not the
# subject, and it must never sit on top of a pickable well.
if show_tail and tail_path.exists():
    tail = load_points(str(tail_path), mtime(tail_path))
    if not tail.empty:
        tail = tail.copy()
        tail["radius"] = tail["w"].map(
            lambda n: 3.0 + 9.0 * math.sqrt(min(n, 400) / 400)
        )
        tail["tooltip_title"] = tail["w"].map(lambda n: f"{n:,} small wells")
        tail["tooltip_line1"] = tail["r"].map(
            lambda r: f"{r:,.1f} {units} combined"
        )
        tail["tooltip_line2"] = "Below the single-well display threshold"
        tail["tooltip_line3"] = ""
        tail["tooltip_line4"] = ""
        tail["tooltip_line5"] = ""
        layers.append(pdk.Layer(
            "ScatterplotLayer", tail, id="well-tail",
            pickable=True, get_position="[lon, lat]",
            get_radius="radius", radius_units='"pixels"',
            radius_min_pixels=2, radius_max_pixels=14,
            get_fill_color=TOWNSHIP_COLOUR, stroked=False,
        ))

if marker_shape == "Square":
    # get_size on a TextLayer is the em box, and a filled square glyph
    # fills roughly 70% of it, so scale up to match the circle's
    # apparent size.
    filtered["glyph"] = SQUARE_GLYPH
    layers.append(pdk.Layer(
        "TextLayer", filtered, id="wells",
        pickable=True,
        get_position="[lon, lat]",
        get_text="glyph",
        get_size="radius * 2.9",
        size_units='"pixels"',
        # Must stay a tuple - a list serialises as a JS accessor and the
        # glyphs render invisible.
        character_set=(SQUARE_GLYPH,),
        get_color="colour",
        get_text_anchor='"middle"',
        get_alignment_baseline='"center"',
        font_family="Arial, Helvetica, sans-serif",
        billboard=True,
    ))
else:
    layers.append(pdk.Layer(
        "ScatterplotLayer", filtered, id="wells",
        pickable=True, auto_highlight=True,
        get_position="[lon, lat]",
        get_radius="radius", radius_units='"pixels"',
        radius_min_pixels=1, radius_max_pixels=40,
        get_fill_color="colour",
        stroked=False, opacity=0.85,
    ))

TOOLTIP = {
    "html": (
        "<b>{tooltip_title}</b><br/>{tooltip_line1}<br/>"
        "{tooltip_line2}<br/>{tooltip_line3}<br/>{tooltip_line4}"
        "<br/>{tooltip_line5}"
    ),
    "style": {
        "backgroundColor": "rgba(18,22,30,0.94)",
        "color": "#e8edf5",
        "fontSize": "12px",
    },
}

deck = pdk.Deck(
    layers=layers,
    initial_view_state=pdk.ViewState(
        latitude=54.3, longitude=-115.5, zoom=4.9, bearing=0, pitch=0,
    ),
    map_style="dark",
    tooltip=TOOLTIP,
)

map_col, side_col = st.columns([1.25, 0.75], gap="large")

with map_col:
    st.pydeck_chart(deck, use_container_width=True, height=820)

    # Shown only on the condensate view, where the data is misleading in
    # a way that is invisible from the map itself. Petrinex books volumes
    # at the facility that measures them, so operators who send raw gas
    # to third-party plants show almost no wellhead condensate - ARC
    # reads 84 bbl/MMcf while Ovintiv reads 0.1 in Kakwa, which is a
    # reporting artifact and not a statement about the rock.
    if product_label == "Condensate":
        st.caption(
            "**Field-measured condensate only.** These wells carry "
            "~68,000 b/d against roughly 372,000 b/d of Alberta C5+. "
            "Condensate recovered at third-party gas plants is booked "
            "against the plant, not the well, so operator shares here "
            "reflect who meters their own liquids — not who produces "
            "them. Switch on **C5+ plants** to see where the rest is "
            "recovered."
        )

with side_col:
    st.markdown('<div class="section-label">Legend</div>',
                unsafe_allow_html=True)

    items = []
    if colour_by in ("Operator", "Operator + output"):
        ranking = filtered.groupby("operator")["r"].sum().sort_values(
            ascending=False
        )
        total = ranking.sum()
        for i, (name, value) in enumerate(ranking.head(MAX_OPERATOR_COLOURS).items()):
            colour = OPERATOR_PALETTE[i]
            items.append(
                f'<span class="legend-item">'
                f'<span class="legend-dot" style="background:rgba('
                f'{colour[0]},{colour[1]},{colour[2]},0.95);"></span>'
                f'{name[:30]}'
                f'<span class="legend-detail">{value:,.0f} {units} · '
                f'{value / total * 100:.0f}%</span></span>'
            )
        if colour_by == "Operator + output":
            items.append(
                '<span class="legend-item">'
                '<span class="legend-dot" style="background:linear-gradient('
                '90deg, rgba(110,198,255,0.35), rgba(110,198,255,1));'
                'border-radius:2px;"></span>'
                'Brighter = higher rate'
                '<span class="legend-detail">four steps: top 1%, top 10%, '
                'top half, rest</span></span>'
            )

        rest = ranking.iloc[MAX_OPERATOR_COLOURS:]
        if not rest.empty:
            items.append(
                '<span class="legend-item">'
                f'<span class="legend-dot" style="background:rgba('
                f'{OPERATOR_OTHER[0]},{OPERATOR_OTHER[1]},'
                f'{OPERATOR_OTHER[2]},0.8);"></span>'
                f'{len(rest):,} other operators'
                f'<span class="legend-detail">{rest.sum():,.0f} {units} · '
                f'{rest.sum() / total * 100:.0f}%</span></span>'
            )
    elif colour_by == "Play":
        share = filtered.groupby("play")["r"].sum().sort_values(ascending=False)
        for name, value in share.items():
            colour = ab_plays.PLAY_COLOURS.get(name, [140, 148, 162, 180])
            items.append(
                f'<span class="legend-item">'
                f'<span class="legend-dot" style="background:rgba('
                f'{colour[0]},{colour[1]},{colour[2]},0.95);"></span>'
                f'{name}'
                f'<span class="legend-detail">{value:,.0f} {units}</span>'
                f'</span>'
            )
    elif colour_by == "Vintage":
        present = set(filtered["band"].unique())
        for i, (_, label, colour) in enumerate(VINTAGE_BANDS):
            if i not in present:
                continue
            share = (filtered.loc[filtered["band"] == i, "r"].sum()
                     / filtered["r"].sum() * 100)
            items.append(
                f'<span class="legend-item">'
                f'<span class="legend-dot" style="background:rgba('
                f'{colour[0]},{colour[1]},{colour[2]},0.95);"></span>'
                f'{label}'
                f'<span class="legend-detail">{share:.0f}% of output'
                f'</span></span>'
            )
        if len(VINTAGE_BANDS) in present:
            items.append(
                '<span class="legend-item">'
                '<span class="legend-dot" style="background:rgba('
                '90,98,112,0.9);"></span>Spud date unknown</span>'
            )
    else:
        for i, band in enumerate(OUTPUT_BANDS):
            edge = (
                f"≥ {breaks[i]:,.2f} {units}" if i < len(breaks)
                else f"< {breaks[-1]:,.2f} {units}"
            )
            colour = band["colour"]
            items.append(
                f'<span class="legend-item">'
                f'<span class="legend-dot" style="background:rgba('
                f'{colour[0]},{colour[1]},{colour[2]},0.95);"></span>'
                f'{band["label"]}'
                f'<span class="legend-detail">{edge}</span></span>'
            )

    swatch = "legend-square" if marker_shape == "Square" else "legend-dot"
    items.append(
        '<span class="legend-item">'
        f'<span class="{swatch}" style="background:rgba(200,200,210,0.5);'
        'width:9px;height:9px;margin-top:6px;"></span>'
        + ("Symbol size = output" if size_mode == "By output"
           else "Uniform symbol size")
        + '<span class="legend-detail">'
        + ("area scales with rate" if size_mode == "By output"
           else "colour is the only variable")
        + '</span></span>'
    )

    if show_tail:
        items.append(
            '<span class="legend-item">'
            f'<span class="legend-dot" style="background:rgba('
            f'{TOWNSHIP_COLOUR[0]},{TOWNSHIP_COLOUR[1]},'
            f'{TOWNSHIP_COLOUR[2]},0.7);"></span>'
            'Small wells, aggregated'
            '<span class="legend-detail">sized by well count</span></span>'
        )
    if show_ngtl:
        items.append(
            '<span class="legend-item">'
            f'<span class="legend-line" style="background:rgb('
            f'{NGTL_COLOUR[0]},{NGTL_COLOUR[1]},{NGTL_COLOUR[2]});"></span>'
            'NGTL pipelines</span>'
        )
    if show_pipelines:
        items.append(
            '<span class="legend-item">'
            f'<span class="legend-line" style="background:rgb('
            f'{PIPELINE_COLOUR[0]},{PIPELINE_COLOUR[1]},'
            f'{PIPELINE_COLOUR[2]});"></span>'
            'Other gas pipelines'
            '<span class="legend-detail">AER, operating</span></span>'
        )

    st.markdown(f'<div class="legend-stack">{"".join(items)}</div>',
                unsafe_allow_html=True)

    st.markdown("---")
    st.metric(
        f"{product_label} shown",
        f"{filtered['r'].sum():,.0f} {units}",
        f"{len(filtered):,} wells",
    )

    # One play selected: describe it. More than one: compare them.
    if len(chosen_plays) == 1:
        name = chosen_plays[0]
        st.caption(ab_plays.blurb(name))
        top_share = (
            filtered.groupby("operator")["r"].sum().nlargest(3).sum()
            / filtered["r"].sum() * 100
        )
        c1, c2 = st.columns(2)
        c1.metric("Operators", f"{filtered['operator'].nunique():,}")
        c2.metric("Top 3 share", f"{top_share:.0f}%")
        if filtered["y"].notna().any():
            st.caption(
                f"Median spud year {int(filtered['y'].median())} · "
                f"{int((filtered['y'] >= 2020).sum()):,} wells spudded "
                "2020 or later"
            )
    elif len(chosen_plays) > 1:
        compare = filtered.groupby("play").agg(
            rate=("r", "sum"), wells=("r", "size"),
            operators=("operator", "nunique"),
        ).sort_values("rate", ascending=False)
        compare.columns = [units, "Wells", "Operators"]
        st.dataframe(
            compare.style.format({
                units: "{:,.0f}", "Wells": "{:,.0f}", "Operators": "{:,.0f}",
            }),
            use_container_width=True,
        )

    top = (
        filtered.groupby("operator")["r"].sum()
        .sort_values(ascending=False).head(10)
    )
    st.markdown('<div class="section-label">Top operators</div>',
                unsafe_allow_html=True)
    st.dataframe(
        top.rename(units).to_frame().style.format("{:,.1f}"),
        use_container_width=True, height=330,
    )

# ---- supply analytics --------------------------------------
# The decline, vintage and operator work lives in analyse_ab_supply so
# the same code backs the console output, the spreadsheet and this app.
# Duplicating it would let three answers to one question drift apart.
try:
    from analyse_ab_supply import (
        base_decline, load as load_gas, operator_scorecard,
        vintage_curves, well_age_table, EARLY_MONTHS,
    )
    ANALYTICS = True
except Exception:  # noqa: BLE001 - absent or unreadable is not fatal
    ANALYTICS = False


@st.cache_data(show_spinner=False)
def deployed_tables():
    """Supply analytics read from precomputed CSVs."""
    read = lambda n: pd.read_csv(DEPLOY_DIR / n)   # noqa: E731
    cohorts = read("vintage_summary.csv")
    dropped = str(cohorts.get("dropped_cohorts", pd.Series([""])).iloc[0])
    cohorts.attrs["dropped_cohorts"] = [
        int(d) for d in dropped.split(",") if d.strip().isdigit()
    ]
    board = read("operators.csv").set_index("operator")
    return (
        read("base_decline.csv"), read("vintage_curves.csv"),
        cohorts, board, read("vintage_by_floor.csv"),
    )


@st.cache_data(show_spinner="Building supply analytics…")
def supply_tables(mtime_ns: int):
    """Base decline, vintage curves and the operator board.

    Cached on the parquet's mtime: this reads about 7.4 million
    well-months and is far too slow to repeat on every widget change.
    """
    del mtime_ns
    frame = load_gas()
    aged = well_age_table(frame)
    curve, cohorts = vintage_curves(aged)
    return (
        base_decline(frame),
        curve,
        cohorts,
        operator_scorecard(frame, aged),
        aged,
    )


gas_parquet = PROJECT_ROOT / "processed" / "ab_well_production.parquet"
have_parquet = ANALYTICS and gas_parquet.exists()
have_deploy = (DEPLOY_DIR / "base_decline.csv").exists()

if have_parquet or have_deploy:
    st.markdown("---")
    st.markdown('<div class="section-label">Supply analytics</div>',
                unsafe_allow_html=True)

    if have_parquet:
        decline, curve, cohorts, board, aged = supply_tables(mtime(gas_parquet))
        floor_table = None
    else:
        decline, curve, cohorts, board, floor_table = deployed_tables()
        aged = None
        st.caption(
            "Running on precomputed tables — the underlying well-month "
            "data is too large to deploy. Figures are identical; the "
            "rate floor below snaps to preset values."
        )

    tab_decline, tab_vintage, tab_operators = st.tabs(
        ["Base decline", "Well vintage", "Operators"]
    )

    with tab_decline:
        if decline.empty:
            st.info(
                "Needs at least 13 months of history. Run "
                "download_petrinex_volumes.py --months 60."
            )
        else:
            latest = decline.iloc[-1]
            lost = latest["base_a_year_ago"] - latest["same_wells_now"]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Base decline", f"{latest['decline_pct']:.1f}%",
                      "year over year")
            c2.metric("Volume lost to decline", f"{lost:,.0f} MMcf/d")
            c3.metric("New-well supply",
                      f"{latest['new_well_supply']:,.0f} MMcf/d",
                      f"{latest['new_well_supply'] - lost:+,.0f} net")
            c4.metric("Wells still on",
                      f"{latest['of_those_still_on']:,}",
                      f"of {latest['wells_a_year_ago']:,} a year ago")

            chart = decline.set_index("month")[
                ["base_a_year_ago", "same_wells_now", "total_now"]
            ].rename(columns={
                "base_a_year_ago": "The base, a year earlier",
                "same_wells_now": "Those same wells now",
                "total_now": "Total production",
            })
            st.line_chart(chart, height=300)
            st.caption(
                "The gap between the top two lines is what decline took "
                "out; the distance from there up to total production is "
                "what new wells put back. Decline is measured on the "
                "same wells year over year and includes shut-ins, "
                "because a shut-in barrel is lost the same as a "
                "depleted one."
            )
            st.dataframe(
                decline.set_index("month").style.format("{:,.0f}", subset=[
                    c for c in decline.columns if c != "month"
                ]),
                use_container_width=True, height=240,
            )

    with tab_vintage:
        if cohorts.empty:
            st.info("Not enough history for cohort comparison.")
        else:
            dropped = cohorts.attrs.get("dropped_cohorts") or []
            if dropped:
                st.caption(
                    f"Cohort {dropped} excluded — those wells were "
                    "already producing when the archive opens, so their "
                    "early life is not observed."
                )

            floor = st.slider(
                "Only wells that ever exceed (MMcf/d)",
                0.0, 3.0, 1.0, 0.25,
                help=(
                    "84% of Alberta gas wells are under 0.1 MMcf/d. A "
                    "median across all of them moves on well mix rather "
                    "than performance, so a floor isolates the modern "
                    "horizontal population."
                ),
            )

            if aged is not None:
                peaks = aged.groupby("well_id")["rate_mmcfd"].max()
                keep = peaks[peaks > floor].index
                subset = aged[aged["well_id"].isin(keep)]
                fixed = (
                    subset[subset["age_months"] <= 24]
                    .assign(cohort=lambda d: d["first_month"].dt.year)
                    .groupby(["cohort", "age_months"])["rate_mmcfd"]
                    .median().unstack(0)
                )
            else:
                # Snap to the nearest precomputed floor.
                available = sorted(floor_table["floor"].unique())
                nearest = min(available, key=lambda f: abs(f - floor))
                fixed = (
                    floor_table[floor_table["floor"] == nearest]
                    .pivot(index="age_months", columns="cohort",
                           values="rate_mmcfd")
                )
                if nearest != floor:
                    st.caption(f"Snapped to the nearest preset: {nearest:g}")
            fixed.columns = [str(c) for c in fixed.columns]
            st.line_chart(fixed, height=320)
            st.caption(
                f"Median rate at each month of life, wells peaking above "
                f"{floor:g} MMcf/d. Comparing cohorts at the same age is "
                "the only fair comparison — averaging over a well's "
                "first months rewards whichever cohort is youngest, "
                "because early-life flush production is the highest a "
                "well ever produces."
            )
            st.dataframe(
                fixed.style.format("{:,.2f}"),
                use_container_width=True, height=260,
            )

    with tab_operators:
        show = board.head(40).copy()
        show = show[[
            "rate_now", "share_of_ab_pct", "growth_pct",
            "from_new_wells_pct", "new_wells",
        ]].rename(columns={
            "rate_now": "MMcf/d",
            "share_of_ab_pct": "Share %",
            "growth_pct": "y/y %",
            "from_new_wells_pct": "From new wells %",
            "new_wells": "New wells",
        })
        # Growth shading written directly rather than via
        # Styler.background_gradient, which needs matplotlib - a large
        # dependency to add for one colour ramp, and one that is not
        # installed on Streamlit Cloud by default.
        def growth_shade(value: float) -> str:
            if value != value:                      # NaN
                return ""
            capped = max(-60.0, min(60.0, float(value))) / 60.0
            if capped >= 0:
                rgb = (0, 168, 120)
            else:
                rgb = (214, 69, 80)
                capped = -capped
            alpha = 0.10 + 0.45 * capped
            return (f"background-color: rgba({rgb[0]},{rgb[1]},{rgb[2]},"
                    f"{alpha:.2f});")

        st.dataframe(
            show.style.format({
                "MMcf/d": "{:,.0f}", "Share %": "{:.1f}",
                "y/y %": "{:+.0f}", "From new wells %": "{:.0f}",
                "New wells": "{:,.0f}",
            }).map(growth_shade, subset=["y/y %"]),
            use_container_width=True, height=520,
        )
        st.caption(
            "'From new wells' is the share of today's output coming "
            "from wells that first produced within the last year — a "
            "high number means an operator is running hard to stand "
            "still. Growth is measured against the same month a year "
            "earlier, so it is not distorted by seasonality."
        )

history = load_history(str(PRODUCTION), mtime(PRODUCTION))
if history is not None:
    st.markdown("---")
    st.markdown('<div class="section-label">Monthly history</div>',
                unsafe_allow_html=True)

    product_key = {
        "Gas": "GAS", "Condensate": "COND", "Crude oil": "CRUDE_OIL",
        "Bitumen (in-situ)": "BITUMEN",
    }[product_label]
    subset = history[history["product_class"] == product_key]
    if chosen_operators:
        subset = subset[subset["operator"].isin(chosen_operators)]

    rate = "rate_mmcfd" if product_key == "GAS" else "rate_bbld"
    monthly = subset.groupby("production_month")[rate].sum()
    st.bar_chart(monthly, height=240)
    st.caption(
        f"{units}, all wells including those below the map threshold. "
        "Petrinex publishes about two months in arrears and restates "
        "earlier months, so the most recent bar can move."
    )

st.caption(
    "Well locations from AER ST37 bottom holes; volumes from Petrinex "
    "Alberta public data, reported per well per month. Conventional "
    "only — mined oil sands are excluded, though in-situ bitumen is "
    "present because it reports through ordinary batteries. Terminals, "
    "meter stations, pipelines, refineries and gas plant fractionation "
    "are withheld by Petrinex and are absent rather than zero."
)
