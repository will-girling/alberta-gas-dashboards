"""Join ST37 well locations to Petrinex monthly production.

The problem
-----------
The two sources identify the same well differently and neither publishes
a crosswalk:

    ST37 Prod_String_UWI    00/06-06-001-01W4/0     (19 chars, punctuated)
    ST37 Well_UWI           0014010606000           (13 chars, reordered)
    Petrinex From/To ID     AB + type + 16 chars    (CPA unformatted)

Joining on the wrong one silently yields zero rows, so this script
parses the UWI into its surveyed components and rebuilds the key, then
*measures* the match rate against several candidate formats rather than
trusting one.

What was verified against the real ST37 file
--------------------------------------------
- All 657,179 Prod_String_UWI values parse with the DLS pattern below.
  The leading pair is a location exception code and is alphanumeric -
  '00', but also 'F1' and 'W0' - so a digits-only pattern drops 10% of
  rows without erroring.
- The 13-char Well_UWI decodes as
  TWP(3) MER(1) RGE(2) SEC(2) LSD(2) LE(2) EVENT(1), confirmed by
  rebuilding it from the parsed parts.
- Prod_String_UWI is the *producing string*, Well_UWI is its parent
  well: 657,179 strings across 530,860 wells, 1.24 strings per well.
  Where the two disagree it is only in the trailing exception and event
  digits - the surveyed location agrees on 99.98% of rows. So production
  reported against a string must be summed to the well before mapping,
  or a multi-string well is drawn several times.

String fields in the GDB are fixed-width space padded. Every comparison
here strips first; a forgotten strip returns an empty result set rather
than an error.

Output
------
processed/ab_well_production_located.parquet

Run
---
    python3 prepare_well_production.py
    python3 prepare_well_production.py --diagnose   # match rates only
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd
import pyogrio

PROJECT_ROOT = Path("/Users/willgirling/Desktop/NGTL Project")
GDB = PROJECT_ROOT / "ST_37_Wells.gdb"
PRODUCTION = PROJECT_ROOT / "processed" / "ab_well_production.parquet"
OUTPUT = PROJECT_ROOT / "processed" / "ab_well_production_located.parquet"

STRING_LAYER = "ST37_Production_String_NAD83_10TM_AEP_Forest"
BOTTOM_LAYER = "ST37_Bottom_Hole_NAD83_10TM_AEP_Forest"

# Location exception is alphanumeric; event is one or more digits.
DLS = re.compile(
    r"^([0-9A-Z]{2})/(\d{2})-(\d{2})-(\d{3})-(\d{2})([WE])(\d)/(\d+)$"
)

# A match rate below this means the key is wrong, not that wells are
# missing - fail loudly rather than write a mostly-empty join.
MIN_MATCH_RATE = 0.40


def strip_frame(frame: pd.DataFrame) -> pd.DataFrame:
    for column in frame.columns:
        if frame[column].dtype == "object":
            frame[column] = frame[column].str.strip()
    return frame


def parse_uwi(values: pd.Series) -> pd.DataFrame:
    parts = values.str.extract(DLS)
    parts.columns = [
        "le", "lsd", "sec", "twp", "rge", "dir", "mer", "event",
    ]
    return parts


def build_keys(parts: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Exact and location-only join keys.

    Measured against Petrinex 2026-05, which lists 135,143 producing
    wells:

        cpa16     85.63%    "1" + LE + LSD + SEC + TWP + RGE + dir + MER + event
        cpa15      0.00%
        cpa15_e1   0.00%
        no_dir     0.00%

    So the format is unambiguous - Petrinex publishes the 16-character
    CPA form, e.g. 100010206504W400 for 00/01-02-065-04W4/0.

    The 14% that miss are not a format problem: 98.1% of them exist in
    ST37 at the same surveyed location with a different event number.
    Matching on location alone lifts coverage to 99.7%. That fallback is
    kept separate rather than merged in, because two events at one
    location can be genuinely different wellbores, and a production
    volume attached to the wrong one is a real error even when the map
    pin lands in the right place.
    """
    event2 = parts["event"].str.zfill(2)
    location = (
        "1" + parts["le"] + parts["lsd"] + parts["sec"] + parts["twp"]
        + parts["rge"] + parts["dir"] + parts["mer"]
    )
    return location + event2, location


def normalise_petrinex(values: pd.Series) -> pd.Series:
    """Strip province/type prefix and punctuation from a Petrinex ID."""
    cleaned = values.str.strip().str.upper()
    cleaned = cleaned.str.replace(r"^AB", "", regex=True)
    cleaned = cleaned.str.replace(r"^(WI|WELL)", "", regex=True)
    return cleaned.str.replace(r"[^0-9A-Z]", "", regex=True)


def load_wells() -> pd.DataFrame:
    strings = strip_frame(pyogrio.read_dataframe(
        GDB, layer=STRING_LAYER, read_geometry=False,
        columns=[
            "Prod_String_UWI", "Well_UWI", "Licensee", "Licence_Status",
            "Status_Fluid", "Status_Mode", "Field_Code", "Pool_Code",
            "Well_Name", "Spud_Date", "Final_Total_Depth",
            "Max_True_Vertical_Depth",
        ],
    ))
    bottom = strip_frame(pyogrio.read_dataframe(
        GDB, layer=BOTTOM_LAYER, read_geometry=False,
        columns=["Well_UWI", "BH_Latitude", "BH_Longitude"],
    ))

    # Bottom hole keys on the punctuated UWI, production string on the
    # 13-char form - the reason a naive join on Well_UWI returns nothing.
    bottom = bottom.rename(columns={"Well_UWI": "Prod_String_UWI"})
    bottom = bottom.drop_duplicates(subset=["Prod_String_UWI"])

    wells = strings.merge(bottom, on="Prod_String_UWI", how="left")
    return wells


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnose", action="store_true",
                        help="report candidate match rates and stop")
    args = parser.parse_args()

    if not PRODUCTION.exists():
        raise SystemExit(
            f"{PRODUCTION.name} not found - run "
            "download_petrinex_volumes.py first."
        )

    print("Reading ST37...")
    wells = load_wells()
    parts = parse_uwi(wells["Prod_String_UWI"])
    unparsed = int(parts["lsd"].isna().sum())
    print(f"  {len(wells):,} production strings, "
          f"{wells['Prod_String_UWI'].nunique():,} distinct")
    print(f"  located: {wells['BH_Latitude'].notna().sum():,}")
    if unparsed:
        print(f"  WARNING {unparsed:,} UWIs did not parse")

    wells["key_exact"], wells["key_location"] = build_keys(parts)

    production = pd.read_parquet(PRODUCTION)
    production["key_exact"] = production["well_id"].str.strip()
    production["key_location"] = production["key_exact"].str[:14]

    exact_ids = set(wells["key_exact"].dropna())
    loc_ids = set(wells["key_location"].dropna())
    petrinex_wells = production["key_exact"].dropna().drop_duplicates()

    exact_rate = petrinex_wells.isin(exact_ids).mean()
    loc_rate = petrinex_wells.str[:14].isin(loc_ids).mean()
    print(f"\nPetrinex: {len(petrinex_wells):,} distinct producing wells")
    print(f"  exact UWI match      {exact_rate * 100:6.2f}%")
    print(f"  location-only match  {loc_rate * 100:6.2f}%")

    if exact_rate < MIN_MATCH_RATE:
        raise SystemExit(
            "Exact match rate collapsed - the UWI rendering has changed. "
            "Compare a Petrinex well_id against a ST37 Prod_String_UWI "
            "before trusting anything downstream."
        )

    if args.diagnose:
        return

    columns = [
        "Prod_String_UWI", "Well_UWI", "Licensee", "Licence_Status",
        "Status_Fluid", "Well_Name", "Field_Code",
        "Spud_Date", "Final_Total_Depth", "Max_True_Vertical_Depth",
        "BH_Latitude", "BH_Longitude",
    ]

    # Tier 1: exact well, event and all.
    exact = wells.drop_duplicates(subset=["key_exact"])
    joined = production.merge(
        exact[["key_exact"] + columns], on="key_exact", how="left"
    )
    joined["match"] = joined["BH_Latitude"].notna().map(
        {True: "exact", False: ""}
    )

    # Tier 2: same surveyed location, different event. Flagged, never
    # silently blended with tier 1.
    gap = joined["match"] == ""
    if gap.any():
        fallback = (
            wells.dropna(subset=["BH_Latitude"])
            .drop_duplicates(subset=["key_location"])
            .set_index("key_location")[columns]
        )
        filled = joined.loc[gap, "key_location"].map(
            lambda k: fallback.index.get_loc(k) if k in fallback.index else None
        )
        hit = filled.notna()
        idx = joined.loc[gap].index[hit]
        for column in columns:
            joined.loc[idx, column] = (
                fallback[column].to_numpy()[filled[hit].astype(int)]
            )
        joined.loc[idx, "match"] = "location"

    located = joined["BH_Latitude"].notna()
    print(f"\njoined {len(joined):,} production rows")
    for tier, count in joined["match"].value_counts().items():
        label = tier or "unmatched"
        print(f"  {label:12}{count:>10,}  ({count / len(joined) * 100:.1f}%)")
    print(f"  wells with no location: "
          f"{joined.loc[~located, 'well_id'].nunique():,}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    joined.to_parquet(OUTPUT, index=False)
    print(f"\nwrote {OUTPUT.name}")

    latest = joined["production_month"].max()
    recent = joined[(joined["production_month"] == latest) & located]
    gas = recent[recent["product"] == "GAS"]
    print(f"\n{latest}: {gas['well_id'].nunique():,} located gas wells, "
          f"{gas['rate_mmcfd'].sum():,.0f} MMcf/d")
    print("  top operators by gas rate:")
    for name, rate in gas.groupby("Licensee")["rate_mmcfd"].sum().nlargest(8).items():
        print(f"    {str(name)[:44]:46}{rate:>9,.0f} MMcf/d")


if __name__ == "__main__":
    main()
