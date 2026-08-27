// Build the US basin / marketing reference as a Word document.
//
// Companion to build_basin_doc.js and deliberately sharing its helpers
// and styling, so the two references read as one set.
//
// A note on the numbers. The Canadian document's operator tables are
// measured - Petrinex volumetrics joined to AER ST37, computed locally.
// Nothing equivalent exists here. US production data at that granularity
// sits behind Enverus, S&P and state-by-state regulators (Texas RRC,
// Pennsylvania DEP, Louisiana DNR, North Dakota DMR), each with its own
// format and lag. So these figures are sourced from EIA STEO, company
// guidance and trade press, and are cited rather than computed.
//
// That distinction is worth keeping straight in an interview: one
// document is your own work, the other is a literature review.

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
      text: "US Basins and Gas Marketing", bold: true, size: 38, color: ACCENT,
    })],
  }),
  new Paragraph({
    spacing: { after: 200 },
    border: { bottom: RULE },
    children: [new TextRun({
      text: "Interview reference — EIA STEO and company guidance, August 2026",
      size: 21, color: MUTED,
    })],
  }),

  lead("How to use the numbers. ",
    "Unlike the Canadian reference, none of this is computed from raw data. US well-level production is fragmented across state regulators and the clean aggregations sit behind Enverus and S&P. These figures come from EIA STEO, company guidance and trade press. Say so if asked — knowing the provenance of your numbers is the point."),
  bullet("Production figures are DAILY RATES and are 2026 annual-average forecast or latest actual, not a single consistent vintage."),
  bullet("US gas figures here are MARKETABLE gas — EIA's basis, after fuel, flare and processing shrinkage. The Canadian companion document reports GROSS WELLHEAD volumes from Petrinex, which run roughly 10-15% higher for the same production. Appalachia at 37.0 Bcf/d and Alberta Montney at 4,678 MMcf/d are therefore not directly comparable; convert to one basis before quoting a ratio."),
  bullet("The Canadian document is a single month (June 2026, a seasonal trough); these are annual averages. That is a second reason not to compare levels across the two."),
  bullet("Basin boundaries differ between EIA, state regulators and commercial vendors. Permian gas in particular varies by several Bcf/d depending on definition."),
  bullet("Operator rankings shift with M&A faster than any published table. Verify before quoting in an interview."),
  p("US marketed gas: 122.5 Bcf/d forecast for 2026, against 118.5 Bcf/d in 2025 — both records. Crude roughly 13.5 MMbbl/d. For scale, the whole WCSB is about 18 Bcf/d, so Appalachia alone is twice Alberta.", { after: 180, muted: true }),

  h1("Why US gas is a different business from Canadian gas"),
  lead("Three structural differences ", "explain most of what follows, and they are worth stating before any basin detail."),
  bullet("Demand. Canada exports gas to one customer. The US has 19 Bcf/d of LNG export capacity, a power sector that switched from coal, a large petrochemical complex, and now data centres. Price is set by competition between those, not by a single export path."),
  bullet("Associated gas. Roughly a quarter of US gas is a by-product of oil drilling and is produced regardless of gas price. Alberta has almost none of this. It is why Waha can go negative while Henry Hub is healthy."),
  bullet("Market structure. Henry Hub is a globally traded benchmark with deep futures liquidity. AECO is a regional hub with thin paper. That changes how producers hedge and how basis behaves."),

  h1("Gas basins"),

  h2("Appalachia — Marcellus and Utica"),
  p("Pennsylvania, West Virginia, Ohio. The largest gas region in North America and roughly twice the size of the entire WCSB. Dry gas in the northeast Marcellus, wet and liquids-rich in the southwest and in the Utica condensate window. Very low breakevens on the rock itself — the problem here has never been geology, it is pipe."),
  sizeLine("37.0 Bcf/d forecast 2026  —  the largest producing region in the US"),
  opTable([
    ["EQT", "~6.9 Bcfe/d company-wide"],
    ["Expand Energy", "~7.3 Bcfe/d company-wide"],
    ["Antero Resources", "liquids-rich, Utica/Marcellus"],
    ["Range Resources", "wet Marcellus, NGL-weighted"],
    ["CNX Resources", "Appalachia pure play"],
    ["Coterra", "Marcellus + Permian + Anadarko"],
  ], "note"),
  lead("The marketing problem. ", "Appalachia is landlocked and pipeline-constrained by politics rather than economics. Constitution and Atlantic Coast were both cancelled; Mountain Valley took years and litigation to finish. So the basin produces gas cheaply and cannot always move it, which is why Appalachian basis has historically been the widest negative basis in North America — Dominion South and Tetco M2 routinely trade well under Henry Hub."),
  p("The consequence for equities: an Appalachian producer's realised price is a transport story, not a resource story. EQT's vertical integration into gathering, and the firm transport portfolios these companies carry, matter more to realisations than well quality does. Always ask what a producer's basis differential and FT commitments look like before comparing netbacks.", { muted: true }),

  h2("Haynesville — East Texas and North Louisiana"),
  p("Deep, hot, high-pressure dry gas. Wells are expensive and decline hard, but deliverability per well is enormous. The defining feature is location: it sits a few hundred miles from the Gulf Coast LNG terminals, which makes it the swing supply for export demand."),
  sizeLine("16.3 Bcf/d forecast 2026  —  up 9% (1.3 Bcf/d) year on year"),
  opTable([
    ["Expand Energy", "largest US gas producer"],
    ["Aethon Energy", "private, large Haynesville position"],
    ["Comstock Resources", "Haynesville pure play"],
    ["Chesapeake legacy assets", "now Expand"],
    ["Rockcliff / TG Natural Resources", "private"],
    ["Vine legacy assets", "now Chesapeake/Expand"],
  ], "note"),
  lead("Why it matters more than its size suggests. ", "The Haynesville is the marginal barrel of US gas supply. High cost means it responds fast to price — rigs come off at $3 Henry Hub and come back at $4. Proximity to Sabine Pass, Plaquemines and Golden Pass means it is the natural feedstock for LNG. So Haynesville rig count is the single best leading indicator of whether US gas supply is about to grow, and it is the number gas marketers watch."),

  h2("Permian — associated gas"),
  p("The Permian is an oil basin that happens to be the second-largest gas producer in the country. Nobody drills a Permian well for the gas. That single fact drives everything about how Permian gas behaves."),
  sizeLine("29.2 Bcf/d gas forecast 2026, up 6%  ·  ~6.5 MMbbl/d oil"),
  lead("Waha and negative prices. ", "Because the gas is a by-product of oil economics, supply does not respond to gas price at all. When takeaway capacity fills, producers will pay to dispose of gas rather than curtail oil. Waha traded negative for 158 days in the first five months of 2026, and for a record 12 consecutive days in February."),
  p("This is the cleanest example in North America of why basis and flat price are separate risks. A Permian producer can be highly profitable while receiving negative prices for a third of its production stream.", { muted: true }),
  lead("The egress build-out. ", "Roughly 4.5 to 5.3 Bcf/d of new takeaway is arriving through late 2026: Matterhorn (2.5 Bcf/d, in service), Blackcomb (2.5 Bcf/d, Whitewater, moving early volumes), Hugh Brinson (Energy Transfer, flowing ahead of schedule) and a Kinder Morgan GCX expansion that filled immediately on start-up. Most of it lands at Agua Dulce in South Texas, positioning the gas for LNG and Mexico export rather than for Midwest markets."),
  p("The pattern to recognise: Permian egress relief is temporary. Each pipeline fills within months because oil-driven associated gas growth resumes. Waha basis blows out, capacity is built, basis recovers, production grows into it, and the cycle repeats. Being early to the next constraint is where the money is.", { muted: true }),

  h2("Anadarko — SCOOP and STACK, Oklahoma"),
  p("Mid-continent, mixed gas and liquids, stacked pay. A first-mover shale play that fell out of favour as capital concentrated in the Permian and Appalachia. Now largely a cash-harvest basin rather than a growth story."),
  sizeLine("roughly 6.5 Bcf/d gas · ~380 Mbbl/d oil"),
  opTable([
    ["Continental Resources", "private since 2022"],
    ["Devon Energy", "diversified, Permian-weighted"],
    ["Coterra Energy", "Anadarko + Permian + Marcellus"],
    ["Ovintiv", "also large in Montney — the Canadian link"],
    ["Expand Energy", "legacy Chesapeake position"],
    ["Marathon legacy assets", "now ConocoPhillips"],
  ], "note"),
  p("Worth knowing for one reason: Ovintiv and Coterra both straddle Anadarko and Canadian or Appalachian assets, so they are the natural comparables when someone asks you to compare a Canadian producer to a US one.", { muted: true }),

  h1("Oil basins"),

  h2("Permian — Midland and Delaware"),
  p("The largest oil basin in the US by a wide margin and the centre of gravity for North American upstream capital. Two sub-basins: Midland to the east, Delaware to the west, the Delaware being deeper, gassier and more liquids-rich. Stacked pay across Wolfcamp, Bone Spring and Spraberry benches means one surface location accesses many targets."),
  sizeLine("~6.5 MMbbl/d oil  —  roughly half of US crude production"),
  opTable([
    ["ExxonMobil", "largest, post-Pioneer"],
    ["Occidental", "second largest, post-CrownRock"],
    ["Chevron", "large Delaware position"],
    ["Diamondback", "largest pure-play independent"],
    ["ConocoPhillips", "post-Marathon"],
    ["Coterra, Devon, Permian Resources", "mid-cap independents"],
  ], "note"),
  lead("2026 growth guidance. ", "East Daley's survey of 14 public operators points to 183,000 b/d of growth, about 2.7%. ExxonMobil alone accounts for roughly 44% of that — 108,000 b/d, or 11% growth. Occidental guides 3.6%, Diamondback raised to 4.5% (27,000 b/d), Chevron about 2%."),
  p("The structural story: consolidation has moved the Permian from a fragmented, price-responsive shale patch to something closer to an oligopoly of majors running it for free cash flow. That is why the basin no longer grows 1 MMbbl/d a year, and why US supply is less price-elastic than it was in 2018.", { muted: true }),

  h2("Eagle Ford — South Texas"),
  p("Mature, well understood, and the most geographically advantaged play in the US: it sits on top of the Gulf Coast refining and export complex. Three windows — oil in the north, condensate in the middle, dry gas in the south — so operators can steer capital toward whichever product is priced best."),
  sizeLine("~1.1 MMbbl/d oil · ~7.3 Bcf/d gas"),
  opTable([
    ["ConocoPhillips", "large position"],
    ["EOG Resources", "the original Eagle Ford mover"],
    ["Devon Energy", "post-Validus"],
    ["Marathon legacy assets", "now ConocoPhillips"],
    ["SilverBow / Crescent Energy", "consolidated mid-caps"],
    ["Chesapeake legacy assets", "divested to INEOS"],
  ], "note"),
  p("Marketing advantage: minimal transport cost to Corpus Christi and Houston, so Eagle Ford crude prices close to LLS and Brent-linked export markets rather than at a Cushing discount. This is the mirror image of the Appalachian problem.", { muted: true }),

  h2("Bakken — North Dakota and Montana"),
  p("The play that started the shale oil era. Light sweet crude, geographically isolated, and constrained by both takeaway and cold. Production has been roughly flat for years — a mature plateau rather than a decline."),
  sizeLine("~1.3 MMbbl/d oil · ~3.5 Bcf/d gas"),
  opTable([
    ["Continental Resources", "private, largest position"],
    ["ConocoPhillips", "post-Marathon"],
    ["Hess", "now part of Chevron"],
    ["Chord Energy", "Whiting + Oasis merger"],
    ["Devon Energy", "smaller position"],
    ["Enerplus legacy assets", "acquired by Chord — the Canadian link"],
  ], "note"),
  lead("Two marketing quirks. ", "First, Bakken crude moves substantially by rail as well as pipe (Dakota Access), so its differential includes a rail-economics floor. Second, gas capture regulation binds: North Dakota limits flaring, so gas processing capacity can constrain oil drilling. That is an unusual case of the by-product controlling the main product."),

  h2("DJ Basin / Niobrara — Colorado"),
  p("Front Range Colorado. Good rock, but the defining feature is regulatory: Colorado has the most restrictive permitting and setback regime of any major US producing state, which caps growth independent of price."),
  sizeLine("~700 Mbbl/d oil · ~5.3 Bcf/d gas"),
  opTable([
    ["Chevron", "post-PDC Energy"],
    ["Civitas Resources", "DJ + Permian"],
    ["Occidental", "legacy Anadarko Petroleum position"],
    ["Prairie Operating", "small-cap"],
  ], "note"),
  p("Useful as the counterexample to the usual story: in the DJ, permitting is the binding constraint rather than geology, price or pipe. Regulatory risk is a real input to a supply forecast, not a footnote.", { muted: true }),

  h2("Gulf of Mexico and other"),
  bullet("Gulf of Mexico — roughly 1.8 MMbbl/d, long-cycle deepwater. Shell, BP, Chevron, Oxy, Equinor. Long lead times, high capital, very low decline once producing. The opposite temperament to shale, and a useful contrast: it is to shale what SAGD is to Clearwater."),
  bullet("Uinta (Utah) — waxy crude that must be kept heated to flow, so it prices at a discount and moves by rail. A niche but a good test of whether someone understands crude quality."),
  bullet("Alaska North Slope — ConocoPhillips Willow. Declining legacy field, isolated market, ANS crude priced off Brent."),

  h1("Gas marketing"),
  p("The mechanics below are the part most candidates cannot describe, and the part a commercial research role cares about most."),

  h2("From wellhead to market"),
  lead("1. Gathering. ", "Small-diameter, low-pressure lines from the wellhead to a processing plant, usually owned by a midstream company rather than the producer. Contracts are typically fee-based per Mcf, sometimes with acreage dedication — the producer commits all production from defined acreage for a term. Dedications are why a producer cannot always switch midstream provider even if a better rate exists."),
  lead("2. Processing. ", "Removes water, CO2, hydrogen sulphide and NGLs to leave pipeline-quality dry methane. This is where the producer's liquids revenue is determined, and the contract type decides who captures it: fee-based (midstream takes a fixed fee, producer keeps liquids upside), percent-of-proceeds (they share), or keep-whole (midstream keeps the NGLs and returns equivalent gas). Which structure a producer signed is a real swing factor in NGL-price sensitivity."),
  lead("3. Transport. ", "Interstate pipelines are FERC-regulated, open-access common carriers — unlike Canada, where NGTL is a single integrated system. Capacity is contracted as firm transport (FT: reserved, paid whether used or not, tradeable on a secondary capacity release market) or interruptible (IT: cheaper, first to be cut). A producer's FT portfolio is effectively a portfolio of basis options, and sophisticated producers trade it."),
  lead("4. Sale. ", "Gas is sold at a hub or a pooling point, priced as Henry Hub futures plus or minus a basis differential. Physical sales are typically indexed to a monthly bidweek index (Platts Gas Daily, NGI) rather than negotiated outright."),

  h2("Hubs and basis"),
  opTable([
    ["Henry Hub, Louisiana", "the benchmark; NYMEX delivery point"],
    ["Waha, West Texas", "Permian; frequently negative in 2026"],
    ["Dominion South / Tetco M2", "Appalachia; structurally discounted"],
    ["Agua Dulce, South Texas", "LNG and Mexico export gateway"],
    ["Chicago citygate", "Midwest demand; where Canadian gas lands"],
    ["SoCal Border / PG&E citygate", "West Coast; GTN and Kingsgate path"],
  ], "role"),
  p("Basis is the difference between a local hub and Henry Hub, and it is the price of transport plus the price of scarcity. When a basin is short of pipe, basis blows out; when new pipe arrives, it collapses. Forecasting basis is largely forecasting pipeline utilisation, which is why this is a research job rather than a macro job.", { muted: true }),

  h2("LNG — the demand driver"),
  sizeLine("~17 Bcf/d capacity end-2025  →  >19 Bcf/d in 2026  ·  feedgas peaks above 20 Bcf/d"),
  bullet("Sabine Pass (Cheniere) — 3.6 Bcf/d nominal. The first US export terminal, ten years old in 2026."),
  bullet("Plaquemines (Venture Global) — 2.6 Bcf/d nominal, authorised to 3.85, pulling about 4 Bcf/d of feedgas."),
  bullet("Corpus Christi Stage 3 (Cheniere) — seven midscale trains at 210 MMcf/d each; Train 5 in commercial operation, 6 commissioning, 7 expected in the autumn."),
  bullet("Golden Pass (ExxonMobil/QatarEnergy) — 2.0 Bcf/d nominal across three trains; first cargo shipped, Train 2 in H2 2026, Train 3 in H1 2027."),
  lead("Contract structures worth knowing. ", "US LNG is mostly sold under two models. Tolling: the customer supplies its own gas and pays a fixed liquefaction fee, taking all commodity risk — Venture Global and Cheniere both use variants. SPA at Henry Hub plus a multiple: typically 115% of Henry Hub plus a fixed liquefaction charge, free-on-board, so the buyer takes destination risk. Both are Henry Hub linked, which is why US LNG is priced fundamentally differently from oil-indexed Qatari or JKM-linked cargoes."),
  p("This is the direct link to your Canadian work. LNG Canada is fed by Coastal GasLink at AECO-linked economics, while Cedar LNG has JKM exposure. A producer with JKM-linked offtake is selling into a different price world from one selling at Henry Hub plus 15%, and that difference is the whole argument about who captures Canadian LNG value.", { muted: true }),

  h2("Midstream — who owns the pipes"),
  opTable([
    ["Energy Transfer", "Permian, Hugh Brinson, huge NGL system"],
    ["Kinder Morgan", "GCX, Permian Highway, largest US gas network"],
    ["Williams", "Transco — the eastern demand artery"],
    ["Whitewater Midstream", "Matterhorn, Blackcomb"],
    ["Targa Resources", "Permian G&P and NGL fractionation"],
    ["EnLink, DT Midstream, Enbridge (US)", "regional systems"],
  ], "note"),
  p("Midstream is where a lot of the basis value is captured. When Waha is deeply negative, the pipeline owner moving gas to Agua Dulce is earning the spread. Watching who holds capacity into a constrained market often tells you more than watching the producers.", { muted: true }),

  h1("Oil marketing"),
  p("Crude is a physically differentiated product in a way gas is not. A molecule of methane is a molecule of methane; a barrel of crude has a density, a sulphur content and a location, and all three are priced separately. That is the whole of crude marketing."),

  h2("The three things that price a barrel"),
  lead("1. Quality. ", "Density (API gravity) and sulphur. Light sweet crude yields more gasoline and diesel with less processing, so it commands a premium. Heavy sour needs a coker and a hydrotreater, so it trades at a discount — and that discount is really the market price of refinery complexity."),
  lead("2. Location. ", "A barrel at Cushing, Oklahoma and the identical barrel at Houston are different prices, separated by pipeline tariff. Landlocked barrels price at a discount to waterborne ones because they can only reach the customers a pipe can reach."),
  lead("3. Timing. ", "Contango (forward above spot) pays you to store; backwardation (forward below spot) pays you to sell now. Storage economics at Cushing are a real trade, not an abstraction."),

  h2("US crude benchmarks"),
  opTable([
    ["WTI, Cushing OK", "NYMEX delivery point; ~40 API light sweet"],
    ["WTI Midland", "wellhead Permian; now in the Dated Brent basket"],
    ["MEH (Magellan East Houston)", "waterborne, export-linked"],
    ["LLS (Light Louisiana Sweet)", "Gulf Coast light sweet"],
    ["Mars", "Gulf of Mexico medium sour"],
    ["Brent", "global waterborne benchmark"],
  ], "what it is"),
  lead("The Midland-in-Brent change matters. ", "Since 2023 WTI Midland has been one of the grades that can set Dated Brent. A US shale barrel now helps price the global benchmark, which is a genuine structural shift — it links Permian production economics directly to Brent rather than leaving WTI as a purely domestic marker. The Brent-WTI spread peaked at $25/bbl on 31 March 2026 and averaged $11/bbl that month; that spread is the arbitrage that pulls US barrels overseas."),

  h2("Where the barrels go"),
  lead("Exports. ", "The US export ban was lifted in 2015 and exports are now a structural feature, running around 4 MMbbl/d. Corpus Christi handles more than half of all US crude exports at 2.3 to 2.4 MMbbl/d, 99% of it to foreign markets, making it the world's third-largest crude export port and the top US LNG export point as well."),
  p("This is why Permian crude economics are Brent economics. A Midland barrel moves on Gray Oak, Cactus II or EPIC to Corpus, loads onto a VLCC, and competes in Rotterdam or Asia. Cushing is increasingly a pricing convention rather than the physical destination.", { muted: true }),
  lead("Refining. ", "The US is divided into five PADDs. PADD 3, the Gulf Coast, holds roughly half of national refining capacity and is the most complex refining complex in the world — built with cokers to run heavy sour Venezuelan, Mexican and Canadian crude. That configuration is why Gulf Coast refiners are the natural buyers for WCS, and why the WCS differential is partly a story about coking capacity rather than about Canada."),
  p("The mismatch worth naming: US shale produces light sweet crude, while US refineries were built for heavy sour. So the country exports light barrels and imports heavy ones simultaneously. That is not irrational — it is two different products meeting two different plants.", { muted: true }),

  h2("Crude pipelines to know"),
  opTable([
    ["Gray Oak, Cactus II, EPIC", "Permian to Corpus Christi"],
    ["Wink to Webster, Midland-to-ECHO", "Permian to Houston"],
    ["Basin, Centurion", "Permian to Cushing"],
    ["Dakota Access", "Bakken to Patoka and the Gulf"],
    ["Seaway, Marketlink", "Cushing to the Gulf Coast"],
    ["Capline (reversed)", "now northern crude southbound"],
  ], "route"),

  h1("NGL marketing — the part everyone skips"),
  p("Natural gas liquids are ethane, propane, butane, isobutane and pentanes plus. They arrive as a mixed stream from a gas processing plant, get shipped to a fractionator, and are separated into purity products with completely separate markets."),
  opTable([
    ["Mont Belvieu, Texas", "the NGL hub; storage, fractionation, export"],
    ["Conway, Kansas", "mid-continent hub, usually at a discount"],
    ["Ethane", "petrochemical cracker feed only"],
    ["Propane", "heating, exports, petchem"],
    ["Butane / isobutane", "gasoline blending, alkylation"],
    ["Pentanes plus (C5+)", "diluent, gasoline blendstock"],
  ], "role"),
  lead("Ethane rejection. ", "Ethane can either be extracted and sold as a liquid, or left in the gas stream and sold as methane on a heating-value basis. Processors choose whichever is worth more. When ethane prices are weak relative to gas, they reject it — which raises gas volumes and cuts NGL volumes without any change in drilling. It is a large swing factor and a common source of confusion in supply data."),
  lead("The frac spread. ", "The margin between the value of NGLs as liquids and the value of the same molecules as gas. It drives processing economics, and it is the number that determines whether a percent-of-proceeds contract is a good deal for the producer that year."),
  p("The Canadian link: US C5+ from Mont Belvieu and the mid-continent moves north on Cochin and Southern Lights as oil sands diluent. Your diluent work sits at the far end of this system.", { muted: true }),

  h1("Canada versus the US — the comparison to have ready"),
  opTable([
    ["Benchmark", "Henry Hub vs AECO"],
    ["Demand driver", "LNG, power, petchem, data centres vs one LNG project"],
    ["Associated gas", "~25% of supply vs almost none"],
    ["Pipeline model", "FERC open-access, contracted FT vs NGTL integrated toll"],
    ["Marginal supply", "Haynesville rig count vs Montney economics"],
    ["Basis risk", "Waha, Dom South vs AECO-Henry, Station 2"],
    ["Crude benchmark", "WTI Cushing and Brent-linked Midland vs WCS Hardisty"],
    ["Crude quality", "light sweet shale vs heavy sour bitumen blend"],
    ["Egress model", "many competing pipes vs apportionment on a few"],
    ["Refining fit", "Gulf Coast cokers want heavy; Canada supplies it"],
  ], "contrast"),
  p("If you are asked why AECO trades where it does, the honest answer runs through this table: one export path, no associated-gas cushion, an integrated toll rather than a capacity market, and a demand base that is only now diversifying. Every one of those is different in the US.", { muted: true }),
  p("And the crude symmetry is worth stating as a single thought: the US produces light sweet crude it does not need and operates refineries built for heavy sour it does not produce. Canada produces heavy sour and has almost no complex refining. The two systems are complements, which is why roughly 4 MMbbl/d of Canadian crude flows south and why WCS is priced against Gulf Coast coking margins rather than against Canadian demand.", { muted: true }),

  h1("Sources"),
  bullet("EIA Short-Term Energy Outlook — production by region, replaced the Drilling Productivity Report in June 2024."),
  bullet("EIA Today in Energy — LNG capacity, Permian pipeline capacity."),
  bullet("East Daley Analytics — 2026 Permian operator growth guidance."),
  bullet("Natural Gas Intelligence, Oil & Gas Journal, S&P Global Commodity Insights — pipeline and LNG project status."),
  bullet("Company disclosure — operator production figures. Verify these before quoting; M&A moves them faster than any published table."),
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
