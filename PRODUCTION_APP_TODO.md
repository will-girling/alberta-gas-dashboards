# Alberta production sites app — build plan

Standalone Streamlit app. Alberta only. Well-level production with
operator, product and output layers.

---

## Done

**`download_petrinex_volumes.py`** — monthly well-level production from
Petrinex. 12 months, 2,162,006 rows, 143,253 wells, 401 operators.

- Well-level volumes are published directly. No allocation from facility
  totals is needed — that assumption in the first draft of this plan was
  wrong.
- The download is a zip inside a zip; the CSV header omits the spaces the
  documentation shows (`FromToID`, not `From/To ID`); and the joinable ID
  is `FromToIDIdentifier`, not `FromToID`.
- `PROD` activity only. The file also carries REC, DISP, DIFF, VENT,
  ROYALTY, FUEL and inventory rows, which would count the same gas
  several times as it moves through the system.

**Product classification** — Petrinex code `OIL` means "Crude Oil, Crude
Bitumen", one code for two different businesses. Split by the reporting
facility's AER subtype, which is carried in the volumetric file:

| product_class | wells | May 2026 |
|---|---:|---:|
| GAS | 133,709 | 13,091 MMcf/d |
| BITUMEN | 13,081 | 1,847,428 bbl/d |
| CRUDE_OIL | 28,549 | 553,094 bbl/d |
| COND | 3,654 | 89,983 bbl/d |
| OIL_AT_GAS_BATTERY | 850 | 16,284 bbl/d |

Crude reconciles to Alberta's published 450–550k bbl/d, bitumen to the
~2.0–2.2M in-situ figure. ST37's `Status_Fluid` cannot do this job —
57% of the oil sits under "Not Applicable". The raw `product` code is
kept alongside `product_class` so the derivation stays auditable.

**`prepare_well_production.py`** — joins production to ST37 locations.

- Petrinex publishes the 16-character CPA UWI (`100010206504W400`);
  ST37 has it punctuated (`00/01-02-065-04W4/0`) and also as a
  13-character reordered form. Joining on the wrong one returns zero
  rows silently.
- Two-tier join: exact UWI 85.8%, then same surveyed location with a
  different event number, lifting coverage to 99.7%. The tier is
  recorded per row in `match`, never blended — two events at one
  location can be different wellbores.
- ST37 string fields are fixed-width space padded. Comparisons without
  `.str.strip()` return empty results rather than errors.

---

## Next: `prepare_well_map_layer.py`

116,748 located wells in the latest month would be ~10.5 MB of GeoJSON
before properties. The NGTL map ships 2.36 MB in total, and that was
already the slow part.

Production is concentrated enough that this is easy:

| | share of gas |
|---|---:|
| top 1% of wells (1,159) | 30.4% |
| top 5% (5,796) | 62.5% |
| top 10% (11,592) | 76.7% |
| top 25% (28,981) | 91.1% |

84% of wells produce under 0.1 MMcf/d and carry 15.3% of the gas
between them.

So the layer should be two things:

1. **Individual wells above a threshold.** At 0.1 MMcf/d that is ~19k
   points carrying 85% of production — a tenth of the payload for
   almost all of the signal. Threshold exposed as a control, not
   hardcoded.
2. **An aggregate for the tail.** Roll the remainder to township or a
   hex grid so the map still shows where the long tail is without
   shipping 98k individual points.

Reuse the coordinate rounding and property-dropping from
`slim_map_layers.py` — 5 decimal places and tooltip-only properties.

---

## Then

**The app** — `AB_Production_Sites.py`. Layers: wells (point, or
aggregated below a zoom), coloured by operator / product_class /
output. Filters for operator, product, month, minimum rate. Optional
NGTL pipeline context from `processed/map/`.

**`refresh_production.py`** — monthly cadence is enough, but it must
catch restatements, which Petrinex does issue. Raw zips are kept so a
restatement shows as a change rather than overwriting history.

**Refresh ST37** — 18,696 producing wells have no location because the
GDB snapshot predates them. A fresh ST37 from AER recovers most.

---

## Known limits

- **Two-month lag.** Not a real-time app. Latest available is 2026-06.
- **Five years of history**, total. No deep history in this feed.
- **Mined oil sands excluded** (OS facility type), so ~1.3M bbl/d of
  bitumen is absent. In-situ *is* present, because SAGD reports through
  ordinary batteries.
- **Whole facility types withheld** under Petrinex's security blanket:
  terminals, meter stations, pipelines, refineries, custom treating, gas
  plant fractionation. Absent, not zero.
- **Operator ≠ licensee.** ST37 gives the well licensee, Petrinex the
  facility operator. Frequently different companies; do not conflate.
- 10.7% of production rows are still unmatched to a location, almost all
  wells newer than the ST37 snapshot.
