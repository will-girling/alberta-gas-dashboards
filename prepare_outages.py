"""Normalise TC maintenance/service tracker exports into a time series.

Why segment-level
-----------------
The tracker names facilities ("Otter Lake - Compressor Station
Maintenance") but the AER installation data has no name field, so
outages cannot reliably be pinned to an individual compressor station.

They do not need to be. Every outage row already states the capacity
*table* it affects, and those tables correspond to gates and areas that
the CSR feed already measures:

    EGAT  East Gate            -> Empress + McNeill borders
    WGAT  West Gate            -> Alberta/BC + Alberta/Montana borders
    FHZ8  Foothills Zone 8     -> Alberta/BC border
    USJR  Upstream James River -> upstream receipts
    OSDA  Oil Sands Delivery Area
    NEDA  North East Delivery Area
    LCLR  local receipt point
    LCLD  local delivery point

That makes "what is the stated capability today, and what is actually
flowing" answerable directly, which is the question the dashboard exists
to answer.

Units
-----
Capability is published in 10^3 m3/d. Converted here to MMcf/d to match
CSR and GDSR. The conversion checks out against observed flow: EGAT
capability lands at ~96% utilisation versus measured Empress + McNeill.

Input
-----
outages/*.csv - tracker exports, dropped in as pulled. Files are read
in date order and de-duplicated on UID, so overlapping exports are safe.

Output
------
processed/ngtl_outages.csv - one row per outage per affected day.

Run
---
    python3 prepare_outages.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path("/Users/willgirling/Desktop/NGTL Project")
OUTAGE_DIR = PROJECT_ROOT / "outages"
RAW_DIR = PROJECT_ROOT / "outages_raw"
OUTPUT = PROJECT_ROOT / "processed" / "ngtl_outages.csv"

# 10^3 m3/d -> MMcf/d
E3M3_TO_MMCFD = 35.3147 / 1000

EXPECTED_COLUMNS = {
    "Outage Id", "Table", "Start", "End", "Capability",
    "Type of Restriction", "Description", "UID",
}

# Capacity table -> the CSR columns measuring the same physical flow.
# Areas with no direct CSR equivalent map to an empty list; they still
# carry a capability figure, just no measured counterpart.
TABLE_TO_CSR = {
    "EGAT": ["Empress Border Flow", "Mcneil Border Flow"],
    "WGAT": ["Alberta-BC Border Flow"],
    "FHZ8": ["Alberta-BC Border Flow"],
    "USJR": ["Total Receipts"],
    "OSDA": [],
    "NEDA": [],
    "LCLR": [],
    "LCLD": [],
}

# NGTL numbered segments, transcribed from the legend of TC's
# "NGTL System - Segment Codes & Project Areas" map (Feb 2025).
# 12, 25, 26 and 27 are absent from the map's own list.
SEGMENT_CODES = {
    1: "UPRM", 2: "PRLL", 3: "NWML", 4: "GRDL", 5: "WAEX", 6: "MRTN",
    7: "GPML", 8: "CENT", 9: "LPOL", 10: "LIEG", 11: "KIRB", 13: "REDL",
    14: "COLD", 15: "NLAT", 16: "ELAT", 17: "ALEG", 18: "BLEG",
    19: "EGAT", 20: "MLAT", 21: "WGAT", 22: "SLAT", 23: "WAIN",
    24: "JUDY", 28: "EDM",
}

# Pipeline names for those codes that appear on the companion
# "NGTL System - Pipeline Names" map legend. Codes without an entry are
# project/area codes rather than named pipelines.
SEGMENT_PIPELINE_NAME = {
    "GPML": "Grande Prairie Mainline",
    "NWML": "Northwest Mainline",
    "PRLL": "Peace River Lateral Loop",
    "PRML": "Peace River Mainline",
    "NLAT": "North Lateral",
    "SLAT": "South Lateral",
    "ELAT": "East Lateral",
    "MLAT": "Mainline Lateral",
    "EDSML": "Edson Mainline",
    "NCC": "North Central Corridor",
    "WAS": "Western Alberta System Mainline",
    "WASE": "Western Alberta System Mainline Extension",
    "CAS": "Central Alberta System Mainline",
    "EAS": "Eastern Alberta System Mainline",
}

# Severity is how far an outage derates a table below the base
# capability that would otherwise apply.
#
# The base comes from TC's own monthly capability series
# (processed/ngtl_area_capabilities.csv, built by
# prepare_outage_areas.py). That is the correct denominator: it is what
# TC itself publishes as the area's capability for that month.
#
# Where no base series exists - NEDA, and the local receipt/delivery
# tables, which TC does not publish a base for - the fallback is the
# highest capability observed for that table in the archive. The method
# used is recorded per row in severity_basis so the dashboard can say
# which it is rather than implying both are equally solid.
#
# The tracker's own Local Base/Outage Capability columns would be ideal
# but are populated on 1 of 91 rows.
AREA_CAPABILITY_FILE = PROJECT_ROOT / "processed" / "ngtl_area_capabilities.csv"

SEVERITY_SEVERE_PCT = 10.0
SEVERITY_MODERATE_PCT = 4.0

# Percent derate on its own is scale-blind, and on a map that is the
# difference between a finding and a false alarm. A meter station taken
# fully out of service is a 100% derate whether it normally flows 205
# MMcf/d (Aeco C Sales) or 0.2 (Whitesands Sales) - and both were
# rendering as the same maximum red.
#
# TC publishes typicalFlow alongside capability, so the volume actually
# at risk is available: typical flow less capability during the outage.
# Against an NGTL system moving roughly 15,000 MMcf/d, 100 MMcf/d is a
# little under a percent and worth a look; 25 is marginal; below that it
# is a local event that should not compete for attention.
VOLUME_SEVERE_MMCFD = 100.0
VOLUME_MODERATE_MMCFD = 25.0

# Below this, an outage is real but too small to be worth a colour.
# Two thirds of the meter-station outages sit under 3 MMcf/d - Whitesands
# Sales is 0.18 - and lumping them into "minor" put twenty-odd warning
# pins on the map for events that move nothing. "Minor" should mean
# measured and small, not measured and irrelevant.
VOLUME_NEGLIGIBLE_MMCFD = 5.0

# Shared ordering so the percent and volume grades can be compared.
SEVERITY_ORDER = {"negligible": 0, "minor": 1, "moderate": 2, "severe": 3}

# A facility's own observed history is only a usable stand-in for its
# normal capability once it has been seen at more than one capability.
# Seen once, its max is its only reading, so the implied derate is 0% by
# construction - a false "minor" rather than an honest "unknown".
MIN_OBSERVATIONS_FOR_BASE = 2

TABLE_LABEL = {
    "EGAT": "East Gate (Empress/McNeill)",
    "WGAT": "West Gate (AB/BC + AB/MT)",
    "FHZ8": "Foothills Zone 8 (AB/BC)",
    "USJR": "Upstream James River",
    "OSDA": "Oil Sands Delivery Area",
    "NEDA": "North East Delivery Area",
    "LCLR": "Local receipt point",
    "LCLD": "Local delivery point",
}


def parse_dates(raw: pd.Series) -> pd.Series:
    """CSV exports use "05-Aug-26"; the API uses ISO timestamps."""
    parsed = pd.to_datetime(raw, format="%d-%b-%y", errors="coerce")
    unparsed = parsed.isna() & raw.notna()
    if unparsed.any():
        parsed.loc[unparsed] = pd.to_datetime(
            raw.loc[unparsed], errors="coerce"
        )
    return parsed


def load_latest_api_publication() -> pd.DataFrame | None:
    """Newest publication downloaded by download_outages.py.

    Preferred over the CSV exports: an API publication is always the
    complete tracker, whereas a CSV export captures whatever was on
    screen and may be filtered. It also carries areaBaseCapability per
    row, which is a better severity denominator than the monthly series.
    """
    if not RAW_DIR.exists():
        return None

    files = sorted(RAW_DIR.glob("outages_*.json"))
    if not files:
        return None

    newest = files[-1]
    payload = json.loads(newest.read_text(encoding="utf-8"))
    records = payload.get("data") if isinstance(payload, dict) else payload
    if not records:
        return None

    frame = pd.DataFrame(records)
    frame["source_file"] = newest.name

    # Flatten the nested area object to the codes the rest of the
    # pipeline speaks: dopAcronym is the CSV's vocabulary (FHZ8).
    if "area" in frame.columns:
        frame["Table"] = frame["area"].apply(
            lambda v: (v or {}).get("dopAcronym") or (v or {}).get("acronym")
            if isinstance(v, dict) else None
        )

        # Plant turnarounds are a different kind of record and must not
        # be graded as maintenance with unknown severity.
        #
        # TC flags two areas - DPTA and RPTA - with isPlantTurnAround.
        # Their records carry no description, no facility and no
        # capability, only dates, a typicalFlow and a negative outageId.
        # That is deliberate: a third-party plant turnaround affects
        # receipts into the system, so TC has no pipeline capability
        # figure to publish for it.
        #
        # Read as ordinary outages they became 24 grey "severity
        # unknown" pins - the bulk of the grey on the map - implying a
        # measurement was missing when in fact none was ever offered.
        frame["plant_turnaround"] = frame["area"].apply(
            lambda v: bool((v or {}).get("isPlantTurnAround"))
            if isinstance(v, dict) else False
        )

    renamed = {
        "outageId": "Outage Id", "id": "UID", "flowCapability": "Capability",
        "typicalFlow": "Typical Flow",
        "impact": "Type of Restriction", "description": "Description",
        "startDateTime": "Start", "endDateTime": "End",
        "areaForStatedCapability": "Area for Stated Capability",
    }
    frame = frame.rename(columns={k: v for k, v in renamed.items()
                                  if k in frame.columns})

    # The API packs restriction and stated area into one field, e.g.
    # " Potential impact to FT-R; USJR " or
    # " Potential impact to FT-D; Segments 10, 11, and 14 ".
    # The CSV keeps them in separate columns, so split to match.
    if "Type of Restriction" in frame.columns:
        impact = frame["Type of Restriction"].fillna("").astype(str)
        split = impact.str.split(";", n=1)
        frame["Type of Restriction"] = split.str[0].str.strip()
        frame["Area for Stated Capability"] = (
            split.str[1].fillna("").str.strip().str.rstrip(";").str.strip()
        )

    print(f"  using API publication {newest.name}: {len(frame)} rows")
    return frame


def parse_typical_flow(values) -> pd.Series:
    """Typical flow in e3m3/d, from either source.

    The field is a string and is often a RANGE - the East Gate reports
    "340000-385000" - so a plain to_numeric would coerce the busiest
    areas on the system to NaN and quietly exempt them from any
    volume-based grading. Ranges take their midpoint.
    """
    series = pd.Series(values).astype(str).str.strip()

    lo = series.str.extract(r"^(-?[\d.]+)", expand=False)
    hi = series.str.extract(r"-\s*([\d.]+)\s*$", expand=False)
    lo = pd.to_numeric(lo, errors="coerce")
    hi = pd.to_numeric(hi, errors="coerce")

    return np.where(hi.notna(), (lo + hi) / 2, lo)


def load_exports() -> pd.DataFrame:
    if not OUTAGE_DIR.exists():
        raise SystemExit(
            f"No outages directory at {OUTAGE_DIR}. Create it and drop "
            "tracker exports in."
        )

    files = sorted(OUTAGE_DIR.glob("*.csv"))
    if not files:
        raise SystemExit(f"No CSV exports found in {OUTAGE_DIR}")

    frames = []
    for path in files:
        df = pd.read_csv(path, skipinitialspace=True)
        df.columns = [str(c).replace("﻿", "").strip() for c in df.columns]

        missing = EXPECTED_COLUMNS - set(df.columns)
        if missing:
            print(f"  SKIPPED {path.name}: missing {sorted(missing)}")
            continue

        df["source_file"] = path.name
        frames.append(df)
        print(f"  read {path.name}: {len(df)} rows")

    if not frames:
        raise SystemExit("No usable exports found.")

    return pd.concat(frames, ignore_index=True)


def main() -> None:
    raw = load_latest_api_publication()
    if raw is None:
        print(f"Reading tracker exports from {OUTAGE_DIR} ...")
        raw = load_exports()

    # UID is unique per outage-occurrence; keep the most recent pull.
    raw = raw.drop_duplicates(subset=["UID"], keep="last")

    df = pd.DataFrame({
        "outage_id": raw["Outage Id"],
        "uid": raw["UID"],
        "table_code": raw["Table"].astype(str).str.strip(),
        "start": parse_dates(raw["Start"]),
        "end": parse_dates(raw["End"]),
        "capability_e3m3d": pd.to_numeric(raw["Capability"], errors="coerce"),
        "restriction": raw["Type of Restriction"].astype(str).str.strip(),
        "area": raw.get("Area for Stated Capability", pd.NA),
        "description": raw["Description"].astype(str).str.strip(),
        "source_file": raw["source_file"],
        "typical_flow_e3m3d": parse_typical_flow(
            raw.get("Typical Flow", pd.NA)
        ),
        # Absent from the CSV exports, which carry no turnaround flag;
        # those rows default to False and grade normally.
        "plant_turnaround": (
            raw["plant_turnaround"].fillna(False).astype(bool)
            if "plant_turnaround" in raw.columns else False
        ),
    })

    df = df.dropna(subset=["start", "end"])
    df["capability_mmcfd"] = df["capability_e3m3d"] * E3M3_TO_MMCFD

    parts = df["description"].str.split(" - ", n=1)
    df["facility"] = parts.str[0].str.strip()
    df["work_type"] = parts.str[1].fillna("").str.strip()

    df["table_label"] = df["table_code"].map(TABLE_LABEL).fillna(df["table_code"])
    df["csr_columns"] = df["table_code"].map(
        lambda t: "|".join(TABLE_TO_CSR.get(t, []))
    )

    # --- impacted segments ------------------------------------------
    # "Area for Stated Capability" spells these out for the area tables,
    # e.g. "Segments 2, 3, 4, 5 and partial 7 (Upstream of Edson)".
    def parse_segments(area) -> list[int]:
        # pd.NA raises on truthiness, so test for null explicitly.
        if area is None or (not isinstance(area, str) and pd.isna(area)):
            return []
        text = str(area)
        if "segment" not in text.lower():
            return []
        return sorted({
            int(n) for n in re.findall(r"\b(\d{1,2})\b", text)
            if int(n) in SEGMENT_CODES
        })

    df["segment_numbers"] = df["area"].map(parse_segments)
    df["segment_codes"] = df["segment_numbers"].map(
        lambda nums: "|".join(SEGMENT_CODES[n] for n in nums)
    )
    df["segment_names"] = df["segment_numbers"].map(
        lambda nums: "|".join(
            SEGMENT_PIPELINE_NAME.get(SEGMENT_CODES[n], SEGMENT_CODES[n])
            for n in nums
        )
    )
    df["segment_numbers"] = df["segment_numbers"].map(
        lambda nums: "|".join(str(n) for n in nums)
    )

    # --- relative severity ------------------------------------------
    base = pd.Series(np.nan, index=df.index)
    basis = pd.Series("observed_max", index=df.index)

    # Best case: the API states the area's base capability on the row
    # itself, so severity needs no join at all.
    if "areaBaseCapability" in raw.columns:
        stated = pd.to_numeric(
            raw["areaBaseCapability"], errors="coerce"
        ).reindex(df.index) * E3M3_TO_MMCFD
        base = base.fillna(stated)
        basis = pd.Series(
            np.where(stated.notna(), "tc_row_base", basis), index=df.index
        )
        print(f"  base capability stated on {int(stated.notna().sum())}"
              f"/{len(df)} rows by the API")

    if AREA_CAPABILITY_FILE.exists():
        caps = pd.read_csv(AREA_CAPABILITY_FILE, parse_dates=["start", "end"])
        # Outage exports use the dopAcronym vocabulary (FHZ8), the area
        # feed uses the map acronym (FHBC). Accept either.
        lookup = {}
        for row in caps.itertuples():
            for key in {row.acronym, row.dop_acronym}:
                if isinstance(key, str):
                    lookup.setdefault(key, []).append(
                        (row.start, row.end, row.base_capability_mmcfd)
                    )

        def find_base(code, day):
            for start, end, value in lookup.get(code, []):
                if start <= day <= end:
                    return value
            return np.nan

        # Only fill gaps: a base stated on the row itself is more
        # specific than the month's figure for the whole area.
        monthly = df.apply(
            lambda r: find_base(r["table_code"], r["start"]), axis=1
        )
        filled = base.isna() & monthly.notna()
        base = base.fillna(monthly)
        basis = np.where(filled, "tc_monthly", basis)
        print(f"  monthly series filled {int(filled.sum())} further rows")
    else:
        print("  NOTE: no area capability file; falling back to observed max")

    # Last resort: infer normal capability from the facility's own
    # observed history.
    #
    # This used to group by table_code, which was wrong and badly so.
    # table_code is an area, not a facility, and an area like LCLR holds
    # 21 unrelated things — Saddle Hills C4 at 5,403 MMcf/d alongside the
    # NPS 8 Mitsue Lateral at 2.5. Taking the area's max as every member's
    # base told the NPS 20 Marten Hills Lateral that its normal capability
    # was Saddle Hills', so a routine 44 MMcf/d reading became a 99.2%
    # derate. That is why the map lit up almost entirely red: 55 of 70
    # currently-active rows were being graded against another facility.
    #
    # Grouping by facility removes the cross-facility comparison, but a
    # facility seen once cannot establish its own normal either — its max
    # IS its only reading, so the derate would be 0% and everything would
    # grade "minor". That is the same error inverted. So a facility must
    # have been seen at MIN_OBSERVATIONS_FOR_BASE distinct capabilities
    # before its history is trusted.
    #
    # Anything left over keeps base NaN, which grades "unknown". An
    # honest blank is worth more than a colour derived from an unrelated
    # asset — particularly on a map, where red reads as a finding.
    facility_key = df["table_code"].astype(str) + "|" + df["facility"].astype(str)
    grouped = df.groupby(facility_key)["capability_mmcfd"]
    observed_max = grouped.transform("max")
    distinct = grouped.transform("nunique")

    usable = (
        base.isna()
        & observed_max.notna()
        & (observed_max > 0)
        & (distinct >= MIN_OBSERVATIONS_FOR_BASE)
    )
    basis = pd.Series(np.where(usable, "observed_max", basis), index=df.index)
    basis = pd.Series(
        np.where(base.isna() & ~usable, "none", basis), index=df.index
    )
    base = pd.Series(base).where(~usable, observed_max)

    print(f"  base from facility history on {int(usable.sum())} rows; "
          f"{int((base.isna()).sum())} left ungraded")

    df["base_capability_mmcfd"] = base
    df["severity_basis"] = basis
    df["derate_pct"] = np.where(
        base > 0,
        ((1 - df["capability_mmcfd"] / base) * 100).clip(lower=0),
        np.nan,
    )

    def grade(pct: float) -> str:
        if pd.isna(pct):
            return "unknown"
        if pct >= SEVERITY_SEVERE_PCT:
            return "severe"
        if pct >= SEVERITY_MODERATE_PCT:
            return "moderate"
        return "minor"

    df["severity"] = df["derate_pct"].map(grade)

    # A stated capability of zero needs no base at all.
    #
    # Requiring a base to grade anything was an over-correction. If TC
    # says the facility's capability during the outage is 0, it is
    # flowing nothing - that is a full outage by definition, whatever its
    # normal capability happens to be. Most of these are meter stations
    # and short laterals taken entirely out of service, which is exactly
    # the maintenance worth seeing on a map.
    #
    # Zero must be distinguished from absent: a missing capability parses
    # to NaN, not 0, so only an explicitly stated zero qualifies.
    if "plant_turnaround" in df.columns:
        turn = df["plant_turnaround"].fillna(False).astype(bool)
        df.loc[turn, "severity"] = "turnaround"
        df.loc[turn, "severity_basis"] = "plant_turnaround"
        print(f"  {int(turn.sum())} rows are plant turnarounds "
              "(no pipeline capability published; not graded)")

    full = df["capability_mmcfd"].eq(0)
    df.loc[full, "derate_pct"] = 100.0
    df.loc[full, "severity"] = "severe"
    df.loc[full, "severity_basis"] = "zero_capability"
    print(f"  {int(full.sum())} rows fully out on a stated zero capability")

    # --- second dimension: how much gas is actually at risk ----------
    df["typical_flow_mmcfd"] = df["typical_flow_e3m3d"] * E3M3_TO_MMCFD
    df["volume_at_risk_mmcfd"] = (
        (df["typical_flow_mmcfd"] - df["capability_mmcfd"]).clip(lower=0)
    )

    def grade_volume(mmcfd: float) -> str:
        if pd.isna(mmcfd):
            return "unknown"
        if mmcfd >= VOLUME_SEVERE_MMCFD:
            return "severe"
        if mmcfd >= VOLUME_MODERATE_MMCFD:
            return "moderate"
        if mmcfd >= VOLUME_NEGLIGIBLE_MMCFD:
            return "minor"
        return "negligible"

    volume_grade = df["volume_at_risk_mmcfd"].map(grade_volume)

    # An outage is only as serious as its weaker dimension. A full
    # outage of a trivial meter station is a large fraction of nothing;
    # a 2% derate of the East Gate is a small fraction of a great deal.
    # Taking the lower of the two grades demands both before it will
    # show red, which is what makes the colour mean something.
    #
    # Where volume is unknown the percent grade stands alone rather than
    # being suppressed - absence of a typicalFlow is not evidence of a
    # small outage.
    graded = df["severity"].isin(("severe", "moderate", "minor", "negligible"))
    known = volume_grade.ne("unknown") & graded
    lower = np.where(
        df["severity"].map(SEVERITY_ORDER).fillna(0)
        <= volume_grade.map(SEVERITY_ORDER).fillna(0),
        df["severity"], volume_grade,
    )
    combined = pd.Series(lower, index=df.index)
    changed = known & combined.ne(df["severity"])
    df["severity"] = np.where(known, combined, df["severity"])
    df.loc[known, "severity_basis"] = (
        df.loc[known, "severity_basis"].astype(str) + "+volume"
    )
    print(f"  volume at risk known on {int(known.sum())} rows, "
          f"{int(changed.sum())} regraded by it")

    # Expand each outage to one row per affected gas day so the dashboard
    # can select by day without interval logic.
    expanded = []
    for row in df.itertuples():
        for day in pd.date_range(row.start, row.end, freq="D"):
            expanded.append({**row._asdict(), "gas_day": day})

    out = pd.DataFrame(expanded).drop(columns=["Index"])
    out = out.sort_values(["gas_day", "table_code", "facility"])

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT, index=False)

    print(f"\nwrote {len(out):,} outage-days ({df.shape[0]} outages) -> {OUTPUT.name}")
    print(f"  date range: {out.gas_day.min().date()} to {out.gas_day.max().date()}")
    print("\n  severity mix:", dict(out["severity"].value_counts()))
    print("  severity basis:", dict(out["severity_basis"].value_counts()))
    seg = out.loc[out["segment_codes"] != ""]
    print(f"  outage-days naming explicit segments: {len(seg)}")
    print("\n  by capacity table:")
    for code, grp in out.groupby("table_code"):
        cap = grp["capability_mmcfd"]
        mapped = "mapped" if TABLE_TO_CSR.get(code) else "no CSR counterpart"
        print(f"    {code:6} {len(grp):4d} days  "
              f"capability {cap.min():7,.0f}-{cap.max():7,.0f} MMcf/d  ({mapped})")


if __name__ == "__main__":
    main()
