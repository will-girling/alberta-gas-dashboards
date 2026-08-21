# NGTL System Monitor / Gas Day Summary Scraper
## Technical Handover for Local Development

**Project root:**  
`/Users/willgirling/Desktop/NGTL Project`

**Current dashboard file:**  
`/Users/willgirling/Desktop/NGTL Project/app_v19_1.py`

**Primary goal:**  
Build a local Streamlit dashboard for monitoring the NGTL system using TC Energy Gas Day Summary Report data, with Alberta/Western Canadian pipeline geography overlaid from AER shapefiles. The dashboard is intended to make border/interconnect flows, Alberta demand, storage, linepack, and pipeline context easy to monitor historically and day-by-day.

---

# 1. Project objectives

The project has three main components:

1. **Automated TC Energy data collection**
   - Download one NGTL Gas Day Summary Report CSV per gas day.
   - Preserve the raw files.
   - Compile the daily reports into historical datasets.

2. **Data processing**
   - Convert the raw report structure into normalized time-series CSVs.
   - Separate flow/system-balance rows from operational metrics.
   - Preserve the TC Energy sign convention.

3. **Streamlit dashboard**
   - Select any available gas day.
   - Display Alberta-wide system metrics.
   - Display NGTL pipelines geographically.
   - Display important border/interconnect locations.
   - Allow selection of an interconnect and replace the Alberta-wide RHS metrics with detailed border metrics.
   - Provide rolling 14-day and 30-day context.
   - Eventually add compressor stations, maintenance/outages, wells, and other Western Canadian gas-market layers.

---

# 2. Local directory structure

Current known directory layout:

```text
/Users/willgirling/Desktop/NGTL Project/
│
├── download_gdsr.py
├── prepare_pipeline_layers.py
├── app_v19_1.py
│
├── gdsr/
│   ├── GdsrNGTLImperialYYYYMMDD.csv
│   ├── GdsrNGTLImperialYYYYMMDD.csv
│   └── ...
│
├── processed/
│   ├── ngtl_daily_flows.csv
│   ├── ngtl_operational_metrics.csv
│   ├── ngtl_operating_pipelines.geojson
│   ├── major_operating_gas_pipelines.geojson
│   └── pipeline_company_summary.csv
│
├── assets/
│   └── alberta_boundary.geojson
│
├── Pipelines_SHP/
│   └── Pipelines_GCS_NAD83.shp
│       + associated .dbf/.shx/.prj/etc.
│
├── Pipeline_Installations_SHP/
│   └── [AER installation shapefile components]
│
└── ST37/
    └── [AER well / ST37 data; not yet integrated]
```

The exact name/content of the ST37 folder has not yet been formalized in code.

---

# 3. Python environment

The project is being run using Miniforge Python 3.12.

Known installed packages include:

```text
Python 3.12
Streamlit 1.61.1
pandas 3.0.3
plotly 6.5.2
requests 2.32.3
GeoPandas 1.1.4
pyogrio 0.13.0
Shapely 2.1.2
pyproj 3.7.2
PyDeck
Playwright
```

Typical launch command:

```bash
cd "/Users/willgirling/Desktop/NGTL Project"
python3 -m streamlit run app_v19_1.py
```

For scraper automation, Playwright Chromium was installed and used successfully.

---

# 4. TC Energy data source

Gas Day Summary Report page:

```text
https://my.tccustomerexpress.com/#GasDaySummaryReport
```

The page exposes one report per gas day.

Raw downloaded files follow the pattern:

```text
GdsrNGTLImperialYYYYMMDD.csv
```

Example conceptual filename:

```text
GdsrNGTLImperial20260806.csv
```

Raw files are stored in:

```text
/Users/willgirling/Desktop/NGTL Project/gdsr
```

Historical availability appeared to extend back to approximately November 2021.

Weekends and holidays have reports.

The current/new gas day generally becomes available the next morning.

---

# 5. Important units and sign convention

## Flow units

TC Energy Gas Day Summary Report flows are treated as:

```text
MMcf/d
```

The dashboard often converts system-wide values to:

```text
Bcf/d = MMcf/d / 1000
```

## Sign convention

This is important and should NOT be lost:

```text
Positive = INTO NGTL
Negative = OUT OF NGTL
```

Therefore:

- Empress export can appear negative.
- A more-negative value means greater outbound physical flow.
- Main displayed flow values should preserve their sign.

The current dashboard deliberately handles relative comparisons differently:

```text
relative magnitude = abs(current flow) - abs(recent average)
```

This avoids treating stronger exports as automatically "bad" merely because the signed value becomes more negative.

Example:

```text
Current              -4,248 MMcf/d
14-day average       -4,110 MMcf/d

Magnitude difference:
abs(-4,248) - abs(-4,110) = +138 MMcf/d
```

Interpretation:

```text
Current flow is outbound.
Outbound magnitude is 138 MMcf/d above the 14-day average.
```

---

# 6. Scraper: `download_gdsr.py`

The scraper was developed using Playwright.

## Purpose

Automate downloading Gas Day Summary Report CSVs across a date range instead of manually selecting each gas day.

## General workflow

1. Open the TC Energy Customer Express Gas Day Summary Report page.
2. Select the requested gas day using the calendar/date control.
3. Trigger the CSV download.
4. Save the downloaded report into:

```text
/Users/willgirling/Desktop/NGTL Project/gdsr
```

5. Repeat over the requested date range.
6. Avoid unnecessarily redownloading files already present.
7. Compile the raw folder into normalized historical datasets.

The script used a browser capture/replay approach because the page is a JavaScript application rather than a simple static download URL.

The downloader was successfully tested and used for historical backfill.

## Important future principle

Keep raw source files immutable.

Do not edit CSVs in `gdsr/`. Any cleaning or normalization should happen during compilation into `processed/`.

---

# 7. Compiled datasets

## 7.1 `processed/ngtl_daily_flows.csv`

Expected schema:

```text
GasDay
NextDayGasDay
Item
Category
ProratedMMcfd
ExtrapolatedMMcfd
NextDayNominatedMMcfd
SourceFile
```

Typical `Item` rows include:

- Empress Border
- McNeill Border
- Alberta-BC border
- Gordondale
- Groundbirch East
- Willow Valley
- Intraprovincial
- Total Net Storage
- Total NGTL Receipts
- Total NGTL Deliveries

The exact raw wording can vary, which is why the dashboard has source-label matching logic.

## 7.2 `processed/ngtl_operational_metrics.csv`

Expected schema:

```text
GasDay
Metric
NumericValue
TextValue
SourceFile
```

Typical operational metrics include:

- NGTL Field Receipts
- End of Day Linepack
- Linepack Target
- tolerance values
- account/system values

The dashboard currently uses:

```text
Field Receipts
Linepack
Linepack Target
```

---

# 8. Current source-label matching logic

The raw TC Energy labels are not assumed to remain perfectly identical.

`app_v19_1.py` uses:

```python
normalize_label()
resolve_name()
```

## `normalize_label()`

Logic:

1. uppercase
2. replace `&` with `AND`
3. remove leading `*`
4. replace punctuation/non-alphanumeric characters with spaces
5. collapse repeated whitespace

Example:

```text
"ALBERTA-B.C. BDR"
```

becomes approximately:

```text
"ALBERTA B C BDR"
```

## `resolve_name()`

Attempts matching in this order:

1. exact normalized match
2. candidate tokens fully contained in source tokens
3. source tokens fully contained in candidate tokens
4. substring fallback

This was added because earlier versions only found Groundbirch reliably.

### Current aliases

```python
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
```

Operational aliases:

```python
ops_candidates = {
    "Field Receipts": ["NGTL FIELD RECEIPTS", "FIELD RECEIPTS"],
    "Linepack": ["END OF DAY LINEPACK"],
    "Linepack Target": ["LINEPACK TARGET"],
}
```

Do not silently replace this matching system with exact string equality unless the source file has first been inspected.

---

# 9. Time-series helper logic

The current app contains the following conceptual pipeline:

```text
raw compiled DataFrame
        ↓
resolve source name
        ↓
build time series
        ↓
snapshot(selected gas day)
        ↓
current / previous / 14d / 30d metrics
```

## `build_flow_series()`

Creates a `GasDay -> value` series for a flow item.

Default data field:

```text
ExtrapolatedMMcfd
```

## `build_ops_series()`

Creates a `GasDay -> NumericValue` series for an operational metric.

## `snapshot()`

Returns:

```python
{
    "current": ...,
    "previous": ...,
    "change": ...,
    "avg14": ...,
    "avg30": ...,
    "vs14": ...,
    "vs30": ...,
}
```

The 14-day and 30-day averages use the latest 14/30 observations up to and including the selected gas day.

This is observation-based, not explicitly calendar-day-window based.

---

# 10. Alberta boundary

The dashboard uses a real Government of Alberta administrative boundary.

Source endpoint:

```text
https://geospatial.alberta.ca/titan/rest/services/boundary/goa_administrative_area/MapServer/0/query
```

Parameters used:

```text
where=1=1
outFields=OBJECTID,PROV_NAME
returnGeometry=true
outSR=4326
f=geojson
```

The downloaded boundary is cached locally:

```text
/Users/willgirling/Desktop/NGTL Project/assets/alberta_boundary.geojson
```

`load_alberta_geojson()`:

1. checks local cache;
2. if missing, downloads the GeoJSON;
3. stores it in `assets/`;
4. reuses local file thereafter.

---

# 11. AER pipeline data

Raw pipeline shapefile:

```text
/Users/willgirling/Desktop/NGTL Project/Pipelines_SHP/Pipelines_GCS_NAD83.shp
```

It successfully loaded with approximately:

```text
323,112 total rows
CRS: EPSG:4269
301,743 LineString
21,369 MultiLineString
```

Important raw fields include:

```text
OBJECTID
LICENCE_NO
IS_NEB
LINE_NO
LIC_LI_NO
PLLICSEGID
COMP_NAME
BA_CODE
PL_SPEC_ID
SEG_LENGTH
SEG_STATUS
FROM_FAC
FROM_LOC
TO_FAC
TO_LOC
OUT_DIAMET
PIPE_TYPE
PIPE_GRADE
PIPE_MATERL
PIPE_MAOP
BIDIRE_IND
FLD_CTR_NM
SUBSTANCE1
SUBSTANCE2
SUBSTANCE3
SHAPE_LEN
geometry
```

Observed `SEG_STATUS` examples:

```text
Operating
Abandoned
Discontinued
Removed
Permitted
```

Observed `SUBSTANCE1` examples:

```text
Natural Gas
Oil-Well Effluent
Salt Water
Fuel Gas
Sour Natural Gas
...
```

Important company match:

```text
NOVA Gas Transmission Ltd.
```

---

# 12. Pipeline preprocessing: `prepare_pipeline_layers.py`

Purpose:

Convert the very large AER shapefile into smaller GeoJSON layers that Streamlit/PyDeck can load quickly.

## Current filters

Start with:

```text
SEG_STATUS == Operating
```

Then gas filter:

```text
SUBSTANCE1 in:
- Natural Gas
- Sour Natural Gas
```

NGTL filter:

```text
COMP_NAME == "NOVA Gas Transmission Ltd."
```

Output CRS:

```text
EPSG:4326
```

## Current output files

```text
processed/ngtl_operating_pipelines.geojson
processed/major_operating_gas_pipelines.geojson
processed/pipeline_company_summary.csv
```

The current dashboard primarily reads:

```text
processed/ngtl_operating_pipelines.geojson
```

A dashboard toggle can further restrict lines to:

```text
OUT_DIAMET >= 600 mm
```

This threshold is a visualization rule for "main transmission lines only."

It is NOT a formal AER/NGTL classification.

---

# 13. Pipeline layer in Streamlit

Current pipeline data source:

```python
NGTL_PIPELINE_FILE = (
    PROJECT_ROOT
    / "processed"
    / "ngtl_operating_pipelines.geojson"
)
```

`load_pipeline_geojson()` enriches every GeoJSON feature with tooltip properties:

```text
tooltip_title
tooltip_line1
tooltip_line2
tooltip_line3
tooltip_line4
tooltip_line5
tooltip_line6
```

Displayed information includes:

- company
- licence number
- line number
- diameter
- substance
- segment status
- segment length
- segment ID

PyDeck is used instead of Plotly for pipeline geometry because rendering one Plotly trace per pipeline segment caused the map to become unusable/blank.

This was an important architectural decision:

```text
PyDeck = geographic layers + hover
Plotly = historical charts
Streamlit = surrounding dashboard UI
```

---

# 14. Current interconnect locations

These coordinates are approximate dashboard placement coordinates and have NOT been formally verified against survey/GIS facility coordinates.

```text
Gordondale Border
lat 55.80
lon -119.98

Groundbirch East
lat 55.78
lon -120.62

Willow Valley Interconnect
lat 55.66
lon -120.55

Alberta–BC Border
lat 49.63
lon -114.69

Empress Border
lat 50.95
lon -110.01

McNeill Border
lat 50.66
lon -110.02
```

Display names currently used:

```text
Gordondale Border
Groundbirch East
Willow Valley Interconnect
Alberta–BC Border
Empress Border
McNeill Border
```

Label positions are split into `"above"` / `"below"` so nearby labels do not overlap as badly.

---

# 15. Current marker design

As of `app_v19_1.py`:

- large purple markers
- white outline
- white text labels
- labels directly on/near markers
- no persistent callout cards
- markers are selectable

PyDeck marker layer uses roughly:

```text
fill colour: [151, 107, 255, 245]
radius min: 8 px
radius max: 17 px
```

The earlier persistent floating-card approach should be considered abandoned.

It produced poor sizing/alignment and should not be revived unless implemented with a proper custom HTML/frontend overlay.

---

# 16. Current RHS interaction design

Desired UX:

```text
No selected interconnect
    ↓
RHS = Alberta System Balance

Select interconnect marker
    ↓
RHS = selected border/interconnect details

Press "AB"
    ↓
RHS = Alberta System Balance
```

The implementation currently uses click selection because standard Streamlit `st.pydeck_chart()` does not expose continuous hover events to Python.

Current selection mechanism:

```python
st.pydeck_chart(
    deck,
    on_select="rerun",
    selection_mode="single-object",
    key="ngtl_system_map",
)
```

Then:

```python
selected_objects = map_event.selection.get("objects", {})
selected_border_objects = selected_objects.get("border-points", [])
```

Selected label is stored in:

```python
st.session_state["selected_interconnect"]
```

## Desired future behavior

The user ultimately prefers:

```text
hover marker
→ RHS temporarily becomes border metrics

hover away
→ RHS automatically returns to Alberta metrics
```

This is NOT currently available with ordinary Streamlit/PyDeck Python callbacks.

To implement true hover-driven RHS replacement, likely use:

- a custom Streamlit component, or
- custom deck.gl JavaScript that emits hover events to Streamlit.

Do not pretend this is available through basic `st.pydeck_chart()` if it is not.

---

# 17. Alberta System Balance RHS

When no interconnect is selected, RHS displays:

```text
Field Receipts
Intraprovincial
Total Deliveries
Total Receipts
Net Storage
Linepack vs Target
```

Current display units:

```text
Bcf/d
```

except:

```text
Linepack vs Target → Bcf
```

Each standard metric shows:

- current
- prior-day change
- 14-day average
- 30-day average

The system uses native `st.metric()` components.

This replaced an earlier custom HTML-card implementation that sometimes rendered raw HTML into the page.

The native Streamlit metric design is currently considered good and should be preserved unless there is a clear reason to change it.

There is also a selected-day table below the metric cards.

---

# 18. Linepack logic

Current linepack display:

```text
Linepack vs Target =
End of Day Linepack - Linepack Target
```

The current synthetic `linepack_gap` snapshot only meaningfully contains:

```text
current
```

and leaves:

```text
previous
change
avg14
avg30
vs14
vs30
```

as NaN.

This can be improved later by constructing a full historical linepack-gap series before calling `snapshot()`.

---

# 19. Interconnect RHS detail logic

When an interconnect is selected, main signed rows currently display:

```text
Current extrapolated
Prorated
Next-day nominated
14-day average
30-day average
```

All preserve the actual NGTL sign convention:

```text
positive = inbound
negative = outbound
```

Two relative rows are calculated separately:

```text
vs 14-day magnitude
vs 30-day magnitude
```

Formula:

```python
abs(current) - abs(avg)
```

Conditional formatting:

```text
positive magnitude difference → green
negative magnitude difference → red
zero / missing → grey
```

This distinction is deliberate.

Do not instead colour based simply on the sign of the raw signed flow.

For example:

```text
-4,248 MMcf/d
```

is not inherently red/bad; it simply means outbound.

---

# 20. Relative-status logic

The app also contains `relative_status()`.

Current threshold:

```text
100 MMcf/d
```

Logic:

```python
current_mag = abs(current)
diff14 = current_mag - abs(avg14)
diff30 = current_mag - abs(avg30)
```

Classification:

```text
above:
    diff14 > +100
    AND diff30 > +100

below:
    diff14 < -100
    AND diff30 < -100

neutral:
    abs(diff14) <= 100
    AND abs(diff30) <= 100

mixed:
    everything else
```

Current colors:

```text
above   green
below   red
mixed   amber
neutral grey
```

The markers themselves were later made purple, so status color is now primarily useful in the RHS detail panel / comparison formatting rather than as marker fill.

---

# 21. Current map

Current map engine:

```text
PyDeck / deck.gl
```

Map style:

```text
dark
```

Approximate initial view:

```python
latitude=54.7
longitude=-114.8
zoom=4.1
pitch=0
bearing=0
```

Main map layers include:

1. Alberta boundary
2. NGTL pipeline GeoJSON
3. interconnect ScatterplotLayer
4. interconnect TextLayer labels

Pipeline display toggles include:

```text
Show NGTL pipelines
Main transmission lines only
```

"Main transmission lines only" currently means:

```text
diameter >= 600 mm
```

---

# 22. Historical dashboard sections

Below the map/RHS area, current app includes:

## Current versus recent history

Comparison table containing items such as:

```text
Empress
McNeill
Alberta–BC
Gordondale
Groundbirch East
Willow Valley
Intraprovincial
Net Storage
Total Deliveries
```

Columns:

```text
Direction
Current
14d avg
30d avg
vs 14d
vs 30d
```

These table calculations currently use the signed `snapshot()` differences.

That means this table is conceptually different from the RHS magnitude-based interconnect comparison.

Claude should decide whether to retain that distinction or make comparison semantics explicit in column names.

## Historical context

A historical chart exists below the comparison table.

Plotly is used for the historical charting portion of the app.

---

# 23. Important known cleanup in `app_v19_1.py`

`app_v19_1.py` works from a long sequence of iterative UI versions and still contains obsolete remnants.

Claude should clean these before making major additions.

## 23.1 Old callout-position code remains

The file still contains:

```python
callout_positions = {...}
```

and writes:

```text
callout_lon
callout_lat
```

to `border_points`.

Persistent callout cards are no longer used.

This code should be removed unless another feature actually uses it.

## 23.2 Status is calculated twice

The current file contains duplicate lines similar to:

```python
border_points["status"] = ...
border_points["status_colour"] = ...
```

twice.

Remove the duplicate.

## 23.3 Old hover helper columns remain

The file still creates fields including:

```text
hover_current
hover_prorated
hover_nominated
hover_avg14
hover_avg30
hover_vs14
hover_vs30
hover_direction
hover_status
```

The current simple marker tooltip does not need all of these.

Remove unused columns after checking pipeline tooltip compatibility.

## 23.4 Caption text is stale

The map caption still references:

```text
"Interconnect cards are compact fixed-format callouts"
```

even though persistent cards were removed.

Update it to describe:

- purple labeled markers
- click selection
- pipeline hover
- main-line filter

## 23.5 Tooltip field collision

Pipeline features and interconnect rows share generic property names like:

```text
tooltip_title
tooltip_line1
...
```

This works but is brittle.

A cleaner design would give each layer its own explicit tooltip payload or use layer-specific rendering if practical.

## 23.6 True hover RHS is still not implemented

Current code is click-selected.

Do not confuse current click behavior with the desired eventual hover behavior.

---

# 24. Most recent bug fixed

`app_v19.py` crashed with:

```text
KeyError: 'prorated_abs_mmcf'
```

because the signed-flow refactor removed:

```text
prorated_abs_mmcf
nominated_abs_mmcf
```

while old hover helper code still referenced them.

`app_v19_1.py` restores those helper columns.

If the obsolete hover helper code is removed during cleanup, those absolute columns may no longer be necessary except where magnitude calculations genuinely use them.

---

# 25. Pipeline hover

Pipeline hover is useful and should be retained.

Current feature properties include:

```text
Company
Licence / Line
Diameter
Substance
Status
Length
Segment ID
```

The pipeline tooltip was deliberately enlarged during prior iterations.

Do not regress to one Plotly trace per segment; that approach performed poorly.

---

# 26. AER pipeline installations: next major GIS layer

There is a folder:

```text
/Users/willgirling/Desktop/NGTL Project/Pipeline_Installations_SHP
```

This has not yet been integrated.

AER installation records include installation types such as:

```text
CS = Compressor Station
PS = Pump Station
RS = Regulator Station
MS = Meter Station
MR = Meter / Regulator
```

Highest-priority next layer:

```text
Compressor stations
```

Suggested preprocessing:

1. load installation shapefile with GeoPandas;
2. identify actual truncated shapefile field names;
3. filter operating installations;
4. filter `Installation_Type == "CS"` or actual corresponding field;
5. optionally filter to NGTL/NOVA;
6. transform to EPSG:4326;
7. export lightweight GeoJSON:
   `processed/ngtl_compressor_stations.geojson`;
8. add PyDeck ScatterplotLayer;
9. add hover with station/license/company metadata.

Do not guess field names without first inspecting the actual shapefile columns.

---

# 27. Maintenance / outage layer: desired future feature

Longer-term dashboard goal:

Add a toggle that visually highlights affected infrastructure.

Possible desired display:

```text
normal pipeline / station:
    normal existing colors

scheduled maintenance:
    orange

unscheduled outage / restriction:
    red
```

Ideally:

- affected pipeline segment changes color;
- related compressor station marker changes color;
- hover/click shows:
  - outage name
  - scheduled/unscheduled
  - start/end
  - capacity reduction
  - affected location
  - notes

This has not yet been implemented.

The eventual difficulty will be mapping maintenance bulletin facility names/IDs to AER/NGTL spatial objects.

---

# 28. ST37 / wells: future layer

ST37 data exists locally but is not yet integrated.

Future idea:

- display Alberta/BC/Saskatchewan gas wells;
- filter by company;
- group/bin wells geographically;
- possibly combine with production data;
- build production-region understanding alongside pipeline flows.

This is lower priority than compressor stations and maintenance.

---

# 29. Proposed long-term dashboard page structure

Eventually move from a single-page prototype to multi-page Streamlit navigation.

Planned pages:

```text
System Overview
Empress
McNeill
Alberta–BC
Gordondale
Groundbirch East
Willow Valley
Alberta Demand
Storage & Linepack
Data Quality
```

The current `app_v19_1.py` is still primarily the System Overview prototype.

---

# 30. Recommended immediate work for Claude

Suggested order:

## Step 1: Clean `app_v19_1.py`

Remove obsolete code from the abandoned callout-card iterations:

- `callout_positions`
- duplicate `relative_status()` assignments
- unused hover helper fields
- stale caption
- unused CSS for old `.metric-card` system if no longer needed
- dead helper functions such as `metric_card()` if not used anywhere

Do not alter behavior yet.

## Step 2: Verify current selection flow

Confirm:

```text
default RHS = Alberta System Balance
click marker = interconnect detail
AB button = reset to Alberta System Balance
```

Make selection state deterministic.

## Step 3: Verify signed-flow display

Check examples from the raw CSV:

```text
outbound should remain negative
inbound should remain positive
```

Ensure no unnecessary `.abs()` is used in main displayed values.

## Step 4: Keep magnitude comparison semantics

For relative-to-average activity:

```python
abs(current) - abs(avg)
```

Use:

```text
green = above average magnitude
red = below average magnitude
```

Clearly label these rows as magnitude comparisons.

## Step 5: Inspect source labels

Print/inspect unique:

```python
flows["Item"].unique()
ops["Metric"].unique()
```

Confirm all aliases currently resolve.

Do not blindly add more aliases unless necessary.

## Step 6: Add compressor stations

Inspect `Pipeline_Installations_SHP`, preprocess into lightweight GeoJSON, and add it to the System Overview.

---

# 31. Possible architecture improvement

The current app is becoming large.

A cleaner structure would be:

```text
NGTL Project/
│
├── app.py
├── download_gdsr.py
├── prepare_pipeline_layers.py
├── prepare_installation_layers.py
│
├── ngtl/
│   ├── __init__.py
│   ├── config.py
│   ├── loaders.py
│   ├── matching.py
│   ├── metrics.py
│   ├── geography.py
│   └── charts.py
│
├── gdsr/
├── processed/
├── assets/
├── Pipelines_SHP/
├── Pipeline_Installations_SHP/
└── ST37/
```

Suggested responsibilities:

```text
config.py
    paths, URLs, constants

loaders.py
    load compiled CSVs
    load GeoJSON

matching.py
    normalize_label
    resolve_name
    aliases

metrics.py
    snapshot
    MMcf/Bcf conversion
    sign/magnitude logic

geography.py
    border coordinates
    PyDeck layer construction

charts.py
    historical Plotly figures
```

Do not refactor until the current app behavior is confirmed stable.

---

# 32. Data-quality checks worth adding

Useful checks:

```text
1. duplicate GasDay + Item rows
2. missing GasDay dates
3. unresolved source labels
4. NaN extrapolated values
5. sudden sign reversals
6. extreme day-over-day jumps
7. NextDayGasDay consistency
8. duplicated SourceFile records
9. scraper dates present in gdsr/ but absent from processed CSV
10. latest local raw file vs latest compiled gas day
```

A future Data Quality page should surface these automatically.

---

# 33. Key design decisions already made

These decisions came from repeated iteration and should not be casually reversed:

```text
1. PyDeck for pipelines/geographic layers.
2. Plotly for historical charts.
3. Streamlit native metrics for RHS Alberta cards.
4. No persistent floating callout boxes around the map.
5. Purple, larger interconnect markers with direct labels.
6. Main flow values preserve TC Energy sign.
7. Relative activity uses absolute magnitude.
8. 14d and 30d averages are central dashboard context.
9. Raw TC CSVs remain untouched.
10. Process heavy GIS files once, not on every dashboard run.
```

---

# 34. Current visual direction

Desired look:

- dark dashboard
- relatively dense professional market-monitor style
- Alberta map is the visual focus
- pipelines should be visible but not overpower the metrics
- purple interconnect markers
- white labels
- clean native RHS metrics
- limited decorative elements
- high information density without clutter

An AEMO Gas Bulletin Board style map was an early visual reference, particularly the combination of system map + operating metrics, but the persistent geographic callout cards were abandoned because deck.gl text/card rendering did not produce a polished result.

---

# 35. Important warning for future edits

Before changing source-label aliases or flow semantics, inspect the actual compiled data.

Before changing station/pipeline field mappings, inspect the actual shapefile columns.

Before converting negative flows to absolute values, remember:

```text
negative = outbound
positive = inbound
```

Do not erase that direction information.

Use absolute values only where the metric explicitly means:

```text
flow magnitude
```

---

# 36. Current canonical files

Treat these as the current reference set unless newer local versions exist:

```text
Dashboard:
    /Users/willgirling/Desktop/NGTL Project/app_v19_1.py

Raw TC data:
    /Users/willgirling/Desktop/NGTL Project/gdsr/

Compiled flow history:
    /Users/willgirling/Desktop/NGTL Project/processed/ngtl_daily_flows.csv

Compiled operations:
    /Users/willgirling/Desktop/NGTL Project/processed/ngtl_operational_metrics.csv

Raw AER pipelines:
    /Users/willgirling/Desktop/NGTL Project/Pipelines_SHP/Pipelines_GCS_NAD83.shp

Processed NGTL pipelines:
    /Users/willgirling/Desktop/NGTL Project/processed/ngtl_operating_pipelines.geojson

Processed major gas lines:
    /Users/willgirling/Desktop/NGTL Project/processed/major_operating_gas_pipelines.geojson

Alberta boundary:
    /Users/willgirling/Desktop/NGTL Project/assets/alberta_boundary.geojson
```

---

# 37. Summary for the next coding agent

This is a functioning local NGTL-monitor prototype built around TC Energy daily Gas Day Summary Reports and AER pipeline GIS data.

The core data model and flow-sign logic are more important than preserving the exact current app code.

The next agent should:

```text
1. clean app_v19_1.py;
2. preserve current working behavior;
3. verify source labels and signs;
4. keep Alberta metrics as default RHS;
5. keep border/interconnect selection as the alternative RHS state;
6. add compressor stations next;
7. later implement maintenance/outage mapping;
8. consider a custom frontend component only if true hover-driven RHS updates are required.
```

The current file reflects many rapid visual iterations, so dead code should be expected. Refactor carefully after first confirming the live local app behavior.
