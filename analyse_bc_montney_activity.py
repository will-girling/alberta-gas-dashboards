"""BC Montney completion activity, from BCER frac records.

Why this is worth doing without production data
-----------------------------------------------
The LNG supply thesis rests on the Montney adding roughly 1.9 Bcf/d by
2030, of which about 1.3 is British Columbia. analyse_montney_supply.py
can only measure Alberta, because Petrinex publishes AB and SK but not
BC - every BC month returns HTTP 400.

BCER does publish frac records, and they carry two things that make an
activity analysis possible without any volumes:

  OBJECTIVE_FORMATION      names the target, so "MONTNEY" is an explicit
                           attribute rather than a geographic guess. This
                           is better attribution than the Alberta side of
                           the analysis has.
  OPS_EXPECTED_START_DATE  dates the completion.

Counting wells frac'd per period is the direct analogue of the Alberta
new-well count. It is also a *leading* indicator: a well frac'd today
produces months later, so activity turns before volumes do.

Two traps, both handled here
----------------------------
Reporting lag. Despite the field name, no record carries a future date -
these are backfilled as operations complete. Monthly counts fall off a
cliff at the data edge (June 6, July 3, August 1 against a ~30/month
run-rate) which reads as a collapse and is not one. So comparisons run
over Jan-April, well inside the reliable window, and the script prints
the monthly tail so the edge can be re-checked whenever the data is
refreshed.

Coverage window. The layer begins September 2021, so 2021 is partial and
is excluded from year-on-year comparisons. It appears to be a rolling
window rather than full history - do not treat it as the complete record
of BC fracturing.

One row per well authorization: records and distinct WA numbers differ by
six out of 2,164, so deduplication barely matters, but it is done anyway
so a re-frac cannot read as a new well.

Run
---
    python3 analyse_bc_montney_activity.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
FRACS = PROJECT_ROOT / "processed" / "bc_frac_activity.parquet"

# Jan-April. April is the last month that looks complete at the current
# data edge; check the monthly tail printed below before widening it.
WINDOW_END_MONTH = 4

# 2021 is a partial year - the layer starts in September.
FIRST_FULL_YEAR = 2022


def load() -> pd.DataFrame:
    if not FRACS.exists():
        raise SystemExit(
            f"{FRACS.name} not found - run "
            "prepare_bc_well_locations.py --download fracs"
        )
    frame = pd.read_parquet(FRACS)
    frame["start"] = pd.to_datetime(frame["OPS_EXPECTED_START_DATE"],
                                    errors="coerce")
    montney = frame[
        frame["OBJECTIVE_FORMATION"].astype(str).str.upper() == "MONTNEY"
    ].dropna(subset=["start"])
    # First frac per well authorization, so a re-frac is not a new well.
    return montney.sort_values("start").drop_duplicates("WA_NUM")


def report_edge(frame: pd.DataFrame) -> None:
    print("\nMonthly counts, last 14 months — check where reporting thins")
    monthly = frame.groupby(frame["start"].dt.to_period("M")).size().tail(14)
    for period, count in monthly.items():
        flag = "   <- thin, likely incomplete" if count < 15 else ""
        print(f"   {period}   {count:>4}{flag}")


def report_window(frame: pd.DataFrame) -> None:
    window = frame[frame["start"].dt.month <= WINDOW_END_MONTH]
    counts = window.groupby(window["start"].dt.year).size()
    counts = counts[counts.index >= FIRST_FULL_YEAR]

    print(f"\nBC Montney wells frac'd, January to "
          f"{'April' if WINDOW_END_MONTH == 4 else WINDOW_END_MONTH}")
    previous = None
    for year, count in counts.items():
        change = f"   {(count / previous - 1) * 100:+6.1f}% y/y" if previous else ""
        print(f"   {year}   {count:>4}{change}")
        previous = count

    if 2024 in counts.index:
        latest = counts.index.max()
        print(f"\n   {latest} vs the 2024 peak: "
              f"{(counts[latest] / counts[2024] - 1) * 100:+.0f}%")


def report_operators(frame: pd.DataFrame) -> None:
    window = frame[frame["start"].dt.month <= WINDOW_END_MONTH]
    table = window.pivot_table(
        index="OPERATOR_ABBREVIATION",
        columns=window["start"].dt.year,
        values="WA_NUM", aggfunc="count",
    ).fillna(0)

    years = [y for y in (2024, 2025, 2026) if y in table.columns]
    if len(years) < 2:
        return
    table = table[years]
    first, last = years[0], years[-1]

    print(f"\nBy operator, January to April ({first} vs {last})")
    print(f"   {'operator':22}" + "".join(f"{y:>7}" for y in years)
          + f"{'change':>10}")
    for name, row in table.sort_values(first, ascending=False).head(12).iterrows():
        change = (f"{(row[last] / row[first] - 1) * 100:>9.0f}%"
                  if row[first] else "         —")
        print(f"   {str(name)[:20]:22}"
              + "".join(f"{row[y]:>7.0f}" for y in years) + change)

    totals = table.sum()
    print(f"   {'TOTAL':22}" + "".join(f"{totals[y]:>7.0f}" for y in years)
          + f"{(totals[last] / totals[first] - 1) * 100:>9.0f}%")
    print(f"\n   operators active {first}: {(table[first] > 0).sum()}"
          f"   {last}: {(table[last] > 0).sum()}")
    falling = ((table[last] < table[first]) & (table[first] > 0)).sum()
    print(f"   operators cutting: {falling} of {(table[first] > 0).sum()}")


def report_depth(frame: pd.DataFrame) -> None:
    """Wells are not getting cheaper or shallower - so this is not a
    shift to smaller, cheaper wells. It is simply fewer of them."""
    print("\nMedian total depth by year, m")
    depth = frame.groupby(frame["start"].dt.year)["TD_DEPTH"].median()
    for year, value in depth.items():
        if year >= FIRST_FULL_YEAR:
            print(f"   {year}   {value:>6.0f}")


def main() -> None:
    frame = load()
    print(f"BC Montney frac records: {len(frame):,}")
    print(f"Coverage: {frame['start'].min().date()} to "
          f"{frame['start'].max().date()}")

    report_edge(frame)
    report_window(frame)
    report_operators(frame)
    report_depth(frame)

    print("\nNote: frac activity leads production by months, so this turns "
          "before volumes do. It is not a substitute for BC production "
          "data, which remains unavailable without a BCER account.")


if __name__ == "__main__":
    main()
