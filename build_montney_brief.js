// Build the Montney supply-elasticity brief as a Word document.
//
// Every number here is computed by analyse_montney_supply.py from
// Petrinex volumetrics joined to AER ST37. Nothing is taken from a
// broker report or a data vendor. That is the point of the document.

const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
  LevelFormat, convertInchesToTwip,
} = require("docx");

const ACCENT = "1F4E5F";
const MUTED = "6B7280";
const RULE = { style: BorderStyle.SINGLE, size: 6, color: "D5DBE0" };
const PAGE = { size: { width: 12240, height: 15840 } };   // US Letter

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 340, after: 130 },
    border: { bottom: RULE },
    children: [new TextRun({ text, bold: true, size: 28, color: ACCENT })],
  });
}

function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 240, after: 70 },
    children: [new TextRun({ text, bold: true, size: 23, color: ACCENT })],
  });
}

function p(text, opts = {}) {
  return new Paragraph({
    spacing: { after: opts.after === undefined ? 110 : opts.after },
    children: [new TextRun({
      text, size: 19, italics: !!opts.italic,
      color: opts.muted ? MUTED : undefined,
    })],
  });
}

function lead(boldText, rest) {
  return new Paragraph({
    spacing: { after: 110 },
    children: [
      new TextRun({ text: boldText, bold: true, size: 19 }),
      new TextRun({ text: rest, size: 19 }),
    ],
  });
}

function bullet(text) {
  return new Paragraph({
    numbering: { reference: "dots", level: 0 },
    spacing: { after: 60 },
    children: [new TextRun({ text, size: 19 })],
  });
}

// Play size strip - the headline numbers, set apart from the prose.
function sizeLine(text) {
  return new Paragraph({
    spacing: { before: 40, after: 100 },
    shading: { type: ShadingType.CLEAR, fill: "EEF3F6" },
    children: [new TextRun({ text: `  ${text}  `, size: 19, bold: true, color: ACCENT })],
  });
}

// Column widths must sum to the table width, and every cell needs its
// own width or Google Docs renders it wrong.
function opTable(rows, unit) {
  const widths = [5100, 1900];
  const header = new TableRow({
    tableHeader: true,
    children: ["Operator", unit].map((text, i) => new TableCell({
      width: { size: widths[i], type: WidthType.DXA },
      shading: { type: ShadingType.CLEAR, fill: "EEF3F6" },
      margins: { top: 50, bottom: 50, left: 110, right: 110 },
      children: [new Paragraph({
        alignment: i === 0 ? AlignmentType.LEFT : AlignmentType.RIGHT,
        children: [new TextRun({ text, bold: true, size: 17, color: ACCENT })],
      })],
    })),
  });

  const body = rows.map((cells, r) => new TableRow({
    children: cells.map((text, i) => new TableCell({
      width: { size: widths[i], type: WidthType.DXA },
      shading: r % 2 ? { type: ShadingType.CLEAR, fill: "F8FAFB" } : undefined,
      margins: { top: 45, bottom: 45, left: 110, right: 110 },
      children: [new Paragraph({
        alignment: i === 0 ? AlignmentType.LEFT : AlignmentType.RIGHT,
        children: [new TextRun({ text: String(text), size: 17 })],
      })],
    })),
  }));

  return new Table({
    columnWidths: widths,
    width: { size: 7000, type: WidthType.DXA },
    rows: [header, ...body],
  });
}

// Glossary entry: term in bold, definition following on the same line.
function term(name, text) {
  return new Paragraph({
    spacing: { after: 90 },
    indent: { left: convertInchesToTwip(0.02) },
    children: [
      new TextRun({ text: `${name} — `, bold: true, size: 19, color: ACCENT }),
      new TextRun({ text, size: 19 }),
    ],
  });
}

// ---- content ------------------------------------------------

const children = [
  new Paragraph({
    spacing: { after: 50 },
    children: [new TextRun({
      text: "Alberta Montney Supply Elasticity", bold: true, size: 38, color: ACCENT,
    })],
  }),
  new Paragraph({
    spacing: { after: 200 },
    border: { bottom: RULE },
    children: [new TextRun({
      text: "Original analysis — Petrinex/AER ST37 (Alberta) and BCER frac records (BC), data through mid-2026",
      size: 21, color: MUTED,
    })],
  }),

  lead("The claim being tested. ",
    "Peters forecasts WCSB supply rising from 19.7 to 22.2 Bcf/d between 2026 and 2030, with the Montney carrying roughly 1.9 Bcf/d of it. The interesting question is not whether the Montney can grow — it plainly can — but how quickly and cheaply it responds as LNG removes gas from the basin. The late-2020s buildout is the observable test before a much larger early-2030s stack."),

  h1("What this data can and cannot answer"),
  bullet("Petrinex publishes Alberta and Saskatchewan only — every BC month returns HTTP 400. Alberta volumes therefore cover roughly 36% of the forecast growth: Alberta Montney (+0.6) and Duvernay (+0.3) of 2.5 Bcf/d."),
  bullet("BC is covered separately and differently. BCER publishes frac records but not accessible production, so BC is measured on ACTIVITY — wells frac'd — rather than volumes. Different metric, same question."),
  bullet("BC frac records carry OBJECTIVE_FORMATION, so 'Montney' is an explicit attribute rather than a geographic guess. That is better attribution than the Alberta side has."),
  bullet("The play boundary is a geographic box, so levels differ from Peters' formation-based figures (5.2 vs 3.4 Bcf/d). Growth rates are comparable; levels are not. All comparisons below use rates."),
  bullet("Liquids are excluded deliberately. Well-level condensate in Petrinex is measurement-dependent — operators sending raw gas to third-party plants show almost none — so a liquids-targeting explanation cannot be tested here."),

  h1("Method — two choices that change the answer"),
  lead("Vintage, not operator. ", "Operator-level growth attribution is unusable: Pipestone, Hammerhead and Paramount all fall to exactly zero between 2022 and 2026 because they were acquired. Naive operator tables would credit Whitecap with 0.287 Bcf/d of 'growth' that is a purchase. This is the same substitution problem the thesis flags in the Shell/ARC case, appearing directly in the data. Decomposing by well vintage is immune to it."),
  lead("Fixed age, complete windows, lateral-normalised. ", "A well with four months of history is excluded from a twelve-month comparison rather than annualised, or recent vintages get measured on their flush period and flattered. Lateral length is approximated as total depth less true vertical depth; without it, longer wells masquerade as better rock."),
  p("Comparisons are H1-over-H1 throughout. Alberta gas is strongly seasonal and the data ends in June 2026.", { muted: true }),

  h1("Finding 1 — growth has decelerated to negative"),
  sizeLine("H1 Bcf/d:  4.445 → 4.749 → 5.103 → 5.311 → 5.184     y/y: +6.8%, +7.4%, +4.1%, −2.4%"),
  p("Four-year CAGR is +3.92% against the +4.15% Peters' Alberta Montney path requires. Treat that comparison as suggestive rather than decisive: the measured CAGR moves between 3.92% and 4.42% depending on where the play box is drawn, and the location-coverage bias described under Reliability pushes the true figure lower still — plausibly as low as 2.4%. The point estimate sits below the requirement and most of the plausible range does too, but the margin is inside the measurement error."),
  p("The −2.4% year-on-year print is a different kind of number and does not depend on any of that. It is a like-for-like comparison of the same wells and the same box in two consecutive first-halves, and it is the first H1 decline in the series.", { muted: true }),
  p("H1-2026 is also the first full period after LNG Canada's initial cargoes. There is no visible supply acceleration into the ramp.", { muted: true }),

  h1("Finding 2 — the treadmill is steep"),
  sizeLine("Pre-2023 base:  4.445 → 2.180 Bcf/d  ·  16.3%/yr decline  ·  75% of new-well volume replaces decline"),
  p("Wells drilled 2023-2026 now contribute 3.004 Bcf/d. Decline on the pre-2023 base destroyed 2.265 Bcf/d over the same period. Net growth: +0.739 Bcf/d. Three quarters of everything drilled went to standing still."),
  p("This is the Alberta Montney equivalent of the province-wide 25.4% base decline measured earlier. It is the number that converts a supply forecast into a capital requirement.", { muted: true }),

  h1("Finding 3 — activity has fallen sharply"),
  sizeLine("New wells:  2023  715  ·  2024  601  ·  2025  584  ·  H1-2026  166 vs 314 in H1-2025  (−47%)"),
  p("Monthly first-production counts confirm this is not a data-edge artifact. The taper begins in late 2025 — December 2025 shows 23 wells against 46 a year earlier — and January to April 2026 is down 46% on the same months of 2025, well inside the reliable window. Petrinex revisions may lift recent months, but not by this order."),

  h1("Finding 4 — new-well gas productivity fell, within operators"),
  sizeLine("12-month cum per 1,000 m lateral:  2023  273  ·  2024  273  ·  2025  221 MMcf   (−19%)"),
  p("Median lateral length is essentially flat across vintages (3,059 / 3,223 / 3,244 m), so this is not a length artifact. Restricting 2024 to H1 starts for like-for-like seasonality still gives −15%. Mann-Whitney p = 0.008."),
  lead("The decomposition that matters. ", "Across the eleven operators with at least ten complete-window wells in both vintages, the weighted figure falls from 321 to 242 MMcf per 1,000 m. Holding the 2024 operator mix constant it still falls to 234 — so the decline is within-operator, and the mix effect is only +4%. Seven of eleven operators declined, including the largest programmes: Tourmaline −58%, ARC −44%, Whitecap −30%, CNRL −25%, Ovintiv −11%."),
  p("This is not a few weak operators dragging an average. The same companies got less gas per metre in 2025 than in 2024.", { muted: true }),

  h1("Finding 5 — what the forecast requires"),
  sizeLine("Peters' path needs ~1.06 Bcf/d of gross adds per year — roughly 476 wells at 2025 well productivity"),
  p("From 5.18 Bcf/d, at 16.3% base decline and 2.23 MMcf/d per new well in its first full half-year, holding production flat requires about 380 wells a year. Peters' +4.15% requires about 476."),
  p("Actual: 584 wells in 2025 — comfortably sufficient. H1-2026 annualises to roughly 332 — below even the flat-line requirement.", { muted: true }),

  h1("Finding 6 — BC is cutting as hard as Alberta"),
  p("This is the finding that matters most, because BC carries roughly 1.3 of the 1.9 Bcf/d of forecast Montney growth. Alberta could be dismissed as the mature half. BC cannot."),
  sizeLine("BC Montney wells frac'd, January to April:  2024  214  ·  2025  167  ·  2026  121     −43% from the peak"),
  p("Year on year: −22.0% in 2025, then −27.5% in 2026. The comparison window stops at April deliberately — despite the field name, no BCER record carries a future date, and monthly counts thin sharply at the data edge (June 6, July 3, August 1 against a ~30/month run-rate). Reading that tail as a collapse would be a mistake; April is well inside the reliable window."),
  lead("It is broad, not concentrated. ", "Eleven of twelve operators cut between 2024 and 2026, and the cuts run through the largest programmes: Tourmaline −47%, Shell −67%, CNRL −82%, Pacific Canbriam −53%, Petronas −34%, ARC −25%, Ovintiv −30%. Only Vermilion held flat. Two operators stopped entirely."),
  lead("And the wells are not getting smaller. ", "Median total depth rose every year — 4,964 m in 2022 to 5,480 m in 2026. This is not a shift to cheaper, shallower wells that would need more of them. It is simply fewer wells, and if anything slightly larger ones."),
  p("Two independent regulators, two different measurements — Alberta first-production counts, BC frac starts — give almost the same answer: −47% and −43% respectively. That consistency is what makes this hard to dismiss as a data artifact.", { muted: true }),
  lead("Frac activity leads production. ", "A well frac'd today produces months later. So this turns before volumes do, and the 2026 cut implies BC supply growth stalls in late 2026 into 2027 — precisely when Woodfibre and Cedar need feedgas."),

  h1("What this does to the thesis"),
  p("It sharpens it rather than contradicting it. The stated view was that Montney supply probably remains strong enough, with the open question being whether it responds as completely and quickly as forecasts require. On this evidence it currently is not — and critically, that is true on both sides of the border. Alberta shows falling growth, activity and per-well productivity at once. BC, which carries most of the forecast, has cut completions 43% from the 2024 peak with eleven of twelve operators participating."),
  p("Peters' path needs the Montney to compound at roughly 4% a year through 2030. Both halves of it are currently reducing activity by double digits, in the middle of the LNG ramp that was supposed to pull supply forward.", { muted: true }),
  lead("But the interpretation is genuinely open, and this is the honest centre of the argument. ",
    "Falling activity at weak AECO is exactly what rational capital discipline looks like. If the slowdown is a price response, supply is elastic and will return when LNG-driven netbacks improve — which supports Peters. If it reflects inventory quality or productivity exhaustion, it does not, and the early-2030s stack becomes considerably harder to supply."),
  bullet("Evidence for discipline: activity fell before productivity did, and the operators cutting hardest are the ones with the most alternatives."),
  bullet("Evidence against: the productivity decline is within-operator and broad, which is harder to explain as a deliberate choice."),
  bullet("Untestable here: whether operators shifted toward liquids-rich targets, which would make falling gas per metre a targeting decision rather than degradation. Petrinex well-level condensate cannot answer this."),

  h1("How to use it"),
  p("Not as a forecast. As a demonstration that the supply assumption underneath the LNG thesis is measurable, and that the measurement currently disagrees with the trend the forecast extrapolates."),
  p("The line worth having ready: Peters needs Alberta Montney to compound at 4.15% a year; it has compounded at 3.92% over four years and printed −2.4% in the most recent half. Well counts are down 47% year over year and per-metre productivity is down 19% within the same operators. That does not prove the forecast is wrong — it may all be discipline at a weak strip — but it means the supply response is an open empirical question rather than an assumption, and the next two years of LNG ramp will settle it.", { muted: true }),

  h1("What would resolve it"),
  bullet("BC production volumes. Activity is now covered, but BCER production sits behind a Data Centre logon. With it, the BC vintage-productivity test could run exactly as Alberta's did — the single highest-value missing piece."),
  bullet("Completion data. Proppant and fluid intensity would show whether operators changed design, separating deliberate cost-cutting from rock quality."),
  bullet("Well logs. Rock-quality controls would distinguish high-grading — drilling the best acreage first — from a genuine productivity decline. This is precisely what public well data cannot do and what a commercial log library is for."),
  bullet("Capital disclosure. Capex per well against production added would show whether the response is a cost decision or a capability limit."),

  h1("Reliability — what was tested"),
  p("Each claim below was probed rather than assumed. Two survived every test, one did not."),
  lead("Robust. ", "The activity and productivity findings hold under every sensitivity run. Alberta new-well counts fall 38% to 47% depending on the month window, so the 2026 drop is not a reporting-lag artifact. Alberta per-metre productivity falls 18.5% to 19.6% under lateral-length filters of 500, 1,500, 2,000 and 2,500 m, and 17.5% on raw cumulative volume with no normalisation at all. Lateral lengths within the comparison sample are stable and if anything longer in 2025 (p25 2,957 m vs 2,844 m), so longer wells are producing less per metre. Depth coverage is 95-99% with no vintage pattern."),
  lead("Not robust. ", "The 3.92% versus 4.15% CAGR comparison. Shrinking the play box gives 4.42%, enlarging it gives 4.03-4.13%. Separately, the location-coverage bias overstates measured growth by an amount that could take the true figure to 2.35% at its outer bound. The direction of the growth conclusion is more likely right than wrong, but it should not be presented as a measurement."),
  lead("Levels are not comparable to published forecasts. ", "Petrinex PROD gas is gross wellhead volume. Peters and AER work on marketable gas, after fuel, flare and processing shrinkage of roughly 10-15%. This data shows 14.0 Bcf/d for Alberta against roughly 12.0-12.6 marketable. Growth rates are comparable; levels are not, and the play box adds a second reason they are not."),
  bullet("Base decline of 16.3%/yr is conservative: unlocatable wells are the fastest decliners, so excluding them understates the true rate."),
  bullet("BC's aggregate count is immune to the M&A problem that broke Alberta's operator table, because it counts wells rather than attributing them to firms. Only two small operators appear in 2024 and not 2026."),

  h1("Reproducibility"),
  p("Alberta figures regenerate from analyse_montney_supply.py — Petrinex volumetrics (2022-01 to 2026-06) joined to AER ST37 on production-string UWI at a 91.7% match rate with a location-key fallback. BC figures regenerate from analyse_bc_montney_activity.py, against BCER's WELL/HISTORIC_FRACTURING layer pulled by prepare_bc_well_locations.py."),
  bullet("The BCER frac layer starts September 2021 and appears to be a rolling window, not the complete record of BC fracturing. 2021 is excluded as partial."),
  bullet("Records are deduplicated to the first frac per well authorization, so a re-frac cannot read as a new well. This affects six records of 2,164."),
  bullet("Location coverage rises from 94.5% of gas volume in early 2022 to 100% currently; the shortfall is wells that ceased before the join month, which slightly overstates measured growth."),
  bullet("Lateral length is a proxy — total depth less true vertical depth — not a surveyed value."),
  bullet("The Montney box is geographic and overlaps the Deep Basin; wells are assigned to the first matching box."),
];

const doc = new Document({
  numbering: {
    config: [{
      reference: "dots",
      levels: [{
        level: 0,
        format: LevelFormat.BULLET,
        text: "•",
        alignment: AlignmentType.LEFT,
        style: {
          paragraph: {
            indent: {
              left: convertInchesToTwip(0.25),
              hanging: convertInchesToTwip(0.18),
            },
          },
        },
      }],
    }],
  },
  styles: { default: { document: { run: { font: "Calibri", size: 19 } } } },
  sections: [{
    properties: {
      page: { ...PAGE, margin: { top: 1000, bottom: 1000, left: 1000, right: 1000 } },
    },
    children,
  }],
});

Packer.toBuffer(doc).then((buffer) => {
  const out = process.argv[2] || "Canadian_Plays_and_Operators.docx";
  fs.writeFileSync(out, buffer);
  console.log(`wrote ${out} (${(buffer.length / 1024).toFixed(0)} KB)`);
});
