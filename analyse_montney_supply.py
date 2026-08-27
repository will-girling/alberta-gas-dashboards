"""Alberta Montney supply elasticity — evidence for the LNG thesis.

The question
------------
Peters forecasts WCSB supply rising 19.7 -> 22.2 Bcf/d between 2026 and
2030, with the Montney carrying roughly 1.9 Bcf/d of that. The thesis
worth testing is not whether the Montney *can* grow, but how quickly and
cheaply it responds as LNG removes gas from the basin.

What this can and cannot answer
-------------------------------
Petrinex is Alberta only. Of Peters' 2.5 Bcf/d of WCSB growth, roughly
1.3 comes from BC Montney, which is invisible here. Testable from this
data: Alberta Montney (+0.6) and Duvernay (+0.3) — about 36% of the
forecast. Every conclusion below is therefore about the *Alberta* half
of the Montney, which is the smaller and more mature half.

Method notes that matter
------------------------
Operator attribution is unusable for growth. Pipestone, Hammerhead and
Paramount all fall to exactly zero between 2022 and 2026 because they
were acquired, not because they stopped producing. That is the same
substitution problem the thesis identifies in the Shell/ARC case, showing
up in the data. So growth is decomposed by *well vintage* instead, which
is immune to corporate transactions.

Productivity is measured at fixed age on complete windows only. A well
that has produced four months is excluded from a twelve-month
comparison rather than annualised — otherwise recent vintages are
measured on their flush period and flattered.

Lateral length is approximated as total depth minus true vertical depth
from ST37. It is a proxy, but a reliable one for horizontals, and
without it longer laterals masquerade as better rock.

Comparisons are H1-over-H1. Alberta gas is strongly seasonal and the
data ends in June 2026, so full-year averages would compare six winter-
weighted months against twelve.

Run
---
    python3 analyse_montney_supply.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import ab_plays

PROJECT_ROOT = Path(__file__).resolve().parent
PROCESSED = PROJECT_ROOT / "processed"
HISTORY = PROCESSED / "ab_well_production.parquet"
LOCATED = PROCESSED / "ab_well_production_located.parquet"

PLAY = "Montney (Alberta)"

# Peters: Alberta Montney 3.4 -> 4.0 Bcf/d, 2026 to 2030.
PETERS_CAGR = (4.0 / 3.4) ** 0.25 - 1

# Horizontals only, and a sanity band that excludes bad depth records.
LATERAL_MIN_M, LATERAL_MAX_M = 500, 7000

H1 = ("01", "02", "03", "04", "05", "06")


def montney_gas_history() -> pd.DataFrame:
    """Monthly Montney gas by well, 2022-2026, with lateral length.

    Locations come from the most recent month's ST37 join and are mapped
    back across history by well_id. Coverage runs 94.5% of gas volume in
    early 2022 to 100% now; the gap is wells that died before the join
    month. That biases early production slightly low, which slightly
    overstates measured growth — worth stating, too small to matter.
    """
    loc = pd.read_parquet(
        LOCATED,
        columns=["well_id", "BH_Latitude", "BH_Longitude",
                 "Final_Total_Depth", "Max_True_Vertical_Depth"],
    ).drop_duplicates("well_id")
    loc["play"] = ab_plays.assign(loc, "BH_Latitude", "BH_Longitude")
    loc["lateral_m"] = (
        pd.to_numeric(loc["Final_Total_Depth"], errors="coerce")
        - pd.to_numeric(loc["Max_True_Vertical_Depth"], errors="coerce")
    )
    loc = loc.loc[loc["play"] == PLAY, ["well_id", "lateral_m"]]

    gas = pd.read_parquet(
        HISTORY,
        columns=["production_month", "product_class", "rate_mmcfd",
                 "operator", "well_id"],
        filters=[("product_class", "==", "GAS")],
    )
    gas = gas[gas["well_id"].isin(set(loc["well_id"]))].copy()
    gas["month"] = gas["production_month"].astype(str)

    # A well can report through several facilities in a month.
    gas = gas.groupby(["month", "well_id", "operator"],
                      observed=True, as_index=False)["rate_mmcfd"].sum()

    first = (
        gas[gas["rate_mmcfd"] > 0]
        .groupby("well_id")["month"].min().rename("first_month")
    )
    gas = gas.join(first, on="well_id").merge(loc, on="well_id")
    gas["vintage"] = gas["first_month"].str[:4]
    gas["age"] = (
        gas["month"].str[:4].astype(int) * 12
        + gas["month"].str[5:7].astype(int)
        - gas["first_month"].str[:4].astype(int) * 12
        - gas["first_month"].str[5:7].astype(int)
    )
    return gas


def h1_series(gas: pd.DataFrame) -> pd.Series:
    h1 = gas[gas["month"].str[5:7].isin(H1)]
    total = h1.groupby(h1["month"].str[:4])["rate_mmcfd"].sum()
    months = h1.groupby(h1["month"].str[:4])["month"].nunique()
    return total / months / 1000


def report_growth(gas: pd.DataFrame) -> None:
    print("\n1. GROWTH — H1 average, Bcf/d")
    series = h1_series(gas)
    previous = None
    for year, value in series.items():
        change = f"   {(value / previous - 1) * 100:+5.1f}% y/y" if previous else ""
        print(f"     H1-{year}   {value:.3f}{change}")
        previous = value

    years = len(series) - 1
    cagr = (series.iloc[-1] / series.iloc[0]) ** (1 / years) - 1
    print(f"\n     four-year CAGR        {cagr * 100:+.2f}%/yr")
    print(f"     Peters 2026-30 needs  {PETERS_CAGR * 100:+.2f}%/yr")


def report_vintage(gas: pd.DataFrame) -> None:
    """Growth attributed to well vintage rather than operator."""
    cohort = gas["vintage"].where(gas["vintage"] > "2022", "2022 & earlier")
    h1 = gas[gas["month"].str[5:7].isin(H1)].assign(cohort=cohort)
    table = (
        h1.groupby([h1["month"].str[:4], "cohort"], observed=True)["rate_mmcfd"]
        .sum().unstack(fill_value=0) / 6 / 1000
    )

    print("\n2. WHERE THE GROWTH CAME FROM — Bcf/d by well vintage, H1")
    print(table.round(3).to_string())

    base = table["2022 & earlier"]
    decline = 1 - (base.iloc[-1] / base.iloc[0]) ** (1 / (len(base) - 1))
    new = table.iloc[-1].drop("2022 & earlier").sum()
    lost = base.iloc[0] - base.iloc[-1]

    print(f"\n     pre-2023 base:  {base.iloc[0]:.3f} -> {base.iloc[-1]:.3f} Bcf/d")
    print(f"     base decline:   {decline * 100:.1f}%/yr")
    print(f"     new wells add:  {new:.3f}   decline destroyed: {lost:.3f}")
    print(f"     net growth:     {new - lost:+.3f} Bcf/d")
    print(f"     -> {lost / new * 100:.0f}% of new-well volume only replaces decline")


def report_activity(gas: pd.DataFrame) -> None:
    wells = gas.drop_duplicates("well_id")[["well_id", "first_month"]]
    wells = wells[wells["first_month"] >= "2023-01"]

    print("\n3. ACTIVITY — new Montney gas wells by first production")
    full = wells.groupby(wells["first_month"].str[:4]).size()
    print("     full year: " + "  ".join(f"{k} {v}" for k, v in full.items())
          + "   (2026 is H1 only)")

    h1 = wells[wells["first_month"].str[5:7].isin(H1)]
    counts = h1.groupby(h1["first_month"].str[:4]).size()
    print("     H1 only:   " + "  ".join(f"{k} {v}" for k, v in counts.items()))
    print(f"     H1-2026 vs H1-2025: "
          f"{(counts.iloc[-1] / counts.iloc[-2] - 1) * 100:+.0f}%")

    # Guard against reading the data edge as a collapse.
    recent = wells[wells["first_month"] >= "2025-01"]
    monthly = recent.groupby("first_month").size()
    print("\n     monthly first-production counts (checking for reporting lag):")
    print("     " + "  ".join(f"{k[2:]}:{v}" for k, v in monthly.items()))


def fixed_age_productivity(gas: pd.DataFrame, months: int) -> pd.DataFrame:
    """Cumulative gas over a complete N-month window, per 1,000 m."""
    window = gas[(gas["age"] < months) & (gas["vintage"] >= "2023")]
    well = window.groupby(["vintage", "well_id"], observed=True).agg(
        rate_sum=("rate_mmcfd", "sum"),
        months=("age", "size"),
        lateral_m=("lateral_m", "first"),
    ).reset_index()

    # Complete windows only - no annualising a four-month well.
    well = well[well["months"] == months]
    well = well[well["lateral_m"].between(LATERAL_MIN_M, LATERAL_MAX_M)]
    well["cum_mmcf"] = well["rate_sum"] * 30.4
    well["per_1000m"] = well["cum_mmcf"] / well["lateral_m"] * 1000
    return well


def report_productivity(gas: pd.DataFrame) -> None:
    print("\n4. PRODUCTIVITY — fixed age, complete windows, lateral-normalised")
    for months in (6, 12):
        well = fixed_age_productivity(gas, months)
        print(f"\n     first {months} months")
        print(f"     {'vintage':9}{'wells':>7}{'med MMcf':>11}"
              f"{'med lateral':>13}{'MMcf/1000m':>13}")
        for vintage in sorted(well["vintage"].unique()):
            subset = well[well["vintage"] == vintage]
            if len(subset) < 20:
                continue
            print(f"     {vintage:9}{len(subset):>7}"
                  f"{subset['cum_mmcf'].median():>11.0f}"
                  f"{subset['lateral_m'].median():>13.0f}"
                  f"{subset['per_1000m'].median():>13.0f}")

    # Is the fall a change in which operators drilled, or a change in
    # what each operator achieved? This is the question that decides
    # whether the number means anything.
    well = fixed_age_productivity(gas, 12)
    operator = gas.sort_values("month").drop_duplicates("well_id")[
        ["well_id", "operator"]]
    well = well.merge(operator, on="well_id")
    pair = well[well["vintage"].isin(["2024", "2025"])]

    median = pair.pivot_table(index="operator", columns="vintage",
                              values="per_1000m", aggfunc="median")
    count = pair.pivot_table(index="operator", columns="vintage",
                             values="well_id", aggfunc="count")
    both = median.dropna()
    both = both[(count.loc[both.index, "2024"] >= 10)
                & (count.loc[both.index, "2025"] >= 10)]

    print("\n     2024 vs 2025 by operator (>=10 complete wells in both)")
    print(f"     {'operator':34}{'2024':>8}{'2025':>8}{'change':>9}")
    for name, row in both.sort_values("2025").iterrows():
        print(f"     {name[:32]:34}{row['2024']:>8.0f}{row['2025']:>8.0f}"
              f"{(row['2025'] / row['2024'] - 1) * 100:>8.0f}%")

    w24 = count.loc[both.index, "2024"]
    actual_24 = (both["2024"] * w24).sum() / w24.sum()
    w25 = count.loc[both.index, "2025"]
    actual_25 = (both["2025"] * w25).sum() / w25.sum()
    held = (both["2025"] * w24).sum() / w24.sum()

    print(f"\n     weighted   2024 {actual_24:.0f} -> 2025 {actual_25:.0f}  "
          f"({(actual_25 / actual_24 - 1) * 100:+.0f}%)")
    print(f"     holding the 2024 operator mix: {held:.0f}  "
          f"({(held / actual_24 - 1) * 100:+.0f}%)  <- within-operator")
    print(f"     residual mix effect: {(actual_25 / held - 1) * 100:+.0f}%")


def report_requirement(gas: pd.DataFrame) -> None:
    """How many wells Peters' path implies, at observed well productivity."""
    series = h1_series(gas)
    current = series.iloc[-1]

    cohort_rate = {}
    for vintage, observed in (("2023", "2024"), ("2024", "2025"), ("2025", "2026")):
        window = gas[(gas["vintage"] == vintage)
                     & (gas["month"].str[:4] == observed)
                     & (gas["month"].str[5:7].isin(H1))]
        wells = gas[gas["vintage"] == vintage]["well_id"].nunique()
        cohort_rate[vintage] = window["rate_mmcfd"].sum() / 6 / wells

    print("\n5. WHAT THE FORECAST REQUIRES")
    print("     first-full-H1 rate per new well, MMcf/d:")
    for vintage, rate in cohort_rate.items():
        print(f"       {vintage} cohort  {rate:.2f}")

    per_well = cohort_rate["2025"]
    cohort = gas["vintage"].where(gas["vintage"] > "2022", "2022 & earlier")
    h1 = gas[gas["month"].str[5:7].isin(H1)].assign(cohort=cohort)
    base = (h1.groupby([h1["month"].str[:4], "cohort"], observed=True)["rate_mmcfd"]
            .sum().unstack(fill_value=0) / 6 / 1000)["2022 & earlier"]
    decline = 1 - (base.iloc[-1] / base.iloc[0]) ** (1 / (len(base) - 1))

    print(f"\n     from {current:.2f} Bcf/d, base decline {decline * 100:.1f}%/yr,"
          f" {per_well:.2f} MMcf/d per new well:")
    print(f"     {'target':16}{'growth':>9}{'replace decline':>18}"
          f"{'gross adds':>13}{'wells/yr':>11}")
    for rate, label in ((PETERS_CAGR, "Peters 4.15%"), (0.0, "hold flat")):
        growth = current * rate
        replace = current * decline
        gross = growth + replace
        print(f"     {label:16}{growth:>9.3f}{replace:>18.3f}"
              f"{gross:>13.3f}{gross * 1000 / per_well:>11.0f}")


def main() -> None:
    gas = montney_gas_history()
    print(f"Alberta Montney gas — {gas['month'].min()} to {gas['month'].max()}")
    print(f"{gas['well_id'].nunique():,} wells")

    report_growth(gas)
    report_vintage(gas)
    report_activity(gas)
    report_productivity(gas)
    report_requirement(gas)

    print("\nNOTE: liquids are deliberately excluded. Well-level condensate in "
          "Petrinex is measurement-dependent (see prepare_plant_condensate.py), "
          "so a liquids-targeting explanation for falling gas productivity "
          "cannot be tested with this data.")


if __name__ == "__main__":
    main()
