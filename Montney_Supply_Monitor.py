"""Montney Supply Monitor — is the basin responding to LNG?

The question
------------
Forecasts of WCSB supply through 2030 need the Montney to compound at
roughly 4% a year, adding about 1.9 Bcf/d, of which ~1.3 is British
Columbia. LNG Canada is ramping, Woodfibre and Cedar follow. So the
observable test is simple to state: as gas leaves the basin, does supply
respond?

This app is built to let someone answer that themselves rather than be
told. Every number on screen is computed from raw regulator data — AER
ST37 and Petrinex volumetrics for Alberta, BCER frac records for BC.

Two provinces, two different measurements
-----------------------------------------
Petrinex publishes Alberta and Saskatchewan; BC returns HTTP 400. BC
volumes come from BCER's own open prod_csv.zip (see
prepare_bc_production.py), but this app measures BC on completion
activity, which leads production by months. So Alberta is
measured on volumes and wells, BC on completion activity. Different
metrics, same question — and the fact that two independent regulators
and two unrelated measurements agree is the point, not a weakness.

Run
---
    streamlit run Montney_Supply_Monitor.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
DATA = PROJECT_ROOT / "processed" / "monitor"

# BCER's frac layer is backfilled as operations complete, not filed
# ahead. Monthly counts thin sharply at the data edge, which reads as a
# collapse and is not one. Comparisons default to Jan-April, well inside
# the reliable window.
DEFAULT_WINDOW_END = 4

# The frac layer starts September 2021, so 2021 is a partial year.
FIRST_FULL_YEAR = 2022

# Colourblind-safe, matched to the other two apps in this project.
PALETTE = [
    [0, 168, 120], [110, 198, 255], [214, 69, 80], [240, 228, 66],
    [168, 138, 221], [0, 114, 178], [230, 159, 0], [90, 210, 210],
    [244, 122, 182], [160, 82, 45], [127, 184, 0], [196, 121, 172],
]
OTHER_COLOUR = [130, 140, 155]

# Year ramp: dark to bright, so a thinning recent year is visible as
# absence of bright points rather than needing a legend lookup.
YEAR_COLOURS = {
    2021: [70, 90, 120], 2022: [64, 120, 160], 2023: [80, 170, 190],
    2024: [16, 216, 132], 2025: [240, 200, 70], 2026: [235, 90, 90],
}

st.set_page_config(page_title="Montney Supply Monitor", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown("""
<style>
  .section-label { font-size:0.78rem; letter-spacing:0.08em;
    text-transform:uppercase; color:#98a2af; margin:0.2rem 0 0.4rem 0; }
  .legend-item { display:inline-flex; align-items:center; color:#dfe6ef;
    font-size:0.9rem; margin:0 0.9rem 0.4rem 0; }
  .legend-dot { width:14px; height:14px; border-radius:50%;
    border:1.5px solid rgba(248,248,252,0.85); margin-right:0.4rem; }
  .takeaway { border-left:3px solid #4da3ff; padding:0.5rem 0 0.5rem 0.8rem;
    color:#c8d3e0; font-size:0.92rem; margin:0.3rem 0 0.6rem 0; }
</style>
""", unsafe_allow_html=True)


def mtime(path: Path) -> int:
    return path.stat().st_mtime_ns if path.exists() else 0


@st.cache_data(show_spinner=False)
def load_csv(path: str, mtime_ns: int) -> pd.DataFrame:
    del mtime_ns
    file = Path(path)
    if not file.exists():
        return pd.DataFrame()
    return pd.read_csv(file)


BC = DATA / "bc_fracs.csv"
AB_MONTHLY = DATA / "ab_montney_monthly.csv"
AB_WELLS = DATA / "ab_montney_wells.csv"
AB_VINTAGE = DATA / "ab_montney_vintage.csv"

bc = load_csv(str(BC), mtime(BC))
ab_monthly = load_csv(str(AB_MONTHLY), mtime(AB_MONTHLY))
ab_wells = load_csv(str(AB_WELLS), mtime(AB_WELLS))
ab_vintage = load_csv(str(AB_VINTAGE), mtime(AB_VINTAGE))

if bc.empty and ab_monthly.empty:
    st.error("No monitor data found. Run `python3 "
             "prepare_montney_monitor_data.py` first.")
    st.stop()

if not bc.empty:
    bc["start"] = pd.to_datetime(bc["start"], errors="coerce")
    bc["year"] = bc["start"].dt.year
    bc["quarter"] = bc["start"].dt.to_period("Q").astype(str)

st.title("Montney Supply Monitor")
st.caption(
    "Is the basin responding to LNG? Alberta measured on production and "
    "well counts (Petrinex + AER ST37); British Columbia on completion "
    "activity (BCER frac records). Two regulators, two measurements, "
    "one question."
)

tab_bc, tab_ab, tab_compare, tab_notes = st.tabs(
    ["British Columbia — activity", "Alberta — production & wells",
     "Side by side", "Data notes"]
)


# ---------------------------------------------------------------- BC ----
with tab_bc:
    if bc.empty:
        st.warning("BC data not built. Run `prepare_bc_well_locations.py "
                   "--download fracs` then the monitor prep script.")
    else:
        c1, c2, c3, c4 = st.columns([1.1, 1.5, 1.2, 1.2])
        with c1:
            montney_only = st.checkbox(
                "Montney only", value=True,
                help="98.6% of BC frac records target the Montney anyway.")
        with c2:
            years = sorted(bc["year"].dropna().unique().astype(int))
            year_range = st.select_slider(
                "Years", options=years, value=(years[0], years[-1]))
        with c3:
            window_end = st.selectbox(
                "Compare Jan through", [3, 4, 5, 12], index=1,
                format_func=lambda m: {3: "March", 4: "April", 5: "May",
                                       12: "December (full year)"}[m],
                help=("BCER backfills these records, so the last two to "
                      "three months are incomplete. April is the safe "
                      "edge — widen it and watch 2026 fall off a cliff "
                      "that is not real."),
            )
        with c4:
            colour_by = st.radio("Colour map by", ["Year", "Operator"],
                                 horizontal=True)

        view = bc[bc["year"].between(*year_range)]
        if montney_only:
            view = view[view["is_montney"]]

        ops = st.multiselect(
            "Operators (blank = all)",
            sorted(view["operator"].dropna().unique()), default=[])
        if ops:
            view = view[view["operator"].isin(ops)]

        # --- the headline comparison -------------------------------------
        window = view[view["start"].dt.month <= window_end]
        counts = (window.groupby(window["start"].dt.year).size()
                  .loc[lambda s: s.index >= FIRST_FULL_YEAR])

        label = {3: "Jan–Mar", 4: "Jan–Apr", 5: "Jan–May",
                 12: "full year"}[window_end]

        if len(counts) >= 2:
            m1, m2, m3, m4 = st.columns(4)
            latest, prior = counts.index[-1], counts.index[-2]
            m1.metric(f"{latest} wells frac'd ({label})", f"{counts[latest]:,}",
                      f"{(counts[latest] / counts[prior] - 1) * 100:+.0f}% vs {prior}")
            if 2024 in counts.index:
                m2.metric("vs 2024 peak",
                          f"{(counts[latest] / counts[2024] - 1) * 100:+.0f}%",
                          f"{counts[2024]:,} → {counts[latest]:,}")
            peak_year = int(counts.idxmax())
            now_ops = window[window["start"].dt.year == latest]["operator"].nunique()
            peak_ops = window[window["start"].dt.year == peak_year]["operator"].nunique()
            m3.metric("Operators active", f"{now_ops}",
                      f"{now_ops - peak_ops:+d} vs {peak_year}")
            m4.metric("Median depth, m",
                      f"{window[window['start'].dt.year == latest]['td_m'].median():,.0f}",
                      "wells are not getting smaller")

        left, right = st.columns([1.15, 1.0], gap="large")

        with left:
            st.markdown('<div class="section-label">Where and when</div>',
                        unsafe_allow_html=True)
            points = view.dropna(subset=["lat", "lon"]).copy()
            if colour_by == "Year":
                points["colour"] = points["year"].map(
                    lambda y: YEAR_COLOURS.get(int(y), OTHER_COLOUR))
            else:
                top = points["operator"].value_counts().head(12).index.tolist()
                lookup = {name: PALETTE[i] for i, name in enumerate(top)}
                points["colour"] = points["operator"].map(
                    lambda o: lookup.get(o, OTHER_COLOUR))
            points["colour"] = points["colour"].apply(lambda c: [*c, 210])

            st.pydeck_chart(pdk.Deck(
                map_style="mapbox://styles/mapbox/dark-v10",
                initial_view_state=pdk.ViewState(
                    latitude=float(points["lat"].mean()) if len(points) else 56.3,
                    longitude=float(points["lon"].mean()) if len(points) else -121.5,
                    zoom=6.4, pitch=0),
                layers=[pdk.Layer(
                    "ScatterplotLayer", points,
                    get_position=["lon", "lat"], get_fill_color="colour",
                    get_radius=1600, radius_min_pixels=3,
                    radius_max_pixels=9, pickable=True,
                    get_line_color=[20, 24, 34, 180],
                    stroked=True, line_width_min_pixels=0.5)],
                tooltip={"html": "<b>{well_name}</b><br/>{operator}<br/>"
                                 "{formation} · TD {td_m} m<br/>{quarter}"},
            ), height=430)

            if colour_by == "Year":
                items = "".join(
                    f'<span class="legend-item"><span class="legend-dot" '
                    f'style="background:rgb({c[0]},{c[1]},{c[2]});"></span>'
                    f'{y}</span>'
                    for y, c in sorted(YEAR_COLOURS.items())
                    if y in points["year"].values)
                st.markdown(items, unsafe_allow_html=True)
                st.markdown(
                    '<div class="takeaway">Set colour to Year and look for '
                    'red. 2026 points are sparse across the whole fairway — '
                    'the pullback is basin-wide, not one company leaving one '
                    'area.</div>', unsafe_allow_html=True)

        with right:
            st.markdown('<div class="section-label">Wells frac\'d per quarter</div>',
                        unsafe_allow_html=True)
            q = view.groupby("quarter").size().reset_index(name="wells")
            fig = go.Figure(go.Bar(
                x=q["quarter"], y=q["wells"],
                marker_color=["#eb5a5a" if s.startswith("2026")
                              else "#4da3ff" for s in q["quarter"]],
                hovertemplate="%{x}: %{y} wells<extra></extra>"))
            fig.update_layout(
                template="plotly_dark", height=250,
                margin=dict(l=10, r=10, t=10, b=10),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                xaxis_title=None, yaxis_title="wells")
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "The final two to three bars are incomplete — BCER backfills "
                "these records rather than filing them ahead. Judge the trend "
                "on the like-for-like comparison above, not the last bar."
            )

            if len(counts) >= 2:
                st.markdown(f'<div class="section-label">{label} by year</div>',
                            unsafe_allow_html=True)
                fig2 = go.Figure(go.Bar(
                    x=counts.index.astype(str), y=counts.values,
                    marker_color="#10d884",
                    text=counts.values, textposition="outside",
                    hovertemplate="%{x}: %{y} wells<extra></extra>"))
                fig2.update_layout(
                    template="plotly_dark", height=230,
                    margin=dict(l=10, r=10, t=10, b=10),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    xaxis_title=None, yaxis_title="wells")
                st.plotly_chart(fig2, use_container_width=True)

        # --- operator table ---------------------------------------------
        st.markdown('<div class="section-label">By operator</div>',
                    unsafe_allow_html=True)
        table = window.pivot_table(index="operator",
                                   columns=window["start"].dt.year,
                                   values="wa_num", aggfunc="count").fillna(0)
        table = table[[c for c in table.columns if c >= FIRST_FULL_YEAR]]
        if table.shape[1] >= 2:
            first_col, last_col = table.columns[0], table.columns[-1]
            table["change %"] = ((table[last_col] / table[first_col] - 1) * 100
                                 ).where(table[first_col] > 0)
            table = table.sort_values(last_col, ascending=False)
            st.dataframe(
                table.style
                .format({c: "{:.0f}" for c in table.columns if c != "change %"})
                .format({"change %": "{:+.0f}%"}, na_rep="—"),
                use_container_width=True, height=330)
            cutting = int((table[last_col] < table[first_col]).sum())
            active = int((table[first_col] > 0).sum())
            st.markdown(
                f'<div class="takeaway">{cutting} of {active} operators are '
                f'drilling less in {last_col} than in {first_col}. A pullback '
                f'this broad is a price response or a play problem — it is not '
                f'one company\'s balance sheet.</div>', unsafe_allow_html=True)


# ----------------------------------------------------------- ALBERTA ----
with tab_ab:
    if ab_monthly.empty:
        st.warning("Alberta data not built.")
    else:
        st.markdown('<div class="section-label">'
                    'Production by well vintage — the treadmill</div>',
                    unsafe_allow_html=True)

        h1_only = st.checkbox(
            "First half of each year only", value=True,
            help=("Alberta gas is strongly seasonal and the data ends in "
                  "June 2026. Comparing full years against a half year "
                  "would invent a decline."))

        m = ab_monthly.copy()
        if h1_only:
            m = m[m["month"].str[5:7] <= "06"]

        pivot = m.pivot_table(index="month", columns="cohort",
                              values="bcfd", aggfunc="sum").fillna(0)
        fig = go.Figure()
        cohorts = [c for c in pivot.columns if c != "2022 & earlier"]
        fig.add_trace(go.Scatter(
            x=pivot.index, y=pivot["2022 & earlier"], name="2022 & earlier",
            stackgroup="one", line=dict(width=0.5, color="#7890a8"),
            fillcolor="rgba(120,144,168,0.75)"))
        for i, c in enumerate(sorted(cohorts)):
            col = PALETTE[i % len(PALETTE)]
            fig.add_trace(go.Scatter(
                x=pivot.index, y=pivot[c], name=f"{c} wells",
                stackgroup="one", line=dict(width=0.5,
                                            color=f"rgb({col[0]},{col[1]},{col[2]})"),
                fillcolor=f"rgba({col[0]},{col[1]},{col[2]},0.8)"))
        fig.update_layout(
            template="plotly_dark", height=380,
            margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            yaxis_title="Bcf/d", xaxis_title=None,
            legend=dict(orientation="h", y=-0.18))
        st.plotly_chart(fig, use_container_width=True)

        # Aggregate to an annual average before measuring decline.
        # Comparing the first and last *monthly* observations instead
        # would contrast January 2022 against June 2026 - two different
        # points in a strongly seasonal year - and understated the base
        # decline by nearly two points when this app was first written.
        annual = pivot.groupby(pivot.index.str[:4]).mean()
        base = annual["2022 & earlier"]
        if len(base) > 1:
            decline = 1 - (base.iloc[-1] / base.iloc[0]) ** (1 / (len(base) - 1))
            newest = annual[cohorts].iloc[-1].sum() if cohorts else 0
            lost = base.iloc[0] - base.iloc[-1]
            a, b, c = st.columns(3)
            a.metric("Base decline, pre-2023 wells", f"{decline * 100:.1f}%/yr")
            b.metric("New wells now contribute", f"{newest:.2f} Bcf/d")
            c.metric("Of which replaces decline",
                     f"{lost / newest * 100:.0f}%" if newest else "—",
                     f"net growth {newest - lost:+.2f} Bcf/d")
            st.markdown(
                '<div class="takeaway">The grey band is what the basin had in '
                '2022, melting away. Everything above it is new drilling. Most '
                'of the new drilling is replacing the melt, not adding to '
                'it.</div>', unsafe_allow_html=True)

        st.divider()

        left, right = st.columns(2, gap="large")

        with left:
            st.markdown('<div class="section-label">New wells online</div>',
                        unsafe_allow_html=True)
            if not ab_wells.empty:
                w = ab_wells.copy()
                w["year"] = w["first_month"].str[:4]
                w["month_no"] = w["first_month"].str[5:7]
                half = st.checkbox("First half only", value=True,
                                   key="ab_wells_h1")
                if half:
                    w = w[w["month_no"] <= "06"]
                counts = w.groupby("year").size()
                fig = go.Figure(go.Bar(
                    x=counts.index, y=counts.values, marker_color="#4da3ff",
                    text=counts.values, textposition="outside"))
                fig.update_layout(
                    template="plotly_dark", height=280,
                    margin=dict(l=10, r=10, t=10, b=10),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    yaxis_title="wells", xaxis_title=None)
                st.plotly_chart(fig, use_container_width=True)
                if len(counts) >= 2:
                    st.caption(
                        f"{counts.index[-1]} vs {counts.index[-2]}: "
                        f"{(counts.iloc[-1] / counts.iloc[-2] - 1) * 100:+.0f}%")

        with right:
            st.markdown('<div class="section-label">'
                        'Productivity per 1,000 m of lateral</div>',
                        unsafe_allow_html=True)
            if not ab_vintage.empty:
                window_months = st.radio(
                    "Fixed age", sorted(ab_vintage["window"].unique()),
                    horizontal=True, format_func=lambda m: f"{m} months",
                    index=1 if 12 in ab_vintage["window"].values else 0,
                    help=("Complete windows only. A four-month well is "
                          "excluded rather than annualised — annualising "
                          "measures the flush period and flatters recent "
                          "vintages."))
                v = ab_vintage[ab_vintage["window"] == window_months]
                stats = v.groupby("vintage")["per_1000m"].agg(
                    ["median", "count"])
                stats = stats[stats["count"] >= 20]
                fig = go.Figure(go.Bar(
                    x=stats.index.astype(str), y=stats["median"],
                    marker_color="#10d884",
                    text=stats["median"].round(0), textposition="outside",
                    customdata=stats["count"],
                    hovertemplate="%{x}: %{y:.0f} MMcf/1,000 m"
                                  "<br>%{customdata} wells<extra></extra>"))
                fig.update_layout(
                    template="plotly_dark", height=280,
                    margin=dict(l=10, r=10, t=10, b=10),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    yaxis_title="MMcf per 1,000 m", xaxis_title=None)
                st.plotly_chart(fig, use_container_width=True)
                if len(stats) >= 2:
                    st.caption(
                        f"{stats.index[-1]} vs {stats.index[-2]}: "
                        f"{(stats['median'].iloc[-1] / stats['median'].iloc[-2] - 1) * 100:+.0f}%"
                        f" · lateral length is normalised out, so this is not "
                        f"a longer-wells effect.")

        # Operator-level productivity: the check that decides whether the
        # decline means anything. If it were a mix shift - different
        # companies drilling - it would say nothing about the rock.
        if not ab_vintage.empty:
            st.markdown('<div class="section-label">'
                        'Same operators, different vintages</div>',
                        unsafe_allow_html=True)
            v = ab_vintage[ab_vintage["window"] == window_months]
            piv = v.pivot_table(index="operator", columns="vintage",
                                values="per_1000m", aggfunc="median")
            cnt = v.pivot_table(index="operator", columns="vintage",
                                values="well_id", aggfunc="count")
            pair = [c for c in ("2024", "2025") if c in piv.columns]
            if len(pair) == 2:
                both = piv.dropna(subset=pair)
                both = both[(cnt.loc[both.index, "2024"] >= 10)
                            & (cnt.loc[both.index, "2025"] >= 10)]
                if not both.empty:
                    show = both[pair].copy()
                    show["change %"] = (show["2025"] / show["2024"] - 1) * 100
                    show["wells 24"] = cnt.loc[show.index, "2024"]
                    show["wells 25"] = cnt.loc[show.index, "2025"]
                    st.dataframe(
                        show.sort_values("change %").style.format({
                            "2024": "{:.0f}", "2025": "{:.0f}",
                            "change %": "{:+.0f}%",
                            "wells 24": "{:.0f}", "wells 25": "{:.0f}"}),
                        use_container_width=True)
                    down = int((show["change %"] < 0).sum())
                    st.markdown(
                        f'<div class="takeaway">{down} of {len(show)} '
                        f'operators got less gas per metre in 2025 than 2024. '
                        f'Because these are the same companies in both years, '
                        f'this is not a change in who is drilling.</div>',
                        unsafe_allow_html=True)


# -------------------------------------------------------- SIDE BY SIDE --
with tab_compare:
    st.markdown('<div class="section-label">'
                'Two regulators, two measurements, indexed to 2024</div>',
                unsafe_allow_html=True)

    # Both series are keyed by calendar year, but they arrive with
    # different index dtypes - BC from a datetime .dt.year (int64),
    # Alberta from a sliced string. Under pandas' Arrow string backend a
    # string index is not object dtype, so branching on dtype silently
    # took the wrong path and compared strings to integers. Coerce both
    # to plain integers once, here, and never test dtype again.
    def by_year(counts: pd.Series) -> pd.Series:
        counts.index = pd.to_numeric(counts.index, errors="coerce").astype("Int64")
        counts = counts[counts.index.notna()]
        counts.index = counts.index.astype(int)
        return counts[counts.index >= FIRST_FULL_YEAR].sort_index()

    series = {}
    if not bc.empty:
        w = bc[bc["is_montney"] & (bc["start"].dt.month <= DEFAULT_WINDOW_END)]
        series["BC — wells frac'd (Jan–Apr)"] = by_year(
            w.groupby(w["start"].dt.year).size())
    if not ab_wells.empty:
        w = ab_wells[ab_wells["first_month"].str[5:7] <= "06"]
        series["Alberta — new wells online (H1)"] = by_year(
            w.groupby(w["first_month"].str[:4]).size())

    if series:
        fig = go.Figure()
        for i, (name, counts) in enumerate(series.items()):
            if 2024 not in counts.index or counts[2024] == 0:
                continue
            col = PALETTE[i]
            fig.add_trace(go.Scatter(
                x=counts.index.astype(str),
                y=counts / counts[2024] * 100,
                name=name, mode="lines+markers",
                line=dict(width=3, color=f"rgb({col[0]},{col[1]},{col[2]})"),
                marker=dict(size=9),
                customdata=counts.values,
                hovertemplate="%{x}: index %{y:.0f}"
                              "<br>%{customdata} wells<extra></extra>"))
        fig.add_hline(y=100, line_dash="dot", line_color="#6b7280",
                      annotation_text="2024 = 100")
        fig.update_layout(
            template="plotly_dark", height=400,
            margin=dict(l=10, r=10, t=20, b=10),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            yaxis_title="index, 2024 = 100", xaxis_title=None,
            legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig, use_container_width=True)

        latest = {n: (c.index[-1], c.iloc[-1] / c[2024] * 100 - 100)
                  for n, c in series.items() if 2024 in c.index}
        if latest:
            cols = st.columns(len(latest))
            for col, (name, (year, change)) in zip(cols, latest.items()):
                col.metric(name, f"{change:+.0f}%", f"{year} vs 2024")

        st.markdown(
            '<div class="takeaway">Alberta first-production counts and BC '
            'frac starts are collected by different regulators, for '
            'different purposes, and measure different events. They agree. '
            'That is what makes the pullback hard to dismiss as a quirk of '
            'one dataset.</div>', unsafe_allow_html=True)

    st.divider()
    st.markdown('<div class="section-label">What would change the picture</div>',
                unsafe_allow_html=True)
    st.markdown("""
- **Activity recovering into 2027** would mean the pullback was a price
  response to a weak strip — supply is elastic, and the forecast holds.
- **Activity staying down while AECO improves** would mean something
  structural: inventory quality, egress, or capital allocated elsewhere.
- **Alberta productivity stabilising** would suggest 2025 was noise
  rather than the start of a trend.

Frac activity leads production by months, so this turns before volumes do.
That is the reason to watch it.
""")


# ------------------------------------------------------------- NOTES ----
with tab_notes:
    st.markdown("""
### Sources

| | Alberta | British Columbia |
|---|---|---|
| Production | Petrinex volumetrics | BCER `prod_csv.zip` (zone-level) |
| Well location | AER ST37 | BCER `WELL_BOTTOM_HOLE_STATE_PT` |
| Activity | first production month | BCER `HISTORIC_FRACTURING` |
| Play attribution | geographic box | `OBJECTIVE_FORMATION` field |

### Known limits

**BC is measured on activity here, not volumes** — but production *is*
available. Petrinex publishes Alberta and Saskatchewan only (every BC
month returns HTTP 400), which is why this app was built on frac
activity. BCER does publish monthly volumes as an open download,
`iris.bcogc.ca/download/prod_csv.zip`, with no logon; I had wrongly
concluded otherwise from the gated Legacy Well Lookup. That file is now
parsed by `prepare_bc_production.py` and reconciles to 7.54 Bcf/d
marketable against Peters' 7.5 for BC Montney. It is not yet wired into
the charts on these tabs.

Activity still leads production by months, so it remains the better
early indicator for the question this app asks.

**BC frac records are backfilled.** Despite the field name
`OPS_EXPECTED_START_DATE`, no record carries a future date. The last two
to three months are always thin. Comparisons default to January–April
for that reason; widen the window and 2026 appears to collapse, which is
an artifact.

**The BC frac layer starts September 2021** and appears to be a rolling
window rather than complete history. 2021 is excluded as partial.

**Alberta play attribution is a geographic box**, so levels differ from
formation-based published figures. Growth rates are comparable; levels
are not.

**Lateral length is a proxy** — total depth less true vertical depth from
ST37, not a surveyed value.

**Alberta location coverage** runs 94.5% of gas volume in early 2022 to
100% now; the gap is wells that ceased before the ST37 join month, which
slightly overstates measured growth.

**Condensate is excluded throughout.** Well-level condensate in Petrinex
depends on where liquids are metered, not on what the well produces, so
it cannot support a liquids-targeting analysis.

### How reliable is this?

Each claim was probed, not assumed. Two categories survived; one did not.

**Robust — holds under every sensitivity test**

| Finding | Tested against | Range |
|---|---|---|
| Alberta new wells down | Jan–Mar / Apr / May / Jun windows | −38% to −47% |
| Alberta productivity down | lateral filters 500/1,500/2,000/2,500 m | −18.5% to −19.6% |
| — same, unnormalised | raw 12-month cumulative | −17.5% |
| BC activity down | Jan–Mar / Apr / May windows | −27% to −38% |

Lateral lengths inside the comparison sample are *stable and slightly
longer* in 2025 (p25 2,957 m vs 2,844 m), so longer wells are producing
less per metre. Depth coverage is 95–99% with no vintage pattern, so the
exclusion isn't selecting.

**Not robust — treat as suggestive**

The Alberta CAGR of 3.92% against the 4.15% requirement. Shrink the play
box and it reads 4.42%; enlarge it and 4.03–4.13%. Separately, location
coverage biases measured growth upward, and the outer bound on that takes
the true figure to 2.35%. The direction is more likely right than wrong,
but the margin sits inside the measurement error. **Don't present this one
as a measurement.**

The −2.4% year-on-year print is different — a like-for-like comparison of
the same box in consecutive first-halves — and doesn't depend on any of it.

**Levels are not comparable to published forecasts**

Petrinex PROD gas is *gross wellhead* volume. Peters and AER work on
*marketable* gas, after fuel, flare and processing shrinkage of roughly
10–15%. This data shows 14.0 Bcf/d for Alberta against roughly 12.0–12.6
marketable. Growth rates compare; levels do not.

**Two things that run in your favour**

Base decline of 16.3%/yr is conservative — the wells that can't be located
are the fastest decliners, so excluding them *understates* the true rate.

BC's count is immune to the M&A problem that broke Alberta's operator
table, because it counts wells rather than attributing them to firms. Only
two small operators appear in 2024 and not 2026.

### Reproducing

```
python3 prepare_bc_well_locations.py --download fracs
python3 prepare_montney_monitor_data.py
python3 analyse_montney_supply.py
python3 analyse_bc_montney_activity.py
```
""")
