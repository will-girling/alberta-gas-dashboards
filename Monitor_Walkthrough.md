# Montney Supply Monitor — how to drive it

```
cd "/Users/willgirling/Desktop/NGTL Project"
python3 -m streamlit run Montney_Supply_Monitor.py
```

Four tabs. Roughly five minutes if you're showing someone, and the order below builds an argument rather than just touring features.

---

## 1. Open on **British Columbia — activity**

Leave the defaults. Colour is set to **Year**, comparison window to **April**.

**Point at the map first.** Each dot is a well that got fractured, coloured by the year it happened. Green is 2024, yellow 2025, red 2026. The red is thin, and it's thin *everywhere* — across the whole Dawson Creek–Fort St John fairway, not concentrated in one corner. That rules out "one company left one area."

**Then the four metrics.** 121 wells frac'd Jan–April 2026, down 28% year over year and **43% from the 2024 peak**. Median depth is up, not down — so this isn't a shift to cheaper, shallower wells that would need more of them. It's simply fewer.

**Then scroll to the operator table.** Eleven of twelve cut. Tourmaline −47%, Shell −67%, CNRL −82%. That breadth is the argument: a pullback this uniform is a price signal or a play problem, not one balance sheet.

### The move that earns credit

Change **Compare Jan through** to **December (full year)**. 2026 drops to about 150 and looks catastrophic.

Then say why that's wrong: BCER *backfills* these records rather than filing them ahead — despite the field being called `OPS_EXPECTED_START_DATE`, not one record carries a future date. The last two or three months are always thin. Set it back to April.

Volunteering the artifact before anyone finds it is worth more than the finding itself.

---

## 2. **Alberta — production & wells**

**The stacked area chart is the treadmill.** Grey is what the basin was producing in 2022, melting away. Every coloured band above it is new drilling.

The metrics underneath: base decline **16.3%/yr**, new wells contribute 3.00 Bcf/d, and **75% of that just replaces the melt**. Net growth over four years is +0.74 Bcf/d.

That's the number that converts a supply forecast into a capital requirement, and almost nobody at associate level will have computed it from raw data.

**Bottom left** — new wells online, H1: 383 → 306 → 314 → **166**. Down 47%.

**Bottom right** — productivity per 1,000 m of lateral, at fixed age. 273 → 273 → **221**. Down 19%.

**Then the operator table at the bottom.** This is the check that makes the productivity number mean anything: the same companies, both vintages, at least ten wells each. Seven of eleven got less gas per metre. Because it's the same operators, it isn't a change in *who* is drilling.

Flip **Fixed age** between 6 and 12 months if asked — 12 is the more honest comparison but drops a year of wells; 6 keeps 2026 in the sample.

---

## 3. **Side by side**

One chart, indexed to 2024 = 100. Alberta first-production counts and BC frac starts, collected by different regulators, for different purposes, measuring different events.

They agree: −47% and −43%.

**This is the slide.** Two independent datasets converging is what makes it hard to dismiss as a quirk of one source.

Underneath, the three things that would change the read — activity recovering into 2027 (elastic, forecast holds), staying down while AECO improves (structural), or Alberta productivity stabilising (2025 was noise).

---

## 4. **Data notes**

Don't walk them through it. Have it open so that when someone asks "where's BC production?" you click the tab instead of hedging.

Short answer: Petrinex publishes Alberta and Saskatchewan only — BC returns HTTP 400. That's why the app is built on frac activity. BCER *does* publish BC volumes as an open download (`iris.bcogc.ca/download/prod_csv.zip`), which I found late; it reconciles to 7.54 Bcf/d marketable against Peters' 7.5, and it's parsed in `prepare_bc_production.py` but not yet wired into these charts.

Say it that way rather than "BC isn't available" — the honest version is stronger, and the reconciliation to within 0.5% of a sell-side number is worth volunteering.

---

## The 30-second version

> Forecasts need the Montney to compound at about 4% a year through 2030. Alberta has done 3.9% over four years and printed −2.4% in the most recent half. BC, which carries most of the forecast growth, has cut completions 43% from the 2024 peak with eleven of twelve operators participating. Both of those are happening during the LNG Canada ramp that was supposed to pull supply forward. Frac activity leads production, so this implies growth stalls in late 2026 into 2027 — right when Woodfibre and Cedar need feedgas.

## What to say when pushed

**"Isn't this just capital discipline at a weak strip?"**
Possibly, and that's the honest open question. If it's a price response, supply is elastic and returns when netbacks improve — which supports the forecast. Activity fell before productivity did, which leans that way. What cuts against it is that the productivity decline is within-operator and broad, which is harder to explain as a choice.

**"Could operators have shifted to liquids-rich targets?"**
That's the alternative I can't rule out. Well-level condensate in Petrinex depends on where liquids are metered rather than what the well produces — ARC reads 84 bbl/MMcf and Ovintiv 0.1 in Kakwa, which is a reporting artifact, not geology. So I pulled liquids out of the analysis rather than report a number I don't believe.

**"What would settle it?"**
BC production volumes, and completion intensity — proppant and fluid per metre — which would separate cheaper completions from rock quality. Neither is in public well data. That's the gap a commercial dataset fills.

---

## Regenerating

```
python3 prepare_bc_well_locations.py --download fracs
python3 prepare_montney_monitor_data.py
```

Cross-check any number on screen against the source scripts:

```
python3 analyse_montney_supply.py
python3 analyse_bc_montney_activity.py
```

The four headline metrics are verified to match those two scripts exactly.
