// Build the master play reference as a Word document.
//
// One file, four sections: Gas Canada, Gas USA, Oil Canada, Oil USA.
// Every play gets the same four things in the same order - volume,
// liquids richness, reservoir and method, operators with size - so it
// can be studied linearly rather than hunted through.
//
// Volumes are published figures with the source named on every line.
// Two exceptions carry local computation, both flagged in the text:
// BC Montney, where BCER formation-coded well data reconciled to the
// published forecast within 0.5%, and Alberta Montney condensate yield.

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
      text: "North American Play Reference", bold: true, size: 38, color: ACCENT,
    })],
  }),
  new Paragraph({
    spacing: { after: 200 },
    border: { bottom: RULE },
    children: [new TextRun({
      text: "Gas and oil by play · volumes, liquids richness, method, operators · August 2026",
      size: 21, color: MUTED,
    })],
  }),

  lead("Every play below follows the same four lines. ",
    "Size, liquids richness, reservoir and method, then operators with their scale. Read it top to bottom or jump to one play; the structure does not change."),
  bullet("Gas volumes are MARKETABLE unless stated — after fuel, flare and processing shrinkage. Wellhead figures run 10–15% higher and the two are not interchangeable."),
  bullet("Every volume names its source on the line. EIA for the US, Peters & Co. for the WCSB balance, CAPP/AER/Oil Sands Magazine for oil sands, BCER for BC well data."),
  bullet("Condensate richness is quoted as barrels per MMcf of gas. Above ~20 is a liquids play where the condensate carries the economics; below ~5 is a gas play that lives on gas price alone."),
  bullet("BOE is 6 Mcf to 1 barrel — energy equivalence, not economic. Never rank a gas play against an oil play on BOE."),

  h1("The whole picture in two tables"),
  p("Gas, marketable Bcf/d:", { after: 60 }),
  opTable([
    ["UNITED STATES total", "122.5"],
    ["  Appalachia", "37.0"],
    ["  Permian (associated)", "29.2"],
    ["  Haynesville", "16.3"],
    ["  Eagle Ford", "~7.3"],
    ["  Anadarko", "~6.5"],
    ["CANADA (WCSB) total", "19.7"],
    ["  BC Montney", "7.5"],
    ["  Deep Basin", "3.9"],
    ["  Alberta Montney", "3.4"],
    ["  Duvernay", "0.8"],
    ["  Everything else", "4.0"],
  ], "Bcf/d"),
  p("US gas is roughly six times Canadian. Appalachia alone is twice the entire WCSB.", { muted: true }),

  p("Oil, MMbbl/d:", { after: 60 }),
  opTable([
    ["UNITED STATES total", "13.5"],
    ["  Permian", "6.6"],
    ["  Gulf of Mexico", "~1.8"],
    ["  Bakken", "1.3"],
    ["  Eagle Ford", "1.1"],
    ["  Niobrara / DJ", "~0.7"],
    ["CANADA total", "~5.0"],
    ["  Oil sands in-situ", "~1.9"],
    ["  Oil sands mining", "~1.7"],
    ["  Conventional and cold heavy", "~1.4"],
  ], "MMbbl/d"),
  p("US oil is roughly 2.7x Canadian, and the Permian alone is larger than all of Canada. Canada's oil is 70%+ oil sands; the US has no equivalent concentration.", { muted: true }),

  h1("GAS — CANADA"),

  h2("BC Montney"),
  sizeLine("7.5 Bcf/d marketable  ·  the largest gas play in Canada  ·  Peters & Co. 2026E"),
  lead("Liquids. ", "Lean by Canadian standards — 5.3 bbl of condensate per MMcf, measured from BCER formation-coded well records. That is roughly a quarter of the Alberta Montney's richness, and it matters: BC gas economics depend on gas price and LNG offtake, with little liquids cushion. The exception is the northern window at Inga, Fireweed, Town and Attachie, which is genuinely liquids-rich; Groundbirch, Sundown and the North Montney are lean."),
  lead("Reservoir and method. ", "Triassic siltstone — tighter than a sandstone, more permeable than a true shale, which is why it sustains long-term matrix contribution better than the Haynesville. Multi-stage fractured horizontals, typically 2,500–3,500 m laterals, plug-and-perf increasingly the norm in the south where shot density correlates with recovery. Higher pressure gradients and shallower drilling depths than Alberta. Bounded north-to-south by the Fort St John Graben, a faulted zone that is technically hard to develop."),
  lead("Operators, MMcf/d gross, BCER well data. ", ""),
  opTable([
    ["Ovintiv", "1,850"], ["Tourmaline", "1,626"], ["Petronas", "1,246"],
    ["ARC Resources", "1,026"], ["Shell", "767"], ["Canadian Natural", "739"],
    ["Pacific Canbriam", "389"], ["Murphy", "323"],
  ], "MMcf/d"),
  p("This play carries roughly 1.3 Bcf/d of the ~1.9 Bcf/d of Montney growth forecast to 2030 — it is the supply side of the Canadian LNG story. Shell ramped operated volumes to ~700 MMcf/d to serve its LNG Canada equity share.", { muted: true }),

  h2("Deep Basin"),
  sizeLine("3.9 Bcf/d marketable  ·  west-central Alberta, Wapiti to Edson  ·  Peters & Co. 2026E"),
  lead("Liquids. ", "Modest in the tight gas itself. The area's high measured condensate yield belongs to the Duvernay stacked beneath it, not to the Spirit River. Peyto — the cleanest Deep Basin exposure — is genuinely dry-weighted and is the most direct AECO beta among Canadian large caps."),
  lead("Reservoir and method. ", "Multiple stacked tight sandstones — Spirit River, Wilrich, Falher, Dunvegan — over a fairway more than 600 km long. The commercial logic is vertical stacking: one surface location and one pad reach several targets, which is where the cost advantage comes from. Falher shoreface bodies around Kakwa give the best gas results."),
  opTable([
    ["Tourmaline", "741"], ["Peyto", "563"], ["Canadian Natural", "446"],
    ["Whitecap", "174"], ["Cenovus", "170"], ["Vermilion", "156"],
  ], "MMcf/d gross"),

  h2("Alberta Montney"),
  sizeLine("3.4 Bcf/d marketable  ·  Grande Prairie, Kakwa, Karr, Gold Creek  ·  Peters & Co. 2026E"),
  lead("Liquids. ", "Rich — roughly 22 bbl/MMcf, four times the BC side. The condensate is worth more than the gas and prices as C5+ at Edmonton, near or above WTI because oil sands producers must buy it as diluent. So Alberta Montney economics run partly through bitumen demand, and the play has a real cushion when AECO is weak."),
  lead("Reservoir and method. ", "Same Triassic siltstone as BC but deeper and in the condensate window. Liquids-weighted throughout except Glacier and Elmworth, which are lean. Kakwa and Karr are the best of the condensate fairway. Multi-stage fractured horizontals, ~3,200 m median lateral."),
  opTable([
    ["Canadian Natural", "912"], ["Ovintiv", "770"], ["Tourmaline", "690"],
    ["ARC Resources", "624"], ["Advantage", "404"], ["Birchcliff", "400"],
  ], "MMcf/d gross"),
  p("The Charlie Lake — a separate, semi-conventional Triassic oil play — sits in the same geography and produces ~129,000 b/d of crude. Whitecap Partnership, CNRL and Tamarack are the names. Do not conflate the two.", { muted: true }),

  h2("Duvernay"),
  sizeLine("0.8 Bcf/d marketable, growing to ~1.1 by 2030  ·  Peters & Co. 2026E"),
  lead("Liquids. ", "The richest condensate source in Alberta. Pembina's Duvernay Condensate Stabilization facility at Fox Creek alone recovers ~26,000 b/d, the single largest C5+ source in the province. Fastest-growing piece of the WCSB gas balance in percentage terms."),
  lead("Reservoir and method. ", "A true self-sourced shale — Devonian, extremely overpressured, low permeability but high porosity, which is what makes it work. Three areas: Greater Kaybob including Simonette, consistently liquids-rich and the proven core; the West Shale Basin at Willesden Green, Pembina, Brazeau and Edson; and the East Shale Basin around Ghost Pine. Higher-intensity completions have advanced the West Shale Basin most, where inferior mineralogy needs complex fracture networks."),
  opTable([
    ["Canadian Natural", "core Kaybob"], ["Whitecap", "core Kaybob"],
    ["Paramount", "West Shale Basin"], ["Spartan Delta", "West Shale Basin"],
    ["PetroChina", "Kaybob"], ["Kiwetinohk", "Kaybob"],
    ["Artis, Parallax, Tmax, Teine", "East / West Shale Basin, private"],
  ], "position"),
  p("It lies directly beneath the Deep Basin, so no geographic method separates them — formation-level data is required, which Alberta's public well records do not carry.", { muted: true }),

  h2("Everything else — Mannville, shallow gas, southeast Alberta"),
  sizeLine("~4.0 Bcf/d combined  ·  large in volume, small in relevance"),
  p("Mannville coalbed methane is adsorbed gas on coal: very low rate per well, enormous well count, almost no decline, and produced by dewatering rather than pressure depletion. Ember and Pine Cliff run these as near-zero-capital harvest businesses — the opposite temperament to a Montney driller and the cleanest contrast to draw. Southeast Alberta is a declining shallow gas overlay on what is now predominantly heavy oil country."),
  p("Specialist coverage largely excludes these: the greater southern Alberta Mannville has attracted roughly 1% of WCSB capital since 2023. Know they exist, know why they are different, move on.", { muted: true }),

  h1("GAS — UNITED STATES"),

  h2("Appalachia — Marcellus and Utica"),
  sizeLine("37.0 Bcf/d  ·  the largest gas region in North America  ·  EIA 2026 forecast"),
  lead("Liquids. ", "Split. The northeast Marcellus in Pennsylvania is dry gas with essentially no liquids. The southwest Marcellus and the Utica condensate window in Ohio and West Virginia are wet — Antero and Range are the NGL-weighted names, and their economics depend on ethane and propane pricing as much as on gas."),
  lead("Reservoir and method. ", "Devonian and Ordovician shale, the original US shale gas plays. Multi-stage fractured horizontals. Breakevens on the rock are among the lowest on the continent — the constraint has never been geology, it is pipe. Constitution and Atlantic Coast were both cancelled; Mountain Valley took years and litigation."),
  lead("Operators. ", "EQT is the largest Appalachian producer, followed by Expand Energy, Range Resources, Antero and CNX. Expand Energy — the 2024 Chesapeake/Southwestern merger — is the largest US gas producer overall at roughly 7.3–7.5 Bcfe/d company-wide, split between Appalachia and the Haynesville. EQT runs about 6.9 Bcfe/d."),
  p("Because the basin is pipeline-constrained by politics rather than economics, Appalachian basis is structurally negative — Dominion South and Tetco M2 trade well under Henry Hub. A producer's realised price here is a transport story, not a resource story: ask about firm transport commitments before comparing netbacks.", { muted: true }),

  h2("Haynesville — East Texas and North Louisiana"),
  sizeLine("16.3 Bcf/d, up ~9% year on year  ·  EIA 2026 forecast"),
  lead("Liquids. ", "None. Bone dry. Pure exposure to gas price with no liquids cushion at all — the closest US analogue to lean southern BC Montney."),
  lead("Reservoir and method. ", "Deep, hot, high-pressure Jurassic shale. Wells are expensive and decline hard, but deliverability per well is enormous. High-intensity completions. The defining feature is not the rock but the location: a few hundred miles from the Gulf Coast LNG terminals."),
  lead("Operators. ", "Expand Energy is the largest, with Aethon Energy the biggest private position, plus Comstock Resources as a pure play and TG Natural Resources. Rockcliff and the legacy Vine assets are now inside larger names."),
  p("This is the marginal barrel of US gas supply. High cost means fast response — rigs come off near $3 Henry Hub and return near $4 — so Haynesville rig count is the single best leading indicator of whether US gas supply is about to grow. It is the number gas marketers watch.", { muted: true }),

  h2("Permian — associated gas"),
  sizeLine("29.2 Bcf/d, up ~6%  ·  second-largest US gas source  ·  EIA 2026 forecast"),
  lead("Liquids. ", "Extremely rich — but that is backwards here. Nobody drills a Permian well for the gas. The gas is a by-product of oil economics, which is the single fact that drives everything about how it behaves."),
  lead("Reservoir and method. ", "Stacked Wolfcamp, Bone Spring and Spraberry benches across the Midland and Delaware sub-basins, the Delaware being deeper and gassier. Long-lateral multi-stage fractured horizontals from multi-well pads."),
  lead("Why it matters for gas. ", "Supply does not respond to gas price at all. When takeaway fills, producers will pay to dispose of gas rather than curtail oil — Waha traded negative for 158 days in the first five months of 2026, and for a record 12 consecutive days in February. Roughly 4.5–5.3 Bcf/d of new egress is arriving through late 2026 (Matterhorn, Blackcomb, Hugh Brinson, a GCX expansion), most of it landing at Agua Dulce for LNG and Mexico export. Each pipeline fills within months, and the cycle repeats."),

  h2("Eagle Ford and Anadarko"),
  sizeLine("Eagle Ford ~7.3 Bcf/d  ·  Anadarko ~6.5 Bcf/d"),
  lead("Eagle Ford. ", "Three windows — oil north, condensate centre, dry gas south — so operators steer capital toward whichever product prices best. Mature and well understood. Its structural advantage is location: it sits on top of the Gulf Coast refining and export complex, so transport costs are minimal. ConocoPhillips, EOG and Devon are the names."),
  lead("Anadarko — SCOOP and STACK, Oklahoma. ", "Mixed gas and liquids in stacked pay. A first-mover shale play that lost capital to the Permian and Appalachia and is now a cash-harvest basin rather than a growth story. Continental (private), Devon, Coterra and Ovintiv. Useful mainly because Ovintiv and Coterra straddle Anadarko and Canadian or Appalachian assets, making them the natural cross-border comparables."),

  h1("OIL — CANADA"),
  p("Canadian oil is a bitumen story. Roughly 70% of production is oil sands, split between mining and thermal in-situ, and the rest is conventional light oil, cold heavy oil and offshore. The four recovery methods below are the whole subject — each one is an answer to how viscous the oil is.", { after: 140 }),

  h2("Oil sands mining — Athabasca, north of Fort McMurray"),
  sizeLine("~1.7 MMbbl/d  ·  CNRL, Suncor and Imperial are the only mine operators"),
  lead("Product. ", "Raw bitumen at 8–10 °API. Either upgraded into synthetic crude (SCO), which trades at a premium to WTI, or blended with condensate and sold as dilbit."),
  lead("Method. ", "Truck-and-shovel surface mining where the deposit sits under less than about 100 m of overburden. Ore is mixed with hot water and the bitumen separated in a plant. Recovery exceeds 90% — far higher than any in-situ method."),
  lead("Facilities. ", "Suncor Base Plant, Millennium, Steepbank and Fort Hills; CNRL Horizon, Muskeg River and Jackpine; Imperial Kearl; Syncrude Mildred Lake and Aurora North. Upgraders at Suncor, CNRL Horizon, Syncrude, Shell Scotford and the Sturgeon Refinery."),
  p("Withheld entirely from Petrinex public data (facility type OS), so any analysis built on Alberta well records will show Fort McMurray as far quieter than it is.", { muted: true }),

  h2("Athabasca in-situ — SAGD"),
  sizeLine("~1.2 MMbbl/d within total in-situ of ~1.9 MMbbl/d  ·  the core of the Canadian large-cap story"),
  lead("Method — this is the one to be able to explain. ", "Two horizontal wells stacked about 5 m apart in the same bitumen pay. Steam is injected into the upper well and rises, forming a growing steam chamber. Where steam meets cold bitumen it condenses, releasing latent heat and dropping viscosity from roughly 1,000,000 cP to under 10. The mobilised bitumen drains down the chamber flanks under gravity into the lower well, and is pumped to surface. Gravity does the work; the producer sits at the low point catching drips."),
  lead("Why the rock allows it. ", "McMurray sand runs 1–5 darcies — five orders of magnitude more permeable than a Montney shale. Gravity is a weak driving force, so only exceptional permeability makes it work, and the same permeability lets steam penetrate to deliver heat by convection rather than conduction."),
  lead("Economics. ", "Steam-oil ratio is the number: 2.5–3.0 in good rock, 4+ in poor. At 0.25–0.35 GJ of gas per barrel, a SAGD operator is structurally short natural gas — cheap AECO is a tailwind for Cenovus and a headwind for Tourmaline. Base decline is only 5–10%/yr with 25–40 year life, but sustaining capital of $8–12/bbl never stops."),
  opTable([
    ["Cenovus", "367,000"], ["Suncor", "263,000"], ["Canadian Natural", "163,000"],
    ["ConocoPhillips", "148,000"], ["CNOOC", "74,000"], ["MEG (now Cenovus)", "55,000"],
  ], "b/d bitumen"),

  h2("Cold Lake — cyclic steam stimulation"),
  sizeLine("~630,000 b/d  ·  Petrinex well data"),
  lead("Method. ", "One well, cycled rather than two wells running continuously. Steam is injected at high pressure for weeks — often above fracture pressure — then the well soaks, then produces on the stored pressure until rate falls, then repeats. You supply the driving force instead of waiting for gravity."),
  lead("Why not SAGD. ", "The Clearwater sand here is thinner and more heterogeneous than the McMurray, so gravity drainage would be slow and uneven. CSS tolerates worse rock but costs more: 3.5–5.0 SOR against SAGD's 2.5–3.0, and 25–35% recovery against 50–60%."),
  lead("Watch the Grand Rapids. ", "Operators are expanding out of the McMurray into the Grand Rapids — more laterally continuous but thinner and lower quality. Strathcona's Lindbergh was first at full scale, IPC's Blackrod second."),
  opTable([
    ["Cenovus", "218,000"], ["Canadian Natural", "167,000"],
    ["Imperial Oil", "158,000"], ["Strathcona", "62,000"],
  ], "b/d bitumen"),

  h2("Clearwater — cold heavy oil"),
  sizeLine("~180,000 b/d  ·  the best capital efficiency in Canada"),
  lead("Method — the third answer to viscosity. ", "No steam, no fracs. The oil is heavy but just mobile enough to flow at reservoir temperature, so operators drill multilateral horizontals — often 8 to 16 legs off a single vertical — and let it seep in. Shallow at 400–600 m, drilled in days, a fraction of a Montney well's cost. Progressing cavity pumps lift it, since it will not flow to surface."),
  lead("The trade. ", "Recovery of only 5–10% of oil in place against SAGD's 50–60%, and 35–50% annual decline. Cheap per barrel produced, wasteful of the resource, and a permanent drilling treadmill. Short-cycle capital that recycles fast, versus long-cycle capital that keeps producing."),
  lead("Live variable. ", "Waterflood at Marten Hills, where oil rates climb once voidage replacement passes 1x. Headwater and Tamarack carry the most upside if that continues."),
  opTable([
    ["Spur Petroleum", "55,000"], ["Tamarack Valley", "42,000"],
    ["Canadian Natural", "41,000"], ["Headwater", "22,000"],
  ], "b/d liquids"),
  p("Alberta's Modernized Royalty Framework charges 5% until a well pays out its drilling cost, so cheap fast-payout wells sit in that window for much of their life. A real edge, and it is policy rather than geology.", { muted: true }),

  h2("Conventional light oil and Peace River"),
  sizeLine("Cardium ~64,000 b/d · Charlie Lake ~129,000 b/d · Peace River ~42,000 b/d"),
  lead("Cardium. ", "Pembina and Willesden Green — producing since the 1950s and one of the most prolific oilfields in Canada. Mature, waterflooded, and the most fragmented operator set in the province. Several sub-plays: high-permeability conglomerates, upper Cardium clean sands, banked oil in the core, and long-reach horizontals into the halo at Lochend and Wapiti. InPlay, Ricochet, Whitecap, Bonterra, Obsidian, Baytex."),
  lead("Charlie Lake. ", "Semi-conventional Triassic, notoriously inconsistent because internal unconformities make reservoir facies unpredictable. Boundary/Braeburn is the usual target; interbedded anhydrite forces harder fracture stimulation. Whitecap Partnership, CNRL, Tamarack."),
  lead("Peace River. ", "The only area where every recovery method coexists, because bitumen viscosity varies enough across the Bluesky–Gething that the right answer changes field to field: cold multilateral horizontals at Seal and Walrus, CSS where it is thicker, waterflood and polymer flood elsewhere. Baytex, Obsidian, CNRL."),
  p("Also outside this data: Saskatchewan Bakken and Viking (Whitecap is the main public name after Veren), and offshore Newfoundland — Hibernia, Terra Nova, Hebron, White Rose.", { muted: true }),

  h1("OIL — UNITED STATES"),
  p("US oil is a shale story, and one basin dominates it. Every play below is light sweet crude produced by multi-stage fractured horizontals — the variation is in rock quality, decline and location, not in method.", { after: 140 }),

  h2("Permian — Midland and Delaware"),
  sizeLine("6.6 MMbbl/d, 48% of US crude  ·  larger than all of Canada  ·  EIA"),
  lead("Liquids and gas. ", "Very gassy for an oil play and getting gassier as fields mature — 29.2 Bcf/d of associated gas comes with the oil, produced regardless of gas price. Rising gas-oil ratio is a real signal of reservoir maturity and worth watching."),
  lead("Reservoir and method. ", "Stacked Wolfcamp, Bone Spring and Spraberry benches — one surface location accesses many targets, which is the source of the capital efficiency. Delaware is deeper, gassier and more liquids-rich; Midland shallower and oilier. Long laterals from multi-well pads, high proppant intensity."),
  lead("2026 growth is concentrated. ", "East Daley's survey of 14 public operators points to 183,000 b/d of growth, about 2.7%. ExxonMobil alone accounts for roughly 44% of that — 108,000 b/d, or 11% growth. Occidental guides 3.6%, Diamondback 4.5% (27,000 b/d), Chevron about 2%."),
  opTable([
    ["ExxonMobil", "largest, post-Pioneer"],
    ["Occidental", "second, post-CrownRock"],
    ["Chevron", "large Delaware position"],
    ["Diamondback", "largest pure-play independent"],
    ["ConocoPhillips", "post-Marathon"],
    ["Coterra, Devon, Permian Resources", "mid-cap independents"],
  ], "position"),
  p("Consolidation has moved the Permian from a fragmented price-responsive shale patch toward an oligopoly of majors running it for free cash flow. That is why it no longer grows 1 MMbbl/d a year, and why US supply is less price-elastic than in 2018.", { muted: true }),

  h2("Bakken — North Dakota and Montana"),
  sizeLine("1.3 MMbbl/d  ·  flat to maturing  ·  EIA"),
  lead("Liquids. ", "Light sweet crude, roughly 42 °API. Gas is associated and constrained — North Dakota's flaring rules mean gas processing capacity can limit oil drilling, an unusual case of the by-product controlling the main product."),
  lead("Reservoir and method. ", "Bakken and Three Forks, a tight dolomite-siltstone sandwiched between shale source rocks. Multi-stage fractured horizontals. Mature: reduced drilling, declining well productivity in places, more limited access to top-tier locations."),
  lead("Marketing quirk. ", "Substantial rail volumes as well as pipe (Dakota Access), so the differential carries a rail-economics floor. Geographic isolation is the play's permanent handicap."),
  opTable([
    ["Continental Resources", "private, largest"],
    ["ConocoPhillips", "post-Marathon"],
    ["Chevron", "post-Hess"],
    ["Chord Energy", "Whiting + Oasis"],
  ], "position"),

  h2("Eagle Ford — South Texas"),
  sizeLine("1.1 MMbbl/d  ·  mature, geographically advantaged  ·  EIA"),
  lead("Liquids. ", "Windowed — oil in the north, condensate in the middle, dry gas in the south. That optionality lets operators steer capital to whichever product is priced best, which is unusual and valuable."),
  lead("Reservoir and method. ", "Cretaceous marl and shale, well understood after fifteen years. Multi-stage fractured horizontals; refracs and infills are now a material share of activity."),
  lead("Marketing advantage. ", "Minimal transport cost to Corpus Christi and Houston, so crude prices close to waterborne export markets rather than at a Cushing discount — the mirror image of the Appalachian problem. ConocoPhillips, EOG, Devon, Crescent Energy."),

  h2("Niobrara / DJ and Gulf of Mexico"),
  sizeLine("Niobrara ~0.7 MMbbl/d  ·  Gulf of Mexico ~1.8 MMbbl/d"),
  lead("DJ Basin. ", "Front Range Colorado. Good rock, but the binding constraint is regulatory rather than geological — Colorado has the most restrictive permitting and setback regime of any major producing state, which caps growth independent of price. Chevron (post-PDC), Civitas, Occidental. The useful counterexample when someone assumes geology always sets the limit."),
  lead("Gulf of Mexico. ", "Long-cycle deepwater — the opposite temperament to shale. Long lead times, high capital, very low decline once producing, and one of the few US sources still growing in 2026 alongside the Permian and Alaska. Shell, BP, Chevron, Occidental, Equinor. It is to shale what SAGD is to Clearwater."),
  p("Also: Uinta waxy crude in Utah, which must be kept heated to flow and moves by rail at a discount — a good test of whether someone understands crude quality. And Alaska North Slope, where ConocoPhillips Willow is the growth project.", { muted: true }),

  h1("Cross-checks and where these numbers came from"),
  opTable([
    ["US gas and oil by region", "EIA 2026 forecast / 2025 actual"],
    ["WCSB gas balance by play", "Peters & Co. WCSB update, Aug 2026"],
    ["BC Montney well data", "BCER production, formation code 5000"],
    ["Alberta well volumes", "Petrinex volumetrics + AER ST37"],
    ["Oil sands facilities and mining", "Oil Sands Magazine / CAPP / AER"],
    ["Permian 2026 operator growth", "East Daley Analytics"],
    ["Play names and sub-areas", "HTM Energy Research WCSB Atlas, Jun 2025"],
  ], "source"),
  lead("One computed figure, and why it is trustworthy. ", "BC Montney gas was calculated independently from BCER well records at 8.88 Bcf/d gross. Applying the 15% shrinkage Peters itself assumes gives 7.54 Bcf/d marketable against their published 7.5 — agreement within 0.5%, from raw well data with no calibration. The condensate yields quoted for BC (5.3 bbl/MMcf) and Alberta (22.1) come from the same computation."),
  lead("One figure to treat with care. ", "The Alberta Montney and Deep Basin split. Geographic attribution puts the boundary in the wrong place — measured against Peters, Alberta Montney reads 32% high and the Deep Basin 32% low, in equal and opposite directions, because the two overlap and wells fall into whichever box is defined first. The combined fairway reconciles within 12%. Quote the published split, not a geographic one."),
  bullet("Gas volumes here are marketable. Wellhead figures from Petrinex run 10–15% higher; never place the two side by side."),
  bullet("Oil sands mining is absent from Alberta public well data entirely — Petrinex withholds facility type OS."),
  bullet("Duvernay cannot be separated from the Deep Basin by surface location. Only formation-coded data does it, which BC has and Alberta does not."),
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
