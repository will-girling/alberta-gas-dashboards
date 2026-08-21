"""Diff TC outage publications to surface what actually changed.

Why
---
A published maintenance schedule is largely priced in by the time you
read it. The tradeable information is not "what is on the calendar" but
"what moved since the last publication": an outage appearing, extending,
deepening, or being cancelled.

TC republishes the whole tracker each evening (see the publisheddates
endpoint - roughly one publication per business day back to 2020), so
every pull is a full snapshot. Comparing consecutive snapshots on UID
recovers the change log TC does not publish directly.

Input
-----
outages/*.csv       tracker CSV exports. The publication timestamp is
                    taken from the filename (2026_08_05_15_37_58.csv),
                    falling back to file modification time.
outages_raw/*.json  raw API pulls, if download_outages.py has been run.

Both are accepted so this works whether outages arrive by hand or by
scraper.

Output
------
processed/ngtl_outage_changes.csv   one row per changed outage
processed/ngtl_publications.csv     inventory of publications seen

Change types
------------
new           UID absent from the previous publication
removed       UID present before, gone now (cancelled or completed)
extended      end date later than before
shortened     end date earlier than before
rescheduled   start date moved
deepened      capability lower than before (worse)
eased         capability higher than before (better)
reclassified  restriction wording changed (e.g. to "Potential impact
              to FT-R") - the commercial signal, independent of size

A single outage can carry several change types; they are recorded as a
pipe-joined list.

Run
---
    python3 prepare_outage_changes.py
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path("/Users/willgirling/Desktop/NGTL Project")
OUTAGE_DIR = PROJECT_ROOT / "outages"
RAW_DIR = PROJECT_ROOT / "outages_raw"
CHANGES_OUTPUT = PROJECT_ROOT / "processed" / "ngtl_outage_changes.csv"
PUBLICATIONS_OUTPUT = PROJECT_ROOT / "processed" / "ngtl_publications.csv"

E3M3_TO_MMCFD = 35.3147 / 1000

# Filenames look like 2026_08_05_15_37_58.csv
FILENAME_STAMP = re.compile(r"(\d{4})_(\d{2})_(\d{2})_(\d{2})_(\d{2})_(\d{2})")

# Capability moves smaller than this are treated as noise rather than a
# real derate change; TC rounds published figures.
CAPABILITY_TOLERANCE_MMCFD = 1.0

# The CSV export and the JSON API describe the same outages with
# different field names, so both vocabularies are accepted.
COLUMN_ALIASES = {
    "outage_id": ["Outage Id", "OutageId", "outage_id", "outageId"],
    "table_code": ["Table", "table", "table_code", "tableCode"],
    "start": ["Start", "start", "startDate", "startDateTime"],
    "end": ["End", "end", "endDate", "endDateTime"],
    "capability": ["Capability", "capability", "flowCapability"],
    "base_capability": ["areaBaseCapability", "Local Base Capability"],
    "restriction": [
        "Type of Restriction", "restriction", "typeOfRestriction", "impact",
    ],
    "description": ["Description", "description"],
    "area_text": ["Area for Stated Capability", "areaForStatedCapability"],
    "published": ["publishedDateTimeUtc", "published"],
}


def pick(frame: pd.DataFrame, key: str) -> pd.Series:
    for candidate in COLUMN_ALIASES[key]:
        if candidate in frame.columns:
            return frame[candidate]
    return pd.Series([pd.NA] * len(frame), index=frame.index)


def publication_stamp(path: Path) -> pd.Timestamp:
    match = FILENAME_STAMP.search(path.name)
    if match:
        return pd.Timestamp(datetime(*(int(g) for g in match.groups())))
    return pd.Timestamp(path.stat().st_mtime, unit="s").round("s")


def area_acronym(frame: pd.DataFrame) -> pd.Series:
    """Capacity-table code, from either vocabulary.

    The CSV states it directly in "Table"; the JSON nests it inside an
    "area" object, where dopAcronym is the code the CSV uses (FHZ8)
    and acronym is the map's (FHBC).
    """
    if "area" in frame.columns and frame["area"].apply(
        lambda v: isinstance(v, dict)
    ).any():
        return frame["area"].apply(
            lambda v: str(
                (v or {}).get("dopAcronym") or (v or {}).get("acronym") or ""
            ).strip() if isinstance(v, dict) else ""
        )
    return pick(frame, "table_code").astype(str).str.strip()


def normalise(frame: pd.DataFrame, published: pd.Timestamp,
              source: str) -> pd.DataFrame:
    # The JSON states its own publication time; trust that over the
    # filename, which is only a fallback for hand-saved CSV exports.
    stated = pick(frame, "published")
    if stated.notna().any():
        parsed = pd.to_datetime(stated, errors="coerce").dropna()
        if len(parsed):
            published = parsed.iloc[0]

    out = pd.DataFrame({
        "published": published,
        "source_file": source,
        "outage_id": pick(frame, "outage_id").astype(str).str.strip(),
        "table_code": area_acronym(frame),
        "restriction": (
            pick(frame, "restriction").astype(str)
            .str.replace(r"\s+", " ", regex=True).str.strip()
        ),
        "description": pick(frame, "description").astype(str).str.strip(),
        "area": pick(frame, "area_text").astype(str).str.strip(),
    })

    for field in ("start", "end"):
        raw = pick(frame, field)
        # CSV exports use "05-Aug-26"; the API uses ISO. Parse the common
        # form first and only fall back for what it could not read, so a
        # well-formed file never triggers dateutil's per-element path.
        parsed = pd.to_datetime(raw, format="%d-%b-%y", errors="coerce")
        unparsed = parsed.isna() & raw.notna()
        if unparsed.any():
            parsed.loc[unparsed] = pd.to_datetime(
                raw.loc[unparsed], errors="coerce"
            )
        out[field] = parsed

    capability = pd.to_numeric(pick(frame, "capability"), errors="coerce")
    out["capability_mmcfd"] = capability * E3M3_TO_MMCFD

    base = pd.to_numeric(pick(frame, "base_capability"), errors="coerce")
    out["base_capability_mmcfd"] = base * E3M3_TO_MMCFD

    parts = out["description"].str.split(" - ", n=1)
    out["facility"] = parts.str[0].str.strip()
    out["work_type"] = parts.str[1].fillna("").str.strip()

    # RPTA/DPTA are plant-turnaround aggregates with no facility named.
    blank = out["facility"].isin(["", "nan", "None", "<NA>"]) | out["facility"].isna()
    out.loc[blank, "facility"] = out.loc[blank, "table_code"].map(
        {"RPTA": "Plant turnaround (receipt)",
         "DPTA": "Plant turnaround (delivery)"}
    ).fillna("(unnamed)")

    # Identity across publications. The JSON's own "id" is regenerated
    # every publication (verified: zero overlap between two pulls), so it
    # cannot be used. Outage + capacity table + start date is stable and
    # unique within a publication, and works for both vocabularies.
    out["uid"] = (
        out["outage_id"] + "|" + out["table_code"] + "|"
        + out["start"].dt.strftime("%Y-%m-%d").fillna("?")
    )

    return out.loc[out["outage_id"].notna() & (out["outage_id"] != "")]


def load_publications() -> pd.DataFrame:
    frames = []

    for path in sorted(OUTAGE_DIR.glob("*.csv")) if OUTAGE_DIR.exists() else []:
        try:
            raw = pd.read_csv(path, skipinitialspace=True)
        except Exception as exc:
            print(f"  SKIPPED {path.name}: {exc}")
            continue
        raw.columns = [str(c).replace("﻿", "").strip() for c in raw.columns]
        frames.append(normalise(raw, publication_stamp(path), path.name))
        print(f"  {path.name}: {len(raw)} rows")

    for path in sorted(RAW_DIR.glob("*.json")) if RAW_DIR.exists() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  SKIPPED {path.name}: {exc}")
            continue
        records = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(records, list) or not records:
            print(f"  SKIPPED {path.name}: no records")
            continue
        frames.append(
            normalise(pd.DataFrame(records), publication_stamp(path), path.name)
        )
        print(f"  {path.name}: {len(records)} rows")

    if not frames:
        raise SystemExit(
            f"No publications found in {OUTAGE_DIR} or {RAW_DIR}."
        )

    everything = pd.concat(frames, ignore_index=True)

    # A CSV export is whatever was on screen when it was saved and can be
    # filtered; an API publication is always the full tracker. Diffing one
    # against the other invents changes. When API publications exist they
    # are used exclusively, and the CSVs stay as a fallback for periods
    # with no API pull.
    from_api = everything["source_file"].str.endswith(".json")
    if from_api.any() and (~from_api).any():
        dropped = everything.loc[~from_api, "source_file"].nunique()
        print(f"\n  ignoring {dropped} CSV export(s): API publications are "
              "complete, CSV exports may be filtered")
        everything = everything.loc[from_api]

    return everything


def diff(previous: pd.DataFrame, latest: pd.DataFrame) -> pd.DataFrame:
    before = previous.set_index("uid")
    after = latest.set_index("uid")

    rows = []

    for uid in after.index.difference(before.index):
        row = after.loc[uid]
        rows.append({**row.to_dict(), "uid": uid, "change": "new",
                     "detail": "not in previous publication"})

    for uid in before.index.difference(after.index):
        row = before.loc[uid]
        rows.append({**row.to_dict(), "uid": uid, "change": "removed",
                     "detail": "dropped from the tracker"})

    for uid in after.index.intersection(before.index):
        now, was = after.loc[uid], before.loc[uid]
        changes, details = [], []

        if pd.notna(now["end"]) and pd.notna(was["end"]):
            delta = (now["end"] - was["end"]).days
            if delta > 0:
                changes.append("extended")
                details.append(f"end +{delta}d")
            elif delta < 0:
                changes.append("shortened")
                details.append(f"end {delta}d")

        if pd.notna(now["start"]) and pd.notna(was["start"]):
            delta = (now["start"] - was["start"]).days
            if delta != 0:
                changes.append("rescheduled")
                details.append(f"start {delta:+d}d")

        if pd.notna(now["capability_mmcfd"]) and pd.notna(was["capability_mmcfd"]):
            delta = now["capability_mmcfd"] - was["capability_mmcfd"]
            if abs(delta) > CAPABILITY_TOLERANCE_MMCFD:
                changes.append("deepened" if delta < 0 else "eased")
                details.append(f"capability {delta:+,.0f} MMcf/d")

        if str(now["restriction"]) != str(was["restriction"]):
            changes.append("reclassified")
            details.append(f"{was['restriction']} -> {now['restriction']}")

        if changes:
            rows.append({**now.to_dict(), "uid": uid,
                         "change": "|".join(changes),
                         "detail": " · ".join(details)})

    if not rows:
        return pd.DataFrame()

    frame = pd.DataFrame(rows)

    # The identity includes the start date, so a rescheduled outage
    # arrives here as a removed row plus a new row. Pair those back up on
    # outage + capacity table and relabel, otherwise a simple date move
    # reads as a cancellation and an unrelated new outage.
    frame["_pair"] = frame["outage_id"].astype(str) + "|" + \
        frame["table_code"].astype(str)
    gone = frame.loc[frame["change"] == "removed"].set_index("_pair")
    fresh = frame.loc[frame["change"] == "new"].set_index("_pair")
    paired = gone.index.intersection(fresh.index)

    if len(paired):
        for key in paired:
            was = gone.loc[key]
            now = fresh.loc[key]
            if isinstance(was, pd.DataFrame) or isinstance(now, pd.DataFrame):
                continue                      # ambiguous, leave as-is
            shift = (
                (now["start"] - was["start"]).days
                if pd.notna(now["start"]) and pd.notna(was["start"]) else None
            )
            mask = (frame["_pair"] == key) & (frame["change"] == "new")
            frame.loc[mask, "change"] = "rescheduled"
            frame.loc[mask, "detail"] = (
                f"start {shift:+d}d (was {was['start']:%b %d})"
                if shift is not None else "start moved"
            )
            frame = frame.loc[
                ~((frame["_pair"] == key) & (frame["change"] == "removed"))
            ]

    frame = frame.drop(columns="_pair")
    frame["previous_published"] = previous["published"].iloc[0]
    return frame


def main() -> None:
    print(f"Reading publications from {OUTAGE_DIR} and {RAW_DIR} ...")
    everything = load_publications()

    everything = everything.sort_values(["published", "uid"])
    stamps = sorted(everything["published"].unique())
    print(f"\n{len(stamps)} publication(s): "
          f"{pd.Timestamp(stamps[0]):%Y-%m-%d %H:%M}"
          + (f" to {pd.Timestamp(stamps[-1]):%Y-%m-%d %H:%M}"
             if len(stamps) > 1 else ""))

    inventory = (
        everything.groupby(["published", "source_file"])
        .agg(outages=("uid", "nunique"),
             tables=("table_code", "nunique"))
        .reset_index()
        .sort_values("published")
    )
    PUBLICATIONS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    inventory.to_csv(PUBLICATIONS_OUTPUT, index=False)
    print(f"wrote publication inventory -> {PUBLICATIONS_OUTPUT.name}")

    if len(stamps) < 2:
        CHANGES_OUTPUT.write_text(
            "published,previous_published,uid,outage_id,table_code,facility,"
            "work_type,change,detail,start,end,capability_mmcfd,restriction\n",
            encoding="utf-8",
        )
        print(
            "\nOnly one publication available, so there is nothing to diff "
            "yet.\nWrote an empty changes file so the dashboard has "
            "something to read.\nDrop a second export into outages/ (or run "
            "download_outages.py) and re-run."
        )
        return

    latest_stamp, previous_stamp = stamps[-1], stamps[-2]
    latest = everything.loc[everything["published"] == latest_stamp]
    previous = everything.loc[everything["published"] == previous_stamp]

    changes = diff(previous, latest)
    if changes.empty:
        print("\nNo changes between the two most recent publications.")
        changes = pd.DataFrame(columns=[
            "published", "previous_published", "uid", "outage_id",
            "table_code", "facility", "work_type", "change", "detail",
            "start", "end", "capability_mmcfd", "restriction",
        ])
    else:
        keep = [
            "published", "previous_published", "uid", "outage_id",
            "table_code", "facility", "work_type", "change", "detail",
            "start", "end", "capability_mmcfd", "restriction",
        ]
        changes = changes[[c for c in keep if c in changes.columns]]

    changes.to_csv(CHANGES_OUTPUT, index=False)

    print(f"\ncomparing {pd.Timestamp(previous_stamp):%Y-%m-%d %H:%M} "
          f"-> {pd.Timestamp(latest_stamp):%Y-%m-%d %H:%M}")
    print(f"wrote {len(changes)} change(s) -> {CHANGES_OUTPUT.name}")
    if len(changes):
        tally = (
            changes["change"].str.split("|").explode().value_counts().to_dict()
        )
        print(f"  by type: {tally}")


if __name__ == "__main__":
    main()
