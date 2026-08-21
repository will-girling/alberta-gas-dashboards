"""Alberta gas supply: base decline, new-well productivity, operators.

The three questions this answers
-------------------------------
1. What does the existing well base decline at, and how many new wells
   does Alberta need each month to hold production flat? This is the
   drilling treadmill, and it is the number everything else hangs off.
2. Is new-well productivity still improving? Average early-life rate by
   spud-year cohort says whether well quality is rising, flat, or
   rolling over.
3. Who is actually adding supply, and who is just holding on?

Method, and its limits
----------------------
Base decline is measured the way a reserves engineer would: take every
well producing twelve months ago, sum what those same wells produce
today, and the difference is legacy decline. It deliberately includes
shut-ins and workovers, because a barrel lost to a well being down is
lost the same as a barrel lost to reservoir pressure.

New supply is production from wells whose first observed month falls
inside the window.

The limit that matters: Petrinex publishes the current production year
plus four. A well drilled before that window starts has its early life
outside the data, so cohorts near the beginning are truncated and their
"early-life rate" is not comparable to a recent cohort's. The script
refuses to report a cohort whose first months are missing rather than
quietly comparing a well's month 30 against another's month 3.

Output
------
processed/ab_supply_analysis.xlsx   one sheet per question
printed summary                     the numbers worth quoting

Run
---
    python3 analyse_ab_supply.py
    python3 analyse_ab_supply.py --play montney
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

# Resolve relative to this file so the app runs anywhere -
# a laptop, a container, or Streamlit Community Cloud.
PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE = PROJECT_ROOT / "processed" / "ab_well_production.parquet"
LOCATED = PROJECT_ROOT / "processed" / "ab_well_production_located.parquet"
OUTPUT = PROJECT_ROOT / "processed" / "ab_supply_analysis.xlsx"

# Months of early life used to compare cohorts. Six is long enough to
# see past flowback noise and short enough that recent wells qualify.
EARLY_MONTHS = 6

# A cohort needs this many wells before its average means anything.
MIN_COHORT = 25


def load() -> pd.DataFrame:
    if not SOURCE.exists():
        raise SystemExit(
            f"{SOURCE.name} not found - run download_petrinex_volumes.py"
        )
    frame = pd.read_parquet(SOURCE, columns=[
        "production_month", "product_class", "well_id", "operator",
        "rate_mmcfd", "volume_mmcf",
    ])
    frame = frame[frame["product_class"] == "GAS"].copy()
    frame["month"] = pd.PeriodIndex(frame["production_month"], freq="M")
    return frame


def base_decline(frame: pd.DataFrame) -> pd.DataFrame:
    """Year-over-year decline of the well base, month by month."""
    monthly = frame.groupby(["month", "well_id"])["rate_mmcfd"].sum()
    rows = []

    months = sorted(frame["month"].unique())
    for month in months:
        prior = month - 12
        if prior < months[0]:
            continue

        then = monthly.loc[prior]
        now = monthly.loc[month] if month in monthly.index.levels[0] else None
        if now is None:
            continue

        survivors = now.reindex(then.index).fillna(0.0)
        legacy_then = float(then.sum())
        legacy_now = float(survivors.sum())

        # Anything producing now that was not in the base a year ago.
        new_supply = float(now.sum()) - legacy_now

        rows.append({
            "month": str(month),
            "base_a_year_ago": legacy_then,
            "same_wells_now": legacy_now,
            "decline_pct": (1 - legacy_now / legacy_then) * 100
            if legacy_then else np.nan,
            "new_well_supply": new_supply,
            "total_now": float(now.sum()),
            "wells_a_year_ago": int((then > 0).sum()),
            "of_those_still_on": int((survivors > 0).sum()),
        })

    return pd.DataFrame(rows)


def well_age_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Months on production for every well-month."""
    first = frame.groupby("well_id")["month"].min().rename("first_month")
    aged = frame.join(first, on="well_id")
    aged["age_months"] = (
        aged["month"].astype("int64") - aged["first_month"].astype("int64")
    )
    return aged


def vintage_curves(aged: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Average rate by months-on-production, per first-production year.

    Cohorts whose first month equals the start of the archive are
    dropped: those wells were already producing when the window opens,
    so their apparent 'month 0' is really some unknown later month.
    """
    window_start = aged["month"].min()
    aged = aged.copy()
    aged["cohort"] = aged["first_month"].dt.year

    truncated = aged.loc[aged["first_month"] == window_start, "cohort"]
    dropped = sorted(truncated.unique())
    aged = aged[aged["first_month"] > window_start]

    curve = (
        aged[aged["age_months"] <= 24]
        .groupby(["cohort", "age_months"])["rate_mmcfd"]
        .agg(["mean", "median", "count"])
        .reset_index()
    )

    early = aged[aged["age_months"] < EARLY_MONTHS]
    summary = early.groupby("cohort").agg(
        wells=("well_id", "nunique"),
        mean_rate=("rate_mmcfd", "mean"),
        median_rate=("rate_mmcfd", "median"),
        p90_rate=("rate_mmcfd", lambda s: s.quantile(0.9)),
    ).reset_index()
    summary = summary[summary["wells"] >= MIN_COHORT]
    summary.attrs["dropped_cohorts"] = dropped
    return curve, summary


def operator_scorecard(frame: pd.DataFrame, aged: pd.DataFrame) -> pd.DataFrame:
    latest = frame["month"].max()
    prior = latest - 12

    now = frame[frame["month"] == latest].groupby("operator")["rate_mmcfd"].sum()
    then = frame[frame["month"] == prior].groupby("operator")["rate_mmcfd"].sum()

    new_wells = (
        aged[(aged["month"] == latest) & (aged["first_month"] > prior)]
        .groupby("operator")
        .agg(new_well_rate=("rate_mmcfd", "sum"),
             new_wells=("well_id", "nunique"))
    )

    board = pd.DataFrame({"rate_now": now, "rate_year_ago": then}).fillna(0.0)
    board = board.join(new_wells).fillna(0.0)
    board["growth_pct"] = np.where(
        board["rate_year_ago"] > 0,
        (board["rate_now"] / board["rate_year_ago"] - 1) * 100,
        np.nan,
    )
    # How much of today's output comes from wells added in the year -
    # a high number means the operator is running hard to stand still.
    board["from_new_wells_pct"] = np.where(
        board["rate_now"] > 0,
        board["new_well_rate"] / board["rate_now"] * 100,
        np.nan,
    )
    board["share_of_ab_pct"] = board["rate_now"] / board["rate_now"].sum() * 100
    return board.sort_values("rate_now", ascending=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=25,
                        help="operators to print")
    args = parser.parse_args()

    frame = load()
    months = sorted(frame["month"].unique())
    print(f"Alberta gas, {len(frame):,} well-months")
    print(f"  {months[0]} to {months[-1]}  ({len(months)} months)")
    print(f"  {frame['well_id'].nunique():,} wells, "
          f"{frame['operator'].nunique():,} operators")

    if len(months) < 18:
        print("\n  WARNING only "
              f"{len(months)} months available. Base decline needs at "
              "least 13 and reads better with 24+. Re-run "
              "download_petrinex_volumes.py --months 60.")

    decline = base_decline(frame)
    aged = well_age_table(frame)
    curve, cohorts = vintage_curves(aged)
    board = operator_scorecard(frame, aged)

    if not decline.empty:
        latest = decline.iloc[-1]
        print("\n=== 1. BASE DECLINE AND THE TREADMILL")
        print(f"  Wells producing {latest['month']} a year earlier made "
              f"{latest['base_a_year_ago']:,.0f} MMcf/d")
        print(f"  Those same wells now make "
              f"{latest['same_wells_now']:,.0f} MMcf/d")
        print(f"  -> base decline {latest['decline_pct']:.1f}% a year")
        print(f"  New wells added {latest['new_well_supply']:,.0f} MMcf/d, "
              f"holding the total at {latest['total_now']:,.0f}")
        gap = latest["new_well_supply"] - (
            latest["base_a_year_ago"] - latest["same_wells_now"]
        )
        print(f"  Net {gap:+,.0f} MMcf/d: new supply "
              f"{'more than offset' if gap > 0 else 'did not offset'} decline")
        print(f"  Of {latest['wells_a_year_ago']:,} wells producing a year "
              f"ago, {latest['of_those_still_on']:,} still are")

        print("\n  decline by month:")
        for row in decline.tail(6).itertuples():
            print(f"    {row.month}  {row.decline_pct:>5.1f}%   "
                  f"new wells {row.new_well_supply:>7,.0f} MMcf/d")

    if not cohorts.empty:
        print(f"\n=== 2. NEW-WELL PRODUCTIVITY (first {EARLY_MONTHS} months)")
        dropped = cohorts.attrs.get("dropped_cohorts") or []
        if dropped:
            print(f"  cohort(s) {dropped} dropped: already producing when "
                  "the archive opens, so their early life is not observed")
        print(f"  {'cohort':>8}{'wells':>8}{'mean':>10}{'median':>10}"
              f"{'p90':>10}   MMcf/d")
        for row in cohorts.itertuples():
            print(f"  {int(row.cohort):>8}{int(row.wells):>8,}"
                  f"{row.mean_rate:>10.2f}{row.median_rate:>10.2f}"
                  f"{row.p90_rate:>10.2f}")
        if len(cohorts) > 1:
            first_c, last_c = cohorts.iloc[0], cohorts.iloc[-1]
            change = (last_c["median_rate"] / first_c["median_rate"] - 1) * 100
            print(f"\n  median early rate {int(first_c['cohort'])} -> "
                  f"{int(last_c['cohort'])}: {change:+.0f}%")

    print(f"\n=== 3. OPERATORS (top {args.top} by current gas)")
    print(f"  {'operator':<38}{'MMcf/d':>9}{'share':>7}{'y/y':>8}"
          f"{'from new':>10}")
    for name, row in board.head(args.top).iterrows():
        print(f"  {str(name)[:36]:<38}{row['rate_now']:>9,.0f}"
              f"{row['share_of_ab_pct']:>6.1f}%{row['growth_pct']:>7.0f}%"
              f"{row['from_new_wells_pct']:>9.0f}%")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        with pd.ExcelWriter(OUTPUT) as writer:
            decline.to_excel(writer, sheet_name="base_decline", index=False)
            cohorts.to_excel(writer, sheet_name="vintage_summary", index=False)
            curve.to_excel(writer, sheet_name="vintage_curves", index=False)
            board.to_excel(writer, sheet_name="operators")
        print(f"\nwrote {OUTPUT.name}")
    except Exception as exc:
        print(f"\ncould not write Excel ({exc}); writing CSVs instead")
        for name, table in [
            ("base_decline", decline), ("vintage_summary", cohorts),
            ("vintage_curves", curve), ("operators", board),
        ]:
            table.to_csv(OUTPUT.with_name(f"ab_{name}.csv"))


if __name__ == "__main__":
    main()
