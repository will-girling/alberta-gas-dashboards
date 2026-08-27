"""Reconstruct NGTL outage history from archived snapshots.

The problem
-----------
processed/ngtl_outages.csv is a snapshot, not a history. Each download
returns what TC Energy currently publishes: outages in progress and
outages scheduled ahead. Anything that finished before the download
drops out. So a single file cannot tell you what maintenance was
running six months ago.

What can be recovered
---------------------
outages_raw/ keeps every JSON pull. Unioning them recovers any outage
that was live or scheduled at the moment of at least one snapshot, and
deduplicating on outage id keeps one row each. With snapshots from late
July 2026 the reconstructed window starts 2026-07-10 — the earliest
start date still visible in the oldest archived pull.

That is a short history today. It extends by one day for every daily
download, and it is the only way to build the series at all, since TC
publishes no archive. Nothing here is retroactive: outages that ended
before the first snapshot are gone for good.

Conflict handling
-----------------
The same outage appears in many snapshots and often changes - dates get
rescheduled, capability revised. The LAST snapshot containing an outage
wins, on the grounds that it is TC's most recent statement about it. The
count of revisions is kept so a heavily-rescheduled outage can be told
from a stable one.

Output
------
processed/ngtl_outage_history.csv

Run
---
    python3 prepare_outage_history.py
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
RAW_DIR = PROJECT_ROOT / "outages_raw"
OUTPUT = PROJECT_ROOT / "processed" / "ngtl_outage_history.csv"

E3M3D_TO_MMCFD = 0.0353147 * 1000


def find_records(payload) -> list[dict]:
    """TC wraps the outage list in {"message": ..., "data": [...]}."""
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, list) else []


def numeric(series: pd.Series) -> pd.Series:
    """Capability fields arrive as strings and often as the literal
    "N/A" rather than null, so a plain astype would raise and a plain
    to_numeric without coercion would too."""
    return pd.to_numeric(series.astype(str).str.strip(), errors="coerce")


def load_snapshots() -> pd.DataFrame:
    files = sorted(glob.glob(str(RAW_DIR / "outages_*.json")))
    if not files:
        raise SystemExit(f"no snapshots in {RAW_DIR}")

    rows: list[dict] = []
    for path in files:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as error:
            print(f"  skipped {Path(path).name}: {error}")
            continue
        for record in find_records(payload):
            if not isinstance(record, dict):
                continue
            # The nested area object carries the gate acronym - EGAT,
            # WGAT, USJR - which is what ties an outage to the flow
            # series rather than to a map pin.
            area = record.get("area") or {}
            rows.append({
                **{k: v for k, v in record.items() if not isinstance(v, (dict, list))},
                "area_acronym": area.get("acronym"),
                "area_name": area.get("name") or area.get("dopAcronym"),
                "snapshot": Path(path).stem[8:],
            })

    print(f"  {len(files)} snapshots, {len(rows):,} raw rows")
    return pd.DataFrame(rows)


def main() -> None:
    print("Rebuilding outage history from archived snapshots")
    raw = load_snapshots()

    raw["start"] = pd.to_datetime(raw.get("startDateTime"), errors="coerce")
    raw["end"] = pd.to_datetime(raw.get("endDateTime"), errors="coerce")
    raw = raw.dropna(subset=["start"])

    # areaBaseCapability is the normal capability of the area;
    # flowCapability is what remains during the outage. Both are
    # e3m3/d strings. localAreaBaseCapability looks like the right
    # field from its name but is "N/A" on all but 22 of 2,507 rows -
    # a trap worth recording.
    for column in ("flowCapability", "areaBaseCapability"):
        if column in raw.columns:
            raw[column] = numeric(raw[column])

    # One row per outage, last snapshot wins for dates and text.
    key = "outageId" if "outageId" in raw.columns else "id"
    raw = raw.sort_values("snapshot")
    revisions = raw.groupby(key).size().rename("snapshots_seen")
    outages = raw.drop_duplicates(key, keep="last").join(revisions, on=key)

    # Capability is different: TC populates it inconsistently, and the
    # most recent snapshot for an outage often omits it. Taking the last
    # snapshot's value verbatim discarded three quarters of the derates.
    # Carry the last NON-NULL value per outage instead.
    for column in ("flowCapability", "areaBaseCapability"):
        if column in raw.columns:
            latest = (raw.dropna(subset=[column])
                      .drop_duplicates(key, keep="last")
                      .set_index(key)[column])
            outages[column] = outages[key].map(latest)

    # Derate as a share of normal capability, which is the comparable
    # number - absolute capability varies by an order of magnitude
    # between a small lateral and the East Gate.
    base = outages.get("areaBaseCapability")
    during = outages.get("flowCapability")
    if base is not None and during is not None:
        outages["derate_pct"] = (
            (1 - during / base).clip(lower=0, upper=1) * 100
        ).round(1)
        outages["capability_lost_mmcfd"] = (
            (base - during).clip(lower=0) * E3M3D_TO_MMCFD / 1000
        ).round(1)

    outages["description"] = outages["description"].astype(str).str.strip()

    keep = [c for c in [
        key, "start", "end", "description", "impact",
        "area_acronym", "area_name", "areaId",
        "derate_pct", "capability_lost_mmcfd", "snapshots_seen",
        "areaBaseCapability", "flowCapability", "snapshot",
    ] if c in outages.columns]
    outages = outages[keep].sort_values("start")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    outages.to_csv(OUTPUT, index=False)

    print(f"\n  {len(outages):,} distinct outages")
    print(f"  window {outages['start'].min().date()} to "
          f"{outages['end'].max().date()}")
    if "derate_pct" in outages.columns:
        d = outages["derate_pct"].dropna()
        print(f"  derate measured on {len(d):,}: median {d.median():.1f}%, "
              f"{(d >= 25).sum():,} at 25%+, {(d >= 50).sum():,} at 50%+")
    if "area_acronym" in outages.columns:
        top = outages["area_acronym"].value_counts().head(6)
        print("  busiest areas: "
              + ", ".join(f"{k} {v}" for k, v in top.items()))
    print(f"  -> {OUTPUT.name}")
    print("\n  This window grows by one day per daily download and cannot "
          "be backfilled — TC publishes no archive.")


if __name__ == "__main__":
    main()
