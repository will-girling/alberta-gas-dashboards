// Build the Canadian play/operator reference as a Word document.
//
// Organised per play, each with its own operator table. Kept as a
// script so the measured tables can be regenerated when Petrinex
// refreshes - those are the parts that go stale.

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
      text: "Interview reference — production data June 2026", size: 21, color: MUTED,
    })],
  }),

  lead("How to use the numbers. ",
    "Operator volumes are measured — Petrinex volumetric data joined to AER ST37, attributed by well licensee. Play assignment is geographic and therefore approximate: wells are binned by bottom-hole location, so a company straddling two plays is split between them. Validated against known footprints (Imperial's Cold Lake figure equals its entire Alberta output, which is correct)."),
  bullet("Alberta only. Tourmaline and ARC are understated — both hold material BC Montney."),
  bullet("Conventional only. Mined oil sands are withheld by Petrinex, so add roughly 1.3 MMbbl/d for Suncor, CNRL and Imperial."),
  bullet("The Deep Basin / Montney boundary is genuinely fuzzy. Wells are assigned to the first play whose box contains them, so the Montney takes the overlap and the Deep Basin figure is correspondingly lower."),
  bullet("BOE is 6 Mcf to 1 barrel — an energy equivalence, not an economic one. At current prices a gas boe is worth a fraction of an oil boe, so never compare a gas-weighted play to an oil one on BOE alone."),
  p("Alberta totals: 13.2 Bcf/d gas · 1.97 MMbbl/d bitumen · 550 Mbbl/d conventional crude · roughly 4.5 MMboe/d across all plays.", { after: 180, muted: true }),

  h1("Gas plays"),

  h2("Montney — Alberta side"),
  p("Grande Prairie, Kakwa, Wapiti, Pipestone. Liquids-rich: the condensate is worth more than the gas, and it is the condensate that makes these wells work. It prices as C5+ at Edmonton — pentanes plus, quoted against WTI — which is a different stream from Edmonton Light Sweet, the light crude benchmark. C5+ often trades at or above WTI because it is the diluent blended into bitumen, so Montney condensate economics depend on oil sands growth. The BC side — Groundbirch, Dawson Creek, Fort St John — is drier and not captured here."),
  sizeLine("950,438 boe/d  —  4,678 MMcf/d gas · 52,930 b/d condensate · 117,850 b/d oil  ·  82% gas"),
  opTable([
    ["Ovintiv", "963"], ["Canadian Natural", "841"], ["Tourmaline", "611"],
    ["ARC Resources", "550"], ["Whitecap", "395"], ["Birchcliff", "361"],
  ], "MMcf/d"),
  p("Also NuVista (Wapiti/Pipestone), Kelt and Paramount. On the BC side, Petronas and Shell tied to LNG Canada.", { muted: true }),

  h2("Deep Basin — Wapiti to Edson"),
  p("West-central Alberta tight gas. Spirit River, Wilrich and Falher are geological formations stacked vertically, so one surface location can access several targets — that is where the cost advantage comes from. Lower decline and lower cost than the Montney but less liquids. Peyto is the pure play and the standard reference for a low-cost operator."),
  sizeLine("502,205 boe/d  —  2,827 MMcf/d gas · 9,977 b/d condensate · 21,032 b/d oil  ·  94% gas"),
  opTable([
    ["Tourmaline", "697"], ["Peyto", "539"], ["Canadian Natural", "459"],
    ["Whitecap", "261"], ["Cenovus", "154"], ["Vermilion", "147"],
  ], "MMcf/d"),
  p("The Duvernay — Kaybob, Fox Creek, Willesden Green — sits beneath this same area and cannot be separated geographically. Chevron, Ovintiv and CNRL are the Duvernay names.", { muted: true }),

  h2("Cardium and central foothills"),
  p("Pembina and Willesden Green. Mature, heavily drilled light oil with associated gas. The box also picks up shallower gas, so treat the gas figure as the area rather than the Cardium formation."),
  sizeLine("318,603 boe/d  —  1,539 MMcf/d gas · 60,601 b/d oil · 1,465 b/d condensate  ·  81% gas"),
  opTable([
    ["TAQA North", "224"], ["Spartan Delta", "186"], ["Tourmaline", "154"],
    ["Vermilion", "142"], ["Peyto", "103"], ["Cenovus", "85"],
  ], "MMcf/d"),
  p("On the oil side: Whitecap, Obsidian, InPlay, Cardinal, Aspenleaf, Yangarra.", { muted: true }),

  h2("Mannville CBM and shallow gas — central Alberta"),
  p("Very low rate per well, enormous well count, minimal decline. This is the long tail in the data: 84% of Alberta wells produce under 0.1 MMcf/d. Ember is the pure play and takes 0% of its production from new wells — pure harvest mode, no drilling."),
  sizeLine("235,506 boe/d  —  957 MMcf/d gas · 73,240 b/d oil  ·  68% gas"),
  opTable([
    ["Ember Resources", "182"], ["Whitecap", "146"], ["Canadian Natural", "136"],
    ["Lynx Energy", "72"], ["Pine Cliff", "51"], ["Tourmaline", "36"],
  ], "MMcf/d"),

  h2("Southeast Alberta shallow gas"),
  p("Medicine Hat and the Lloydminster corridor. Shallow, old, declining, and the reason Alberta has so many low-rate wells."),
  sizeLine("112,682 boe/d  —  372 MMcf/d gas · 50,628 b/d oil  ·  55% gas"),
  opTable([
    ["Canadian Natural", "135"], ["IPC Canada", "91"], ["Canlin Energy", "37"],
    ["Rockpoint Gas Storage", "26"], ["Pine Cliff", "20"], ["City of Medicine Hat", "9"],
  ], "MMcf/d"),

  h1("Oil plays"),

  h2("Athabasca in-situ — Christina Lake, Foster Creek, Firebag, Surmont"),
  p("SAGD thermal — paired horizontal wells, steam injected above, heated bitumen drains into the producer below. The largest single pool of production in the country and the core of the Canadian large-cap story. Low decline and long life, but capital never stops: new well pairs are drilled continuously to keep the central plant full. Growth arrives in lumps as plants are expanded, which is why thermal names guide to named projects rather than a rig count."),
  sizeLine("1,230,554 boe/d  —  1,190,664 b/d bitumen · 239 MMcf/d gas  ·  3% gas"),
  opTable([
    ["Cenovus", "439,294"], ["Suncor", "275,728"], ["Canadian Natural", "179,548"],
    ["ConocoPhillips", "135,914"], ["CNOOC", "69,220"], ["Athabasca Oil", "32,250"],
  ], "b/d"),
  p("Cenovus's position reflects the MEG acquisition, which closed 13 November 2025 and consolidated Christina Lake. MEG delisted the next day — do not name it as a comp.", { muted: true }),

  h2("Cold Lake"),
  p("Cyclic steam (CSS, or \"huff and puff\" — one well alternately injects steam then produces, rather than the two-well SAGD arrangement) alongside SAGD. Imperial's Cold Lake operation is its entire Alberta production, which is a useful check that the geographic attribution is sound."),
  sizeLine("639,561 boe/d  —  605,548 b/d bitumen · 204 MMcf/d gas  ·  5% gas"),
  opTable([
    ["Cenovus", "185,958"], ["Canadian Natural", "166,345"], ["Imperial Oil", "160,371"],
    ["Strathcona", "65,063"], ["Caltex Trilogy", "12,770"], ["Baytex", "7,277"],
  ], "b/d"),

  h2("Clearwater — Marten Hills, Peavine, Nipisi"),
  p("Shallow, cheap heavy oil produced from multilateral wells — several horizontal legs drilled from a single wellbore, which spreads the cost of one surface location across much more reservoir contact. The highest capital efficiency in Canadian conventional and the most interesting play of the last five years. Almost no associated gas, and no steam, which is what separates it from the thermal plays."),
  sizeLine("212,131 boe/d  —  192,486 b/d oil · 118 MMcf/d gas  ·  9% gas"),
  opTable([
    ["Spur Petroleum", "60,665"], ["Canadian Natural", "44,544"],
    ["Tamarack Valley", "43,462"], ["Headwater Exploration", "23,123"],
    ["Cardinal Energy", "4,179"], ["Clear North Energy", "3,048"],
  ], "b/d"),

  h2("Peace River oil sands"),
  p("Heavy oil in the northwest. Smaller than Athabasca or Cold Lake, and the play most associated with Baytex."),
  sizeLine("52,658 boe/d  —  41,668 b/d oil · 66 MMcf/d gas  ·  21% gas"),
  opTable([
    ["Baytex", "17,046"], ["Obsidian Energy", "9,915"],
    ["Canadian Natural Upgrading", "9,699"], ["Spur Petroleum", "1,789"],
    ["Surge Energy", "1,220"],
  ], "b/d"),

  h1("Not in the data"),
  bullet("Oil sands mining — Athabasca, north of Fort McMurray. Suncor (Base Plant, Fort Hills), CNRL (Horizon, AOSP), Imperial (Kearl), Syncrude. Roughly 1.3 MMbbl/d, withheld by Petrinex."),
  bullet("BC Montney — Groundbirch, Dawson Creek, Fort St John. Tourmaline, ARC, Ovintiv, Petronas, Shell. Needs BCER production data."),
  bullet("Saskatchewan — Bakken and Torquay around Estevan, Viking in the southwest, and Strathcona's Lloydminster Thermal. Whitecap is the main public Bakken name after the Veren acquisition. Needs the Petrinex SK pull."),
  bullet("Offshore Newfoundland — Hibernia, Terra Nova, Hebron, White Rose. Suncor, Cenovus, ExxonMobil."),

  h1("Infrastructure — the marketing half of the question"),
  lead("Gas. ", "NGTL gathers essentially all Alberta supply and hands off at Empress (east, to the TC Mainline and Saskatchewan) and the Alberta/BC border (west, via Foothills to Kingsgate). Alliance moves liquids-rich gas direct to Chicago. Westcoast T-South carries northeast BC gas to Huntingdon/Sumas. AECO is the Alberta hub; Station 2 is northeast BC."),
  p("LNG Canada at Kitimat, fed by Coastal GasLink, is the structural change — the first material new demand for WCSB gas in decades. Cedar LNG and Woodfibre follow."),
  lead("Oil. ", "Enbridge Mainline to the US Midwest, Keystone to Cushing and the Gulf, TMX to Burnaby — the last of which changed the WCS differential. Heavy prices off WCS at Hardisty, light off Edmonton Par."),

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
