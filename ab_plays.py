"""Alberta play definitions, as bottom-hole geographic boxes.

Why boxes rather than field codes
---------------------------------
AER field and pool codes would attribute a well to a play exactly, but
the code-to-name lookup is a separate Petrinex download and the mapping
from field to play is itself a judgement call. Bottom-hole location is
already in the data and is good enough at province scale.

It is an approximation, and the honest limits are:

- Plays overlap in the subsurface. The Duvernay sits directly beneath
  the Deep Basin, so a box cannot separate them at all - Duvernay wells
  are counted as Deep Basin here.
- The Deep Basin and Montney boundary near Wapiti is genuinely fuzzy.
  Tourmaline appears in both because it operates in both.
- A box is a rectangle and a play is not. Edges will misattribute.

Validated against known operator footprints, which is the reason to
trust it at all: the Cold Lake box returns Imperial at exactly its
entire Alberta production, Athabasca returns Cenovus, Suncor,
ConocoPhillips and CNOOC, and Clearwater returns Spur, Tamarack and
Headwater. Those are the right answers in every case.

Shared by the map app and the Word reference so the two cannot drift.
"""

from __future__ import annotations

import pandas as pd

# name: (lat_min, lat_max, lon_min, lon_max, kind, blurb)
PLAYS: dict[str, tuple] = {
    "Montney (Alberta)": (
        53.8, 56.3, -120.1, -117.9, "gas",
        "Grande Prairie, Kakwa, Wapiti, Pipestone. Liquids-rich — the "
        "condensate is worth more than the gas. The drier BC side is "
        "not in this data.",
    ),
    "Deep Basin": (
        52.8, 54.6, -118.6, -115.6, "gas",
        "Stacked Spirit River, Wilrich and Falher tight gas. Lower "
        "decline and cost than the Montney, less liquids. The Duvernay "
        "lies beneath and cannot be separated geographically.",
    ),
    "Cardium / central foothills": (
        52.0, 53.6, -116.4, -114.2, "gas",
        "Pembina and Willesden Green. Mature light oil with associated "
        "gas; the box also catches shallower gas, so read the gas "
        "figure as the area rather than the formation.",
    ),
    "Mannville CBM / shallow": (
        50.8, 53.4, -114.6, -111.2, "gas",
        "Very low rate per well, enormous well count, minimal decline. "
        "This is the long tail — 84% of Alberta wells make under 0.1 "
        "MMcf/d.",
    ),
    "SE Alberta shallow gas": (
        49.0, 52.0, -112.5, -109.9, "gas",
        "Medicine Hat and the Lloydminster corridor. Shallow, old and "
        "declining.",
    ),
    "Athabasca in-situ": (
        55.4, 58.2, -113.2, -110.2, "oil",
        "SAGD thermal — Christina Lake, Foster Creek, Firebag, Surmont. "
        "The largest single pool of production in the country.",
    ),
    "Cold Lake": (
        53.8, 55.4, -111.6, -109.9, "oil",
        "Cyclic steam and SAGD. Imperial's Cold Lake operation is its "
        "entire Alberta production.",
    ),
    "Clearwater": (
        54.6, 56.6, -116.0, -113.2, "oil",
        "Marten Hills, Peavine, Nipisi. Shallow, cheap multilateral "
        "heavy oil — the highest capital efficiency in Canadian "
        "conventional. Almost no associated gas.",
    ),
    "Peace River oil sands": (
        55.8, 57.6, -117.8, -115.2, "oil",
        "Heavy oil in the northwest. Smaller than Athabasca or Cold "
        "Lake, and the play most associated with Baytex.",
    ),
}

# Drawn in the order plays are listed, so later entries sit on top.
PLAY_COLOURS: dict[str, list[int]] = {
    "Montney (Alberta)": [64, 191, 118, 60],
    "Deep Basin": [110, 198, 255, 55],
    "Cardium / central foothills": [240, 228, 66, 55],
    "Mannville CBM / shallow": [168, 138, 221, 55],
    "SE Alberta shallow gas": [141, 151, 165, 55],
    "Athabasca in-situ": [214, 69, 80, 55],
    "Cold Lake": [224, 106, 43, 55],
    "Clearwater": [0, 168, 120, 60],
    "Peace River oil sands": [196, 121, 172, 55],
}


def assign(frame: pd.DataFrame, lat: str = "lat", lon: str = "lon") -> pd.Series:
    """Label each row with its play, or 'Other' when no box contains it.

    First match wins, so overlapping boxes resolve in definition order
    rather than silently double counting a well.
    """
    out = pd.Series("Other", index=frame.index, dtype=object)
    unassigned = pd.Series(True, index=frame.index)

    for name, (la1, la2, lo1, lo2, *_rest) in PLAYS.items():
        hit = (
            unassigned
            & frame[lat].between(la1, la2)
            & frame[lon].between(lo1, lo2)
        )
        out.loc[hit] = name
        unassigned &= ~hit

    return out


def polygon(name: str) -> list[list[float]]:
    """Box corners as a deck.gl polygon ring, lon/lat order."""
    la1, la2, lo1, lo2, *_ = PLAYS[name]
    return [[lo1, la1], [lo2, la1], [lo2, la2], [lo1, la2], [lo1, la1]]


def blurb(name: str) -> str:
    return PLAYS[name][5] if name in PLAYS else ""


def kind(name: str) -> str:
    return PLAYS[name][4] if name in PLAYS else ""
