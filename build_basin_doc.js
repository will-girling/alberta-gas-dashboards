// Build the Canadian play/operator reference as a Word document.
//
// Figures are twelve-month averages to June 2026, computed from Petrinex
// volumetrics joined to AER ST37. An earlier version quoted a single
// month, which was the seasonal trough and understated every gas figure
// by about a tenth, and used well-level condensate, which is a function
// of where liquids are metered rather than what wells produce. Both are
// fixed at source here rather than footnoted.

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
      text: "Canadian Plays and Operators", bold: true, size: 38, color: ACCENT,
    })],
  }),
  new Paragraph({
    spacing: { after: 200 },
    border: { bottom: RULE },
    children: [new TextRun({
      text: "Twelve-month averages to June 2026 · Petrinex volumetrics joined to AER ST37",
      size: 21, color: MUTED,
    })],
  }),

  lead("Reading the numbers. ",
    "Everything is a daily rate averaged over the twelve months to June 2026. Gas is gross wellhead volume as Petrinex reports it, which runs roughly 10–15% above the marketable basis used by AER and the brokers. Condensate is C5+ recovered at gas plants, geocoded to the plant. BOE is 6 Mcf to 1 barrel — energy equivalence, not economic, so never rank a gas play against an oil one on BOE alone."),
  p("Alberta: 13.0 Bcf/d gas · 267 Mbbl/d condensate · 532 Mbbl/d conventional crude · 1.96 MMbbl/d bitumen · 4.94 MMboe/d. Add roughly 1.3 MMbbl/d for oil sands mining, which Petrinex does not publish.", { after: 180, muted: true }),

  h1("The basin at a glance"),
  opTable([
    ["Athabasca in-situ", "1,203,000"],
    ["Montney (Alberta)", "1,129,000"],
    ["Cold Lake", "666,000"],
    ["Deep Basin", "660,000"],
    ["Cardium and central foothills", "354,000"],
    ["Mannville", "282,000"],
    ["Clearwater", "201,000"],
    ["Lloydminster corridor and southeast", "130,000"],
    ["Peace River", "53,000"],
  ], "boe/d"),
  p("Two thermal oil plays and one liquids-rich gas play are three quarters of Alberta. Everything else is a rounding error by comparison — which is worth remembering when a conversation drifts toward a small-cap story.", { muted: true }),

  h1("Gas plays"),

  h2("Montney — Alberta side"),
  p("Kakwa, Karr, Gold Creek, Wapiti, Gordondale, Pouce Coupe, Pipestone. The largest gas play in the province and the one that matters for LNG. Liquids-rich: 22 barrels of condensate per MMcf, and the condensate is worth more than the gas. It prices as C5+ at Edmonton, quoted against WTI, and usually trades near or above it because it is the diluent oil sands producers must buy. So Montney economics run partly through bitumen demand."),
  p("The Alberta fairway is liquids-weighted almost throughout, the exceptions being Glacier and Elmworth, which are lean gas. Kakwa and Karr are the best of the condensate window and are dominated by ARC and Ovintiv. Only the Lower and Middle Montney are pervasive across Alberta.", { muted: true }),
  sizeLine("1,129,000 boe/d  —  5,270 MMcf/d gas · 116,541 b/d condensate · 128,608 b/d crude  ·  22% liquids"),
  opTable([
    ["Canadian Natural", "912"], ["Ovintiv", "770"], ["Tourmaline", "690"],
    ["ARC Resources", "624"], ["Advantage", "404"], ["Birchcliff", "400"],
  ], "MMcf/d gas"),
  lead("The oil beside the gas is mostly the Charlie Lake, a separate play. ", "128,608 b/d of crude sits inside this box and belongs to a different set of firms. The Charlie Lake is a semi-conventional Triassic play, notoriously inconsistent because internal unconformities make reservoir facies unpredictable; the Boundary/Braeburn member is the usual target, and interbedded anhydrite forces harder fracture stimulation. Grande Prairie is two industries sharing a postal code, and they should be named separately."),
  opTable([
    ["Whitecap Partnership", "39,672"], ["Canadian Natural", "29,598"],
    ["Tamarack Valley", "8,927"], ["Whitecap Resources", "6,979"],
    ["Tourmaline", "6,802"], ["Advantage", "6,580"],
  ], "b/d liquids"),
  p("Other Charlie Lake names: Archer, Bonterra, Cardinal, Coelacanth, Kelt, Logan, Paramount, Prairie Thunder.", { muted: true }),
  lead("The BC side. ", "Groundbirch and Sundown in the south; Dawson and Cutbank Ridge in the middle; Town, Attachie, Inga and Fireweed to the north; then North Montney and Birch. Drier and richer-gas weighted than Alberta, higher pressure gradients, shallower. The Fort St John Graben — a zone of extreme faulting — splits the play north from south. Inga and Fireweed are the best of the BC oil and condensate; Groundbirch through Sundown the best lean gas, and directly competitive with the Haynesville and Marcellus on gas in place per section."),
  p("BC is larger than the Alberta side and carries most of the forecast WCSB growth. It is not in this data; see the separate Montney supply brief.", { muted: true }),

  h2("Deep Basin and Duvernay — Wapiti to Edson"),
  p("West-central Alberta tight gas, with the Duvernay directly beneath it. Spirit River, Wilrich, Falher and Dunvegan stack vertically, so one surface location reaches several targets — that is where the cost advantage comes from. The fairway runs more than 600 km southeast to northwest, and the strongest gas results have come from Falher shoreface bodies around Kakwa."),
  p("The Duvernay divides into three: Greater Kaybob, including Simonette, which is consistently liquids-rich and extremely overpressured; the West Shale Basin at Willesden Green, Pembina, Brazeau and Edson; and the East Shale Basin around the Ghost Pine embayment. Kaybob is the proven core, the West Shale Basin the area higher-intensity completions have most advanced.", { muted: true }),
  sizeLine("660,000 boe/d  —  3,105 MMcf/d gas · 114,804 b/d condensate · 24,410 b/d crude  ·  22% liquids"),
  opTable([
    ["Tourmaline", "741"], ["Peyto", "563"], ["Canadian Natural", "446"],
    ["Whitecap", "174"], ["Cenovus", "170"], ["Vermilion", "156"],
  ], "MMcf/d gas"),
  lead("The condensate story is the Duvernay, not the tight gas. ", "At 37 bbl/MMcf this area yields more liquids per unit of gas than the Montney does — Pembina's Duvernay Condensate Stabilization facility at Fox Creek alone recovers about 26,000 b/d, the largest single C5+ source in Alberta. Kaybob, Fox Creek and Simonette are condensate centres."),
  lead("Peyto is the exception that proves it. ", "Peyto is genuinely dry-weighted and is the cleanest AECO beta among the Canadian large caps: almost no liquids cushion under the gas price, and correspondingly the most torque in a gas rally. Generalising from Peyto to the whole area gets the liquids picture backwards."),

  h2("Cardium and central foothills"),
  p("Pembina and Willesden Green — one of the most prolific oilfields in Canada, producing since the 1950s. Mature, waterflooded, and the most fragmented operator set in the province. It carries several distinct sub-plays: high-permeability conglomerates, upper Cardium clean sands, horizontal wells into banked oil in the core, and long-reach horizontals into the halo extension at Lochend and Wapiti, where recent results have been strongest."),
  sizeLine("354,000 boe/d  —  1,587 MMcf/d gas · 64,369 b/d crude · 24,981 b/d condensate  ·  25% liquids"),
  opTable([
    ["Ricochet Oil", "9,445"], ["InPlay Oil", "8,684"],
    ["Whitecap Resources", "6,490"], ["Spartan Delta", "5,655"],
    ["Bonterra", "4,435"], ["Baytex", "3,734"],
  ], "b/d liquids"),
  opTable([
    ["TAQA North", "214"], ["Spartan Delta", "199"], ["Vermilion", "169"],
    ["Tourmaline", "152"], ["Peyto", "107"], ["Cenovus", "84"],
  ], "MMcf/d gas"),
  p("Also Cardinal, Aspenleaf, Yangarra and Obsidian on the oil side.", { muted: true }),

  h2("Mannville — coalbed methane and conventional oil"),
  p("Central Alberta. Two businesses sharing a map. The coalbed methane is very low rate per well across an enormous well count, with almost no decline — Ember is the pure play and drills essentially nothing, harvesting existing wells. Alongside it, Mannville and Glauconite sand pools produce 78,000 b/d of conventional oil for a completely different operator set."),
  sizeLine("282,000 boe/d  —  1,191 MMcf/d gas · 77,822 b/d crude  ·  30% liquids"),
  opTable([
    ["Ember Resources", "170"], ["Whitecap", "137"], ["Canadian Natural", "134"],
    ["Rockpoint Gas Storage", "91"], ["ATCO Next Energy", "86"], ["Lynx Energy", "72"],
  ], "MMcf/d gas"),
  opTable([
    ["Parallax Energy", "13,425"], ["Aspenleaf Energy", "12,461"],
    ["Canadian Natural", "8,850"], ["Artis Exploration", "7,474"],
    ["Whitecap Resources", "3,082"], ["North 40 Resources", "3,024"],
  ], "b/d liquids"),
  lead("The Glauconite is the part worth knowing. ", "Central Alberta's Glauconite targets a large sand bar complex — the Hoadley Barrier Bar — with substantial rich gas in place. Porosity improves northward while pressure rises southward, and horizontal drilling has revived historically unproducible lower-porosity sand. Southeast of the bar it becomes stringy lithic channels running into southern Alberta, with smaller shoreface bodies around Caroline and Willesden Green. TAQA, Whitecap and Pine Cliff are the active names."),
  p("Specialist coverage generally excludes this area and the shallow gas fairway as non-core: the greater southern Alberta Mannville has attracted on the order of 1% of WCSB capital since 2023. Worth knowing, not worth pitching.", { muted: true }),
  lead("Why the CBM matters commercially. ", "Coalbed methane is adsorbed gas on coal, not free gas in pores, so it needs dewatering rather than pressure depletion and it barely declines. That makes Ember and Pine Cliff near-zero-decline, near-zero-capital cash businesses — the opposite temperament to a Montney driller, and a useful contrast when someone asks how two gas producers can look so different."),

  h2("Lloydminster corridor and southeast Alberta"),
  p("Medicine Hat east to the Saskatchewan line. Once a shallow gas province; now predominantly heavy oil with a legacy gas overlay that is steadily disappearing. At 41% liquids and 2.6 bbl/MMcf, the oil is the value and the gas is the remnant."),
  sizeLine("130,000 boe/d  —  461 MMcf/d gas · 52,149 b/d crude  ·  41% liquids"),
  opTable([
    ["Canadian Natural", "23,221"], ["IPC Canada", "9,418"],
    ["Hemisphere Energy", "3,527"], ["Cardinal Energy", "3,332"],
    ["Astara Energy", "3,078"], ["Journey Energy", "2,435"],
  ], "b/d liquids"),
  p("The oil is Lloydminster blend, priced off WCS and needing some diluent of its own — far less than bitumen, since it is 12–16 °API rather than 8–10. CNRL and IPC both run thermal and polymer flood projects here. Strathcona's Lloydminster Thermal assets sit across the Saskatchewan line and are not in this data.", { muted: true }),
  p("Rockpoint Gas Storage appears in the gas table at 104 MMcf/d because storage cycling reports as production; it is not new supply.", { muted: true }),

  h1("Oil plays"),

  h2("Athabasca in-situ — Christina Lake, Foster Creek, Firebag, Surmont"),
  p("SAGD. Paired horizontal wells, steam injected above, heated bitumen draining by gravity into the producer below. The largest single pool of production in the country and the core of the Canadian large-cap story: low decline, long life, and capital that never stops, because new well pairs are drilled continuously to keep the central plant full. Growth arrives in lumps as plants expand, which is why thermal names guide to named projects rather than a rig count."),
  sizeLine("1,203,000 boe/d  —  1,159,926 b/d bitumen · 261 MMcf/d gas  ·  96% liquids"),
  opTable([
    ["Cenovus", "367,175"], ["Suncor", "263,485"], ["Canadian Natural", "163,045"],
    ["ConocoPhillips", "147,894"], ["CNOOC Petroleum", "74,208"], ["MEG Energy", "55,118"],
  ], "b/d bitumen"),
  lead("The gas connection. ", "SAGD burns 0.25–0.35 GJ of natural gas per barrel to make steam, so a thermal producer is structurally short gas. Cheap AECO is a margin tailwind for Cenovus and a headwind for Tourmaline — the two sides of the basin are not independent bets."),

  h2("Cold Lake"),
  p("Cyclic steam stimulation rather than SAGD. One well, cycled: inject steam at high pressure for weeks, let it soak, produce until rate falls, repeat. The Clearwater sand here is thinner and more heterogeneous than the McMurray, so gravity drainage would be slow and uneven — CSS supplies its own pressure instead. It burns more gas per barrel and recovers 25–35% of oil in place against SAGD's 50–60%, which is the price of forcing rock that will not cooperate for free."),
  sizeLine("666,000 boe/d  —  631,385 b/d bitumen · 211 MMcf/d gas  ·  95% liquids"),
  opTable([
    ["Cenovus", "218,290"], ["Canadian Natural", "166,717"],
    ["Imperial Oil", "157,826"], ["Strathcona Resources", "61,959"],
    ["Caltex Trilogy", "12,258"], ["Baytex", "6,664"],
  ], "b/d bitumen"),
  lead("Watch the Grand Rapids. ", "Operators in the southern Cold Lake area are expanding out of the McMurray into the Grand Rapids — a more laterally continuous shoreface sand, but thinner and lower quality. Strathcona's Lindbergh was the first full-scale project, IPC's Blackrod the second. It is the main source of incremental in-situ inventory in the area."),

  h2("Clearwater — cold heavy oil at Marten Hills, Peavine and Nipisi"),
  p("Classed as cold heavy oil rather than oil sands, and the best capital efficiency in Canada — a third answer to the viscosity problem. The oil is heavy but mobile enough to flow cold, so no steam and no fracs — just multilateral horizontal wells, often eight to sixteen legs off one vertical, drilled in days for a fraction of a Montney well. Shallow, cheap, fast payout."),
  sizeLine("201,000 boe/d  —  105,889 b/d bitumen · 75,623 b/d crude · 118 MMcf/d gas  ·  90% liquids"),
  opTable([
    ["Spur Petroleum", "55,400"], ["Tamarack Valley", "41,971"],
    ["Canadian Natural", "41,194"], ["Headwater Exploration", "21,710"],
    ["Cardinal Energy", "4,379"], ["Islander Oil & Gas", "3,266"],
  ], "b/d liquids"),
  lead("The trade-off. ", "Cold production recovers only 5–10% of oil in place, against SAGD's 50–60%. Cheap per barrel produced, wasteful of the resource. And decline runs 35–50% a year, so a Clearwater producer is on a drilling treadmill in a way a SAGD operator is not — short-cycle capital that recycles fast, versus long-cycle capital that keeps producing."),
  p("Waterflood is the live variable. Results at Marten Hills have been strong, with oil rates climbing once voidage replacement passes 1x, and Headwater and Tamarack carry the most upside if that continues. Beyond the main Clearwater sand, the Grand Rapids and Wabiskaw provide localised inventory.", { muted: true }),
  p("Alberta's Modernized Royalty Framework charges 5% until a well pays out its drilling cost, so cheap fast-payout wells sit in that window for much of their productive life. A real edge, and it is policy rather than geology.", { muted: true }),

  h2("Peace River"),
  p("The most methodologically diverse oil area in Alberta, and the only one where every recovery technique coexists. Bitumen viscosity varies enough across the Bluesky–Gething that the right answer changes field to field: cold multilateral horizontals at Seal and Walrus, CSS where the oil is thicker, and waterflood or polymer flood elsewhere."),
  sizeLine("53,000 boe/d  —  39,074 b/d bitumen · 2,779 b/d crude · 66 MMcf/d gas  ·  79% liquids"),
  opTable([
    ["Baytex", "15,278"], ["Obsidian Energy", "11,557"],
    ["Canadian Natural", "10,248"], ["Spur Petroleum", "1,352"],
    ["Surge Energy", "1,328"], ["Prairie Thunder", "810"],
  ], "b/d liquids"),
  p("Useful as the counterexample to any claim that a play has one right development method. Peace River's answer is 'it depends on the pool'.", { muted: true }),

  h1("Not in this data"),
  bullet("Oil sands mining — Suncor Base Plant and Fort Hills, CNRL Horizon and AOSP, Imperial Kearl, Syncrude. Roughly 1.7 MMbbl/d, with CNRL, Suncor and Imperial the only mine operators. Petrinex withholds facility type OS entirely, so the Fort McMurray area looks far quieter here than it is."),
  bullet("BC Montney — Groundbirch, Dawson Creek, Fort St John. Tourmaline, ARC, Ovintiv, Petronas, Shell. Covered on activity in the separate Montney supply brief; BCER does not publish accessible production."),
  bullet("Saskatchewan — Bakken and Torquay around Estevan, Viking in the southwest, Strathcona's Lloydminster Thermal. Whitecap is the main public Bakken name after the Veren acquisition."),
  bullet("Offshore Newfoundland — Hibernia, Terra Nova, Hebron, White Rose. Suncor, Cenovus, ExxonMobil."),

  h1("Gas marketing"),
  p("Canadian gas marketing differs from the US in one structural way that explains most of the rest: NGTL is a single integrated system with a postage-stamp toll, not a set of competing point-to-point pipes with tradeable firm capacity. You do not buy a path from A to B. You buy receipt service and delivery service on one pool."),

  h2("Hubs"),
  opTable([
    ["AECO / NIT", "the Alberta benchmark; a notional trading pool, not a place"],
    ["Station 2", "northeast BC, upstream of Westcoast processing"],
    ["Empress", "Alberta/Saskatchewan border; TC Mainline handoff"],
    ["Kingsgate", "Alberta/BC border to the US; feeds GTN"],
    ["Huntingdon / Sumas", "BC to Washington State"],
    ["Dawn, Ontario", "eastern storage and trading hub"],
  ], "what it is"),
  p("AECO is a pool rather than a physical junction — gas is deemed delivered anywhere on NGTL. That is why AECO and NGTL operational conditions are so tightly linked: a maintenance event that strands supply moves the price of a hub that has no location.", { muted: true }),

  h2("How service on NGTL works"),
  lead("Receipt and delivery service. ", "Producers contract firm receipt service to put gas on the system and firm delivery service to take it off at a specific point. The two are separate contracts, and a shortage of either constrains flow. This is genuinely different from the US model, where you buy capacity on a defined path."),
  lead("Firm versus interruptible. ", "Firm service is reserved and paid whether used or not. Interruptible is cheaper and cut first. During maintenance, interruptible service goes before firm — which is why outage notices move AECO before any physical volume changes."),
  lead("Why linepack matters commercially. ", "NGTL operates within a tolerance band, and the system's ability to absorb a mismatch between receipts and deliveries is finite. When linepack is drawn down, TC issues operational notices restricting receipts. Your dashboard's decomposition — receipts, deliveries, storage, interprovincial flows and fuel summing to the linepack change — is the physical statement of that constraint."),

  h2("Egress and what competes for the gas"),
  opTable([
    ["TC Mainline", "east from Empress to Ontario and Quebec"],
    ["Foothills / GTN", "south from Kingsgate to the US West Coast"],
    ["Alliance", "liquids-rich gas direct to Chicago, bundled service"],
    ["Westcoast T-South", "northeast BC to Huntingdon/Sumas"],
    ["Coastal GasLink", "to LNG Canada at Kitimat"],
  ], "route"),
  p("Alliance is the outlier and worth knowing: it is a wet-gas pipeline that carries liquids-rich gas without full field processing, extracting NGLs at Aux Sable near Chicago. So an Alliance shipper is selling into Chicago basis rather than AECO, and capturing NGL value at the far end. It is the closest thing Canada has to a competing path.", { muted: true }),
  lead("LNG Canada is the structural change. ", "The first material new demand for WCSB gas in decades. Cedar LNG and Woodfibre follow. The distinction that matters for equities is pricing: LNG Canada offtake is largely AECO-linked, while Cedar has JKM exposure. A producer selling into JKM is in a different price world from one selling at an AECO-linked netback, and that difference is the entire argument about who captures Canadian LNG value."),

  h2("NGL and straddle plants"),
  p("Liquids are stripped in two places: at field plants near the wellhead, and at straddle plants sitting on the mainline at Empress and Cochrane, which pull remaining NGLs out of gas already in transit. Fort Saskatchewan is the fractionation and storage hub — the Canadian Mont Belvieu."),
  bullet("C5+ (pentanes plus) — diluent for bitumen. Prices near WTI at Edmonton because oil sands demand is captive. Covered in detail in the condensate section above."),
  bullet("Propane — heating and export. Ridley Island and Prince Rupert opened Asian export capacity, which structurally lifted Canadian propane off a Conway-linked discount."),
  bullet("Ethane — Alberta petrochemical feed (NOVA, Dow). Alberta is one of the few places where an integrated ethane-to-plastics chain sits beside the gas supply."),

  h1("Oil marketing"),
  p("Canada's crude problem is the mirror image of its gas problem: a large volume of a differentiated product, few routes to market, and a price set by buyers a long way away."),

  h2("Benchmarks"),
  opTable([
    ["WCS at Hardisty", "heavy blend; the headline Canadian benchmark"],
    ["Edmonton Par / MSW", "light sweet, the Canadian WTI analogue"],
    ["C5+ Edmonton", "condensate; near WTI, diluent-driven"],
    ["SCO / Syncrude Sweet", "upgraded synthetic, premium to WTI"],
    ["Lloyd blend", "heavy conventional, Lloydminster corridor"],
  ], "what it is"),
  p("Hardisty is the physical centre of gravity — roughly 13 million barrels of storage, the largest crude hub in Canada, and the origin point for Keystone and much of the Mainline's heavy service.", { muted: true }),
  lead("What the WCS differential actually is. ", "Three things stacked: the quality discount for heavy sour crude that needs a coker, the transport cost to reach a refinery that has one, and a scarcity premium when egress is tight. Only the third is volatile. When people say the differential blew out, they almost always mean pipeline capacity ran short, not that the crude got worse."),

  h2("Egress"),
  opTable([
    ["Enbridge Mainline", "~3.2 MMb/d, to the US Midwest"],
    ["Trans Mountain / TMX", "to Burnaby and tidewater"],
    ["Keystone", "to Cushing and the Gulf Coast"],
    ["Express-Platte", "to the Rockies and Midwest"],
    ["Crude by rail", "the marginal, high-cost outlet"],
  ], "route"),
  lead("Apportionment — the Canadian-specific concept. ", "When nominations exceed pipeline capacity, shippers are cut back pro rata rather than bidding for space. This is the crucial difference from the US, where firm capacity is contracted and tradeable. Apportionment means a Canadian producer cannot buy its way out of a constraint, and it is why egress shortages translate so directly into price rather than into transport cost."),
  p("In 2025 the Mainline ran at 95.2% utilisation on 3.23 MMb/d of available capacity — the highest since 2019 — yet apportionment stayed generally below 10% per month, because TMX absorbed the incremental barrel. Trans Mountain has seen no apportionment since start-up. That is the clearest possible evidence of what one new pipeline does to a constrained system.", { muted: true }),
  lead("Why TMX mattered more than its size. ", "590,000 b/d is not large against 4 MMbbl/d of exports. But it was the first route to tidewater, so it introduced a second buyer. Before TMX, Canadian heavy had one customer — US refiners — and a monopsony sets the price. After TMX, a barrel can reach Asia or the US West Coast, which puts a floor under the differential that did not previously exist."),

  h2("Where the barrels actually go"),
  p("Overwhelmingly to US refiners in PADD 2 and PADD 3, which built coking capacity specifically to run heavy sour crude. Canada itself has very little complex refining — the Co-op Refinery at Regina, Imperial's Strathcona, Sturgeon — so the value of upgrading is captured mostly in the United States."),
  p("The symmetry worth stating: the US produces light sweet shale crude its refineries were not built for, and operates cokers with no domestic heavy supply. Canada produces heavy sour and cannot refine it. The two systems are complements. That is why WCS is priced against Gulf Coast coking margins rather than against anything Canadian.", { muted: true }),

  h1("Terminology"),

  h2("Producing techniques"),
  term("SAGD", "Steam Assisted Gravity Drainage. Two horizontal wells stacked about five metres apart; steam injected into the upper one heats the bitumen until it flows, and gravity drains it into the lower producer. Gas-intensive, so a SAGD operator's operating cost moves with AECO — thermal producers are a large source of Alberta gas demand."),
  term("CSS", "Cyclic Steam Stimulation, or \"huff and puff\". One well alternately injects steam and produces. Used at Cold Lake."),
  term("Mining", "Truck-and-shovel oil sands recovery where the deposit is shallow enough to dig, north of Fort McMurray. Not drilling at all, and withheld from this data."),
  term("SOR", "Steam-to-Oil Ratio — barrels of steam per barrel of bitumen. The efficiency metric for thermal projects: roughly 2.5 to 3.0 is good, above 4 is poor. Compared across projects the way well cost is compared in a shale play."),
  term("Multilateral", "Several horizontal legs drilled from one wellbore, spreading a single surface location across much more reservoir. The reason Clearwater wells are so capital-efficient."),

  h2("Volumes and well metrics"),
  term("BOE", "Barrel of Oil Equivalent, converting gas at 6 Mcf to 1 barrel. An energy equivalence, not an economic one — at roughly $70 oil and $2 gas a gas boe is worth a fraction of an oil boe, which is why gas-weighted names always screen cheap on EV/boe."),
  term("EUR", "Estimated Ultimate Recovery — everything a well will produce over its life. The number behind every type curve and NAV, and contested because it extrapolates decline decades past what has been observed. Cannot be derived from five years of production data; it comes from a reserve report."),
  term("IP30 / IP90", "Initial production averaged over the first 30 or 90 days. The standard well-quality benchmark. Note the first partial month understates a well badly — use month one or a three-month average."),
  term("Base decline", "How fast existing production falls without new drilling. Alberta gas runs about 25% a year; SAGD thermal is nearer 5 to 10%. The gap is the whole low-sustaining-capital argument for thermal names."),
  term("TIL", "Turned In Line — a well brought onto production. \"TIL count\" is an activity measure."),
  term("DUC", "Drilled but UnCompleted. Inventory between drilling and production; operators can add supply by working down DUCs without drilling, so it is a swing factor."),
  term("Type curve", "The expected production profile of an average well in a play, used to forecast and to value undrilled locations."),

  h2("Products and benchmarks"),
  term("WCS at Hardisty", "Western Canadian Select — the heavy blended barrel, and the benchmark for oil sands and heavy oil. Its differential to WTI is driven by egress, and TMX is what changed it."),
  term("MSW / Edmonton Par", "Edmonton Light Sweet, the Canadian light crude benchmark. Distinct from condensate despite both quoting at Edmonton."),
  term("C5+ at Edmonton", "Pentanes plus — condensate, quoted against WTI. Demand comes from diluent rather than refining, and Western Canada is short, importing via Cochin. Frequently trades at or above WTI, unusual for a Canadian barrel."),
  term("Dilbit / diluent", "Bitumen will not flow in a pipeline, so it is blended with roughly 25 to 30% condensate to make dilbit. This is the link between the Montney and the oil sands: condensate demand is a function of thermal growth."),
  term("AECO", "The Alberta gas hub, priced on NGTL. Station 2 is the northeast BC equivalent; Dawn is Ontario; Henry Hub is the US benchmark."),
  term("Basis", "The differential between two hubs — AECO to Henry Hub, say. Driven by pipeline constraint, which is why outages and capacity move it."),

  h2("Transport and projects"),
  term("FT / IT", "Firm and Interruptible Transportation. Firm shippers hold contracted capacity; interruptible is curtailed first when a pipeline is constrained. FT-R is receipt-side, FT-D delivery-side."),
  term("FID", "Final Investment Decision — the point a project is sanctioned. Pre-FID projects are optionality; post-FID they belong in a supply forecast."),
  term("Egress", "Pipeline capacity out of the basin. The binding constraint on Canadian oil pricing, and the reason WCS trades at a differential at all."),

  h2("Valuation"),
  term("EV/DACF", "Enterprise value to debt-adjusted cash flow. The Canadian standard because it neutralises leverage and capital structure across comparables."),
  term("NAV", "Net asset value, usually the PV-10 of 2P reserves. Forces engagement with decline, reserve life and the price deck."),
  term("$/flowing barrel", "EV divided by current daily production. Standard for transaction comps, and misleading twice over: it ignores the 6:1 boe distortion and ignores decline, so two companies at the same $/flowing can have completely different sustaining capital."),
  term("Netback", "Realised price less transport, royalties and operating cost — what the producer actually keeps per barrel."),
  term("F&D / recycle ratio", "Finding and development cost per boe; the recycle ratio is netback divided by F&D, a measure of capital efficiency."),

  h1("Two things most candidates cannot say"),
  lead("Alberta gas runs a 25% base decline. ",
    "Wells producing a year ago make 3.2 Bcf/d less today. New wells added 3.7 Bcf/d, holding the province roughly flat at 13.2 Bcf/d. Wells under three years old are 82% of supply."),
  lead("Horizontal well productivity peaked in 2024. ",
    "Measured at the same month of life, restricted to wells that ever exceed 1 MMcf/d, the 2024 cohort beats 2025 at every age. The basin holds production by drilling more wells, not better ones — which makes supply more sensitive to a capital pullback than a flat production line suggests."),
  p("Both are derived from well-level data, and both are falsifiable.", { italic: true }),

  h1("Play naming — how this maps to industry usage"),
  p("Specialist coverage of the WCSB works with roughly a dozen named plays accounting for about 95% of production. This document is organised around measurable geographic areas, which does not always line up one-to-one. The differences worth knowing:"),
  opTable([
    ["Montney (Alberta)", "Montney fairway + Charlie Lake"],
    ["Deep Basin", "Deep Basin + Duvernay + Dunvegan"],
    ["Cardium / central foothills", "Cardium, incl. Lochend and Wapiti halo"],
    ["Mannville", "Mannville CBM + Glauconite / Hoadley"],
    ["Athabasca in-situ, Cold Lake", "Oil Sands (SAGD and CSS)"],
    ["Clearwater", "Cold Heavy Oil"],
  ], "industry play name"),
  bullet("Charlie Lake is a distinct play, not part of the Montney. It sits inside the Montney box here because the two overlap geographically; the 128,608 b/d of crude in that section is largely Charlie Lake."),
  bullet("Duvernay cannot be separated from the Deep Basin by surface location — it lies directly beneath. Splitting them needs formation-level attribution, which Alberta's public well data does not carry."),
  bullet("Mannville and southeast Alberta shallow gas are generally excluded from specialist coverage as non-core. They are included here because they are large in volume and explain a third of Alberta's well count."),
  bullet("Nomenclature cross-checked against the HTM Energy Research public WCSB Play Atlas, June 2025."),
  h1("Benchmarking against a published forecast"),
  p("Peters & Co.'s August 2026 WCSB update publishes supply by play on a marketable, formation-based basis. Setting this document's gross wellhead figures against it — applying the 15% shrinkage Peters itself assumes — shows exactly where the geographic boxes hold and where they do not."),
  opTable([
    ["AB Montney", "4.5 vs 3.4  (+32%)"],
    ["Deep Basin", "2.6 vs 3.9  (−32%)"],
    ["Combined fairway incl. Duvernay", "7.1 vs 8.1  (−12%)"],
    ["Alberta total", "11.1 vs ~11.6  (−4%)"],
  ], "mine vs Peters, Bcf/d"),
  lead("The combined number reconciles; the split does not. ", "Within 12% across the whole liquids-rich fairway and within 4% at province level, which is about what shrinkage assumptions and box edges should cost. But the internal split is out by ±32% in equal and opposite directions — the Montney box takes acreage that belongs to the Deep Basin, because wells fall into the first box containing them and the Montney is defined first."),
  p("So: quote this document for operator composition, liquids weighting and relative scale. Quote a formation-based source for the Montney/Deep Basin split. The two are answering different questions and the geographic version loses on that particular one.", { muted: true }),
  p("Peters' 2026E figures used above: AB Montney 3.4, Deep Basin 3.9, Duvernay 0.8, WCSB total 19.7 Bcf/d.", { muted: true }),

  p("Two further checks that this attribution is not far off: this document's Deep Basin box returns 660,000 boe/d against roughly 650 MBOE/d of horizontal Deep Basin production in that atlas, and its Charlie Lake operator list — Archer, Bonterra, Cardinal, Kelt, Paramount, Tamarack, Tourmaline, Whitecap — matches the firms appearing in the liquids table above.", { muted: true }),

  h1("Method"),
  p("Operator volumes are measured, not sourced: Petrinex volumetric data joined to AER ST37, attributed by well licensee, averaged over the twelve months to June 2026. Play assignment is geographic — wells are binned by bottom-hole location — and validated against known footprints. Imperial's Cold Lake figure equals its entire Alberta output, which is correct; Athabasca returns Cenovus, Suncor, ConocoPhillips and CNOOC; Clearwater returns Spur, Tamarack and Headwater."),
  bullet("Gas is gross wellhead. AER and broker forecasts use marketable gas, roughly 10–15% lower. Compare growth rates across the two freely; convert before comparing levels."),
  bullet("Condensate is C5+ recovered at gas plants, geocoded to the plant. Well-level condensate in Petrinex reflects where liquids are metered rather than what wells produce — ARC reads 84 bbl/MMcf and Ovintiv 0.1 in Kakwa — so it is not used here. The consequence is that condensate is attributed to where it is recovered, which for a plant drawing across a play boundary is approximate."),
  bullet("Play boxes are rectangles and plays are not, so edges misattribute. The Montney and Deep Basin boundary near Wapiti is genuinely fuzzy, and the Duvernay lies beneath the Deep Basin and cannot be separated geographically at all."),
  bullet("Alberta only. Tourmaline and ARC are understated because both hold material BC Montney."),
  bullet("Regenerate with prepare_well_production.py, prepare_plant_condensate.py, then build_basin_doc.js."),
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
