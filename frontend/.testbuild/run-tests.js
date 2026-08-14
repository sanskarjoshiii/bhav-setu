/* Logic tests for the demo data layer. Run: node .testbuild/run-tests.js */

const { CROPS, VEGETABLES, FRUITS } = require("./mock/crops");
const { MANDIS, HOME_MANDIS, DISTRICTS, mandisInDistrict } = require("./mock/mandis");
const { seriesFor, todayPrice } = require("./mock/prices");
const { netInHand, compareMandis, spoilageFraction } = require("./mock/economics");
const { recommend, DEFAULT_LOT } = require("./mock/recommendation");
const { POOLS, poolEconomics } = require("./mock/community");
const { openingMessages, nextReply, resetChat } = require("./mock/chat");
const { SALE_REPORTS, TRANSPARENCY_SCORES } = require("./mock/transparency");
const { ACCURACY } = require("./mock/accuracy");
const { DEMO_ACCOUNTS, findAccount } = require("./credentials");

let pass = 0;
const failures = [];

function check(name, fn) {
  try {
    const problem = fn();
    if (problem) failures.push(`${name}\n      ${problem}`);
    else pass++;
  } catch (e) {
    failures.push(`${name}\n      threw ${e.message}`);
  }
}

// ── data integrity ─────────────────────────────────────────────────────────
check("crops: 16 crops split into vegetables and fruits", () => {
  if (CROPS.length !== 16) return `expected 16 crops, got ${CROPS.length}`;
  if (VEGETABLES.length + FRUITS.length !== CROPS.length) return "categories do not partition";
});

check("crops: every crop has sane economics fields", () => {
  for (const c of CROPS) {
    if (!(c.basePrice > 0)) return `${c.id} basePrice ${c.basePrice}`;
    if (!(c.kC > 0)) return `${c.id} kC ${c.kC}`;
    if (!(c.maxHoldDays >= 1)) return `${c.id} maxHoldDays ${c.maxHoldDays}`;
    if (!c.nameMr || !c.emoji) return `${c.id} missing Marathi name or emoji`;
    if (c.maxHoldDays > c.shelfLifeDays) return `${c.id} holds longer than its shelf life`;
  }
});

check("mandis: 11 mandis, 3 districts, 5 at home", () => {
  if (MANDIS.length !== 11) return `expected 11, got ${MANDIS.length}`;
  if (DISTRICTS.length !== 3) return `expected 3 districts, got ${DISTRICTS.join()}`;
  if (HOME_MANDIS.length !== 5) return `expected 5 home mandis, got ${HOME_MANDIS.length}`;
});

check("mandis: district filter returns only that district", () => {
  for (const d of DISTRICTS) {
    const rows = mandisInDistrict(d);
    if (!rows.length) return `${d} is empty`;
    if (rows.some((m) => m.district !== d)) return `${d} leaked another district`;
  }
});

check("mandis: unique ids and coordinates inside Maharashtra", () => {
  if (new Set(MANDIS.map((m) => m.id)).size !== MANDIS.length) return "duplicate mandi ids";
  for (const m of MANDIS) {
    if (m.lat < 15 || m.lat > 23) return `${m.name} lat ${m.lat}`;
    if (m.lon < 72 || m.lon > 81) return `${m.name} lon ${m.lon}`;
    if (!(m.distanceKm > 0)) return `${m.name} distance ${m.distanceKm}`;
  }
});

// ── price series ───────────────────────────────────────────────────────────
check("prices: 180 history points plus a 15-day forecast", () => {
  const s = seriesFor("Lasalgaon", "onion");
  if (s.length !== 195) return `expected 195 points, got ${s.length}`;
  if (s.filter((p) => p.isForecast).length !== 15) return "forecast length wrong";
});

check("prices: forecast band always ordered p10 <= p50 <= p90", () => {
  for (const crop of CROPS) {
    for (const m of HOME_MANDIS) {
      for (const p of seriesFor(m.name, crop.id).filter((x) => x.isForecast)) {
        if (!(p.p10 <= p.p50 && p.p50 <= p.p90)) {
          return `${crop.id}/${m.name} ${p.date}: ${p.p10}/${p.p50}/${p.p90}`;
        }
      }
    }
  }
});

check("prices: uncertainty widens with horizon", () => {
  const f = seriesFor("Lasalgaon", "onion").filter((p) => p.isForecast);
  const first = f[0].p90 - f[0].p10;
  const last = f[f.length - 1].p90 - f[f.length - 1].p10;
  if (!(last > first * 2)) return `day1 band ${first}, day15 band ${last}`;
});

check("prices: no NaN or non-positive values anywhere", () => {
  for (const crop of CROPS) {
    for (const m of MANDIS) {
      for (const p of seriesFor(m.name, crop.id)) {
        for (const v of [p.modal, p.p10, p.p50, p.p90].filter((x) => x != null)) {
          if (!Number.isFinite(v) || v <= 0) return `${crop.id}/${m.name} ${p.date} -> ${v}`;
        }
      }
    }
  }
});

check("prices: chart last point equals the board price (pages agree)", () => {
  for (const crop of CROPS) {
    for (const m of HOME_MANDIS) {
      const hist = seriesFor(m.name, crop.id).filter((p) => !p.isForecast);
      const last = hist[hist.length - 1].modal;
      const board = todayPrice(crop.id, m.id);
      if (Math.abs(last - board) > 1) return `${crop.id}/${m.name}: chart ${last} vs board ${board}`;
    }
  }
});

// ── economics ──────────────────────────────────────────────────────────────
const base = {
  pricePerQtl: 2000, qtyQtl: 80, daysHeld: 0,
  distanceKm: 12, grade: "B", storage: "shed", cropId: "onion",
};

check("economics: net is always below gross", () => {
  for (const crop of CROPS) {
    for (const qty of [5, 25, 80, 200]) {
      for (const days of [0, 3, 7]) {
        const r = netInHand({ ...base, qtyQtl: qty, daysHeld: days, cropId: crop.id, pricePerQtl: crop.basePrice });
        if (!(r.netPerQtl < r.grossPerQtl)) return `${crop.id} qty=${qty} days=${days}`;
      }
    }
  }
});

check("economics: net falls as distance grows", () => {
  if (!(netInHand({ ...base, distanceKm: 62 }).netPerQtl < netInHand({ ...base, distanceKm: 12 }).netPerQtl))
    return "far mandi was not cheaper to reach";
});

check("economics: net falls as days held grows", () => {
  const d0 = netInHand({ ...base, daysHeld: 0 }).netPerQtl;
  const d7 = netInHand({ ...base, daysHeld: 7 }).netPerQtl;
  const d15 = netInHand({ ...base, daysHeld: 15 }).netPerQtl;
  if (!(d15 < d7 && d7 < d0)) return `${d0} / ${d7} / ${d15}`;
});

check("economics: zero-day hold has zero spoilage", () => {
  for (const crop of CROPS) {
    if (spoilageFraction(0, "shed", crop.id) !== 0) return `${crop.id} spoils on day 0`;
  }
});

check("economics: perishables spoil faster than storables", () => {
  if (!(spoilageFraction(3, "shed", "okra") > spoilageFraction(3, "shed", "potato") * 3))
    return "okra does not spoil materially faster than potato";
});

check("economics: cold store slows spoilage", () => {
  if (!(spoilageFraction(5, "cold_store", "tomato") < spoilageFraction(5, "ambient", "tomato")))
    return "cold store did not help";
});

check("economics: grade A beats B beats C", () => {
  const a = netInHand({ ...base, grade: "A" }).netPerQtl;
  const b = netInHand({ ...base, grade: "B" }).netPerQtl;
  const c = netInHand({ ...base, grade: "C" }).netPerQtl;
  if (!(a > b && b > c)) return `${a} / ${b} / ${c}`;
});

check("economics: breakdown lines reconcile to the net total", () => {
  const r = netInHand({ ...base, daysHeld: 7 });
  const sum = r.lines.reduce((s, l) => s + l.amount, 0);
  if (Math.abs(sum - r.netTotal) > 0.01) return `lines ${sum} vs total ${r.netTotal}`;
});

// ── the demo moment ────────────────────────────────────────────────────────
check("compare: gross and net rankings disagree (the rank flip)", () => {
  const rows = compareMandis(80, 0, "B", "shed", "onion");
  const byGross = [...rows].sort((a, b) => b.grossPerQtl - a.grossPerQtl);
  if (byGross[0].mandi === rows[0].mandi) return `${rows[0].mandi} wins both — callout will not fire`;
});

check("compare: flip survives every quantity and hold period", () => {
  for (const qty of [10, 25, 50, 80, 150]) {
    for (const days of [0, 3, 7, 15]) {
      const rows = compareMandis(qty, days, "B", "shed", "onion");
      const byGross = [...rows].sort((a, b) => b.grossPerQtl - a.grossPerQtl);
      if (byGross[0].mandi === rows[0].mandi) return `no flip at qty=${qty} days=${days}`;
    }
  }
});

check("compare: ranks form a complete 1..5 permutation", () => {
  const rows = compareMandis(80, 0, "B", "shed", "onion");
  const want = JSON.stringify([1, 2, 3, 4, 5]);
  if (JSON.stringify(rows.map((r) => r.rankByGross).sort()) !== want) return "gross ranks broken";
  if (JSON.stringify(rows.map((r) => r.rankByNet).sort()) !== want) return "net ranks broken";
});

check("compare: rows come back sorted by net rank", () => {
  const rows = compareMandis(80, 0, "B", "shed", "onion");
  for (let i = 1; i < rows.length; i++) {
    if (rows[i].netPerQtl > rows[i - 1].netPerQtl) return `row ${i} out of order`;
  }
});

// ── recommendation engine ──────────────────────────────────────────────────
check("advisor: tranche quantities sum to the lot quantity", () => {
  for (const crop of CROPS) {
    for (const qty of [5, 22, 80, 150]) {
      const r = recommend({ ...DEFAULT_LOT, cropId: crop.id, qtyQtl: qty });
      const sum = r.tranches.reduce((s, t) => s + t.qtl, 0);
      if (Math.abs(sum - qty) > 1) return `${crop.id} qty=${qty}: tranches sum ${sum}`;
    }
  }
});

check("advisor: never holds past the crop's max hold days", () => {
  for (const crop of CROPS) {
    const r = recommend({ ...DEFAULT_LOT, cropId: crop.id });
    for (const t of r.tranches) {
      if (t.dayOffset > crop.maxHoldDays) return `${crop.id} max ${crop.maxHoldDays}, advised ${t.dayOffset}`;
    }
  }
});

check("advisor: confidence is a probability and ranges are ordered", () => {
  for (const crop of CROPS) {
    const r = recommend({ ...DEFAULT_LOT, cropId: crop.id });
    if (!(r.confidence >= 0 && r.confidence <= 1)) return `${crop.id} confidence ${r.confidence}`;
    for (const t of r.tranches) {
      if (!(t.rangeLow <= t.netPerQtl && t.netPerQtl <= t.rangeHigh)) return `${crop.id} range broken`;
    }
  }
});

check("advisor: every crop yields a headline and reason in both languages", () => {
  for (const crop of CROPS) {
    const r = recommend({ ...DEFAULT_LOT, cropId: crop.id });
    if (!r.headline || !r.headlineMr) return `${crop.id} missing a headline`;
    if (!r.reasonText || !r.reasonTextMr) return `${crop.id} missing a reason`;
    if (!["sell_now", "hold", "split", "sell_to_procurement"].includes(r.action)) {
      return `${crop.id} bad action ${r.action}`;
    }
  }
});

check("advisor: cautious never holds longer than aggressive", () => {
  for (const crop of CROPS) {
    const c = recommend({ ...DEFAULT_LOT, cropId: crop.id, risk: "cautious" });
    const a = recommend({ ...DEFAULT_LOT, cropId: crop.id, risk: "aggressive" });
    const ch = Math.max(0, ...c.tranches.map((t) => t.dayOffset));
    const ah = Math.max(0, ...a.tranches.map((t) => t.dayOffset));
    if (ch > ah) return `${crop.id}: cautious ${ch}d vs aggressive ${ah}d`;
  }
});

check("advisor: small lots trigger min_viable_load", () => {
  const r = recommend({ ...DEFAULT_LOT, qtyQtl: 8 });
  if (!r.constraintsApplied.includes("min_viable_load")) return `got ${r.constraintsApplied.join()}`;
});

check("advisor: it really searches many alternatives", () => {
  if (!(recommend(DEFAULT_LOT).alternativesConsidered >= 25)) return "too few alternatives scored";
});

// ── anti-vacuity: the engine must actually decide, not always say sell_now ──
check("advisor: the flagship onion case produces a split with a real gain", () => {
  const r = recommend(DEFAULT_LOT);
  if (r.action !== "split") return `onion action is ${r.action}; the demo narrative breaks`;
  if (r.tranches.length !== 2) return `expected 2 tranches, got ${r.tranches.length}`;
  if (!(r.expectedGain > 0)) return `expected gain is ${r.expectedGain}`;
});

check("advisor: decisions genuinely vary across crops", () => {
  const actions = CROPS.map((c) => recommend({ ...DEFAULT_LOT, cropId: c.id }).action);
  const kinds = new Set(actions);
  if (kinds.size < 2) return `every crop returned ${[...kinds][0]}; the engine is not deciding`;
  if (!actions.includes("split")) return "no crop splits; a linear objective can only pick corners";
});

check("advisor: perishables sell now, storables do not all sell now", () => {
  for (const id of ["tomato", "okra", "banana", "mango"]) {
    const a = recommend({ ...DEFAULT_LOT, cropId: id }).action;
    if (a !== "sell_now") return `${id} returned ${a}; perishables must sell today`;
  }
  const storable = ["potato", "garlic", "pomegranate"].map(
    (id) => recommend({ ...DEFAULT_LOT, cropId: id }).action
  );
  if (storable.every((a) => a === "sell_now")) return "no storable crop was ever held";
});

check("advisor: a split really splits (both tranches carry quantity)", () => {
  for (const c of CROPS) {
    const r = recommend({ ...DEFAULT_LOT, cropId: c.id });
    if (r.action !== "split") continue;
    if (r.tranches.length !== 2) return `${c.id} split has ${r.tranches.length} tranches`;
    for (const t of r.tranches) if (!(t.qtl > 0)) return `${c.id} split has an empty tranche`;
  }
});

check("advisor: expected gain is never negative for the chosen plan", () => {
  for (const c of CROPS) {
    for (const risk of ["cautious", "balanced", "aggressive"]) {
      const r = recommend({ ...DEFAULT_LOT, cropId: c.id, risk });
      if (r.expectedGain < -1) return `${c.id}/${risk} gain ${r.expectedGain}`;
    }
  }
});

// ── community pooling ──────────────────────────────────────────────────────
check("community: pooling is strictly cheaper than going alone", () => {
  for (const p of POOLS) {
    const e = poolEconomics(p);
    if (!(e.pooledCostEach < e.soloCost)) return `${p.id} pooled ${e.pooledCostEach} vs solo ${e.soloCost}`;
    if (!(e.savingEach > 0)) return `${p.id} saving ${e.savingEach}`;
  }
});

check("community: saving maths is internally consistent", () => {
  for (const p of POOLS) {
    const e = poolEconomics(p);
    if (Math.abs(e.pooledCostEach - e.soloCost / p.members.length) > 0.01) return `${p.id} split wrong`;
    if (Math.abs(e.savingEach - (e.soloCost - e.pooledCostEach)) > 0.01) return `${p.id} saving wrong`;
  }
});

check("community: capacity never displays above 100%", () => {
  for (const p of POOLS) {
    const e = poolEconomics(p);
    if (e.capacityUsedPct > 100 || e.capacityUsedPct < 0) return `${p.id} ${e.capacityUsedPct}%`;
  }
});

check("community: every member has a dialable phone", () => {
  for (const p of POOLS) {
    for (const m of p.members) {
      if (!/^\+91\d{10}$/.test(m.phone)) return `${p.id}/${m.name} phone ${m.phone}`;
    }
  }
});

check("community: at most one member marked as you", () => {
  for (const p of POOLS) {
    if (p.members.filter((m) => m.isYou).length > 1) return `${p.id} has several 'you'`;
  }
});

// ── chat flow ──────────────────────────────────────────────────────────────
check("chat: opening greets and offers quick replies", () => {
  resetChat();
  const open = openingMessages("en");
  if (!open.length) return "no opening messages";
  if (!open[open.length - 1].buttons?.length) return "no quick-reply buttons";
  if (!/Namaskar/i.test(open[0].text)) return `unexpected greeting: ${open[0].text}`;
});

check("chat: the full 7-step default flow completes", () => {
  resetChat();
  openingMessages("en");
  let sawAdvice = false;
  let sawThanks = false;
  for (const s of ["onion 80 quintal", "Grade B", "Shed", "I sold today", "1840"]) {
    const replies = nextReply(s, "en");
    if (!replies.length) return `no reply to "${s}"`;
    const text = replies.map((r) => r.text).join(" ");
    if (/Sell 50 quintal today/i.test(text)) sawAdvice = true;
    if (/Recorded/i.test(text)) sawThanks = true;
  }
  if (!sawAdvice) return "never produced the advice message";
  if (!sawThanks) return "never acknowledged the sale report";
});

check("chat: POOL works at any point", () => {
  resetChat();
  openingMessages("en");
  const text = nextReply("POOL", "en").map((r) => r.text).join(" ");
  if (!/Truck to Lasalgaon/i.test(text)) return `POOL gave: ${text.slice(0, 80)}`;
});

check("chat: unrecognised input gets help, not a dead end", () => {
  resetChat();
  openingMessages("en");
  const replies = nextReply("qwertyuiop", "en");
  if (!replies.length) return "no reply at all";
  if (!replies[replies.length - 1].buttons?.length) return "fallback offered no buttons";
});

check("chat: Marathi is genuinely different text", () => {
  resetChat();
  const en = openingMessages("en")[0].text;
  resetChat();
  const mr = openingMessages("mr")[0].text;
  if (en === mr) return "Marathi is identical to English";
  if (!/[ऀ-ॿ]/.test(mr)) return `no Devanagari in: ${mr}`;
});

// ── seeded content ─────────────────────────────────────────────────────────
check("credentials: three accounts, findable raw and formatted", () => {
  if (DEMO_ACCOUNTS.length !== 3) return `expected 3, got ${DEMO_ACCOUNTS.length}`;
  for (const a of DEMO_ACCOUNTS) {
    if (!findAccount(a.phone)) return `${a.phone} not found`;
    if (!findAccount(`+91 ${a.phone}`)) return `formatted ${a.phone} not found`;
  }
  if (findAccount("0000000000")) return "unknown number matched an account";
});

check("credentials: the three profiles are genuinely different", () => {
  if (new Set(DEMO_ACCOUNTS.map((a) => a.riskProfile)).size !== 3) return "risk profiles repeat";
});

check("transparency: reports are internally consistent", () => {
  if (SALE_REPORTS.length < 30) return `only ${SALE_REPORTS.length} reports`;
  for (const r of SALE_REPORTS) {
    if (!(r.receivedPerQtl < r.quotedPerQtl)) return `${r.id} received >= quoted`;
    if (!(r.gapPct > 0 && r.gapPct < 40)) return `${r.id} gap ${r.gapPct}%`;
  }
});

check("transparency: scores are 0-10 and sorted best first", () => {
  for (const s of TRANSPARENCY_SCORES) {
    if (s.score < 0 || s.score > 10) return `${s.mandi} score ${s.score}`;
  }
  for (let i = 1; i < TRANSPARENCY_SCORES.length; i++) {
    if (TRANSPARENCY_SCORES[i].score > TRANSPARENCY_SCORES[i - 1].score) return "not sorted";
  }
});

check("accuracy: the model beats every baseline at every horizon", () => {
  for (const row of ACCURACY.mape) {
    if (!(row.model < row.naive)) return `h=${row.horizon}: model ${row.model} vs naive ${row.naive}`;
  }
  for (const row of ACCURACY.pinball) {
    if (!(row.model < row.naive)) return `pinball h=${row.horizon} loses to naive`;
  }
});

check("accuracy: PICP inside the band PLAN.md requires", () => {
  if (!(ACCURACY.picp >= 0.72 && ACCURACY.picp <= 0.88)) return `PICP ${ACCURACY.picp}`;
  if (!(ACCURACY.directionalAccuracy > 0.6)) return `directional ${ACCURACY.directionalAccuracy}`;
});

// ── determinism ────────────────────────────────────────────────────────────
check("determinism: repeat calls are identical (no hydration drift)", () => {
  if (JSON.stringify(seriesFor("Lasalgaon", "onion")) !== JSON.stringify(seriesFor("Lasalgaon", "onion")))
    return "price series changed between calls";
  if (JSON.stringify(recommend(DEFAULT_LOT)) !== JSON.stringify(recommend(DEFAULT_LOT)))
    return "recommendation changed between calls";
});

console.log("");
if (failures.length === 0) {
  console.log(`  ✅ all ${pass} logic checks passed`);
} else {
  console.log(`  ${pass} passed, ${failures.length} FAILED\n`);
  failures.forEach((f, i) => console.log(`  ${i + 1}. ${f}\n`));
}
process.exit(failures.length ? 1 : 0);
