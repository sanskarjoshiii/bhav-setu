"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.ALL_CROP_IDS = void 0;
exports.todayPrice = todayPrice;
exports.todayChangePct = todayChangePct;
exports.todayArrivals = todayArrivals;
exports.seriesFor = seriesFor;
exports.latestModal = latestModal;
exports.miniSeries = miniSeries;
const mandis_1 = require("./mandis");
const crops_1 = require("./crops");
const seed_1 = require("../seed");
/**
 * Price series that behave like real produce: a seasonal swing, a post-harvest
 * slump, one policy shock that knocks ~18% off over four days, and daily noise.
 * Every series is generated from a fixed seed, so nothing moves between renders
 * and the server and client always agree.
 */
const HISTORY_DAYS = 180;
const FORECAST_DAYS = 15;
/** Each mandi trades a little above or below the belt reference. */
function mandiFactor(mandiId) {
    const rand = (0, seed_1.mulberry32)(mandiId * 3301 + 17);
    return 0.94 + rand() * 0.12;
}
function buildSeries(seedBase, level, volatility) {
    const rand = (0, seed_1.mulberry32)(seedBase);
    const out = [];
    let price = level * 0.82;
    for (let i = 0; i < HISTORY_DAYS; i++) {
        const t = i / HISTORY_DAYS;
        const seasonal = Math.sin((i / 365) * Math.PI * 2 - 1.1) * 0.09;
        const drift = 0.22 * t;
        const shock = i > HISTORY_DAYS - 78 && i < HISTORY_DAYS - 60
            ? -0.18 * Math.min(1, (i - (HISTORY_DAYS - 78)) / 4)
            : 0;
        const recovery = i >= HISTORY_DAYS - 60 ? 0.11 * Math.min(1, (i - (HISTORY_DAYS - 60)) / 25) : 0;
        const noise = (0, seed_1.gaussian)(rand) * volatility;
        const target = level * (0.82 + seasonal + drift + shock + recovery);
        price = price * 0.86 + target * 0.14 + price * noise;
        out.push(Math.max(level * 0.25, price));
    }
    return out;
}
const CACHE = new Map();
/** Perishable produce swings harder — volatility scales with perishability. */
function seriesRaw(cropId, mandiId) {
    const key = `${cropId}:${mandiId}`;
    const hit = CACHE.get(key);
    if (hit)
        return hit;
    const crop = (0, crops_1.cropById)(cropId);
    const mandi = mandis_1.MANDIS.find((m) => m.id === mandiId) ?? mandis_1.MANDIS[0];
    const level = crop.basePrice * mandiFactor(mandiId);
    const volatility = 0.014 + (5 - crop.perishability) * 0.006;
    const raw = buildSeries(mandiId * 9173 + cropId.length * 811 + crop.basePrice, level, volatility);
    // Anchor the last point on the board price so every page quotes one number.
    const target = todayPrice(cropId, mandi.id);
    const k = target / raw[raw.length - 1];
    const scaled = raw.map((v) => v * k);
    CACHE.set(key, scaled);
    return scaled;
}
/** The board price for a crop at a mandi, today. */
function todayPrice(cropId, mandiId) {
    const crop = (0, crops_1.cropById)(cropId);
    const mandi = mandis_1.MANDIS.find((m) => m.id === mandiId) ?? mandis_1.MANDIS[0];
    if (cropId === "onion")
        return mandi.todayModal;
    return Math.round(crop.basePrice * mandiFactor(mandiId));
}
function todayChangePct(cropId, mandiId) {
    const rand = (0, seed_1.mulberry32)(mandiId * 77 + cropId.length * 991 + (0, crops_1.cropById)(cropId).basePrice);
    return Math.round((rand() * 9 - 3.6) * 10) / 10;
}
function todayArrivals(cropId, mandiId) {
    const mandi = mandis_1.MANDIS.find((m) => m.id === mandiId) ?? mandis_1.MANDIS[0];
    const rand = (0, seed_1.mulberry32)(mandiId * 131 + cropId.length * 577);
    return Math.round(mandi.arrivalQtl * (0.25 + rand() * 0.9));
}
/** History plus a P10–P50–P90 fan for the next 15 days. */
function seriesFor(mandiName, cropId = "onion") {
    const mandi = mandis_1.MANDIS.find((m) => m.name === mandiName) ?? mandis_1.MANDIS[0];
    const history = seriesRaw(cropId, mandi.id);
    const points = [];
    for (let i = 0; i < history.length; i++) {
        points.push({
            date: (0, seed_1.isoDate)((0, seed_1.addDays)(seed_1.TODAY, i - history.length + 1)),
            modal: Math.round(history[i]),
            isForecast: false,
        });
    }
    const last = history[history.length - 1];
    const crop = (0, crops_1.cropById)(cropId);
    const rand = (0, seed_1.mulberry32)(Math.round(last) + 7717);
    /**
     * Expected drift per day. Storable produce is coming off a supply squeeze —
     * arrivals are below normal and prices are recovering — so holding it can pay
     * for the spoilage and interest it costs. Perishables have almost no drift,
     * which is what makes the engine tell you to sell them today.
     */
    const trend = crop.perishability >= 3 ? 0.012 : crop.perishability === 2 ? 0.004 : 0.0015;
    const spreadBase = 0.038 + (5 - crop.perishability) * 0.005;
    points[points.length - 1] = {
        ...points[points.length - 1],
        p10: Math.round(last),
        p50: Math.round(last),
        p90: Math.round(last),
    };
    for (let h = 1; h <= FORECAST_DAYS; h++) {
        const centre = last * (1 + trend * h + (0, seed_1.gaussian)(rand) * 0.004);
        const spread = spreadBase * Math.sqrt(h);
        points.push({
            date: (0, seed_1.isoDate)((0, seed_1.addDays)(seed_1.TODAY, h)),
            modal: null,
            p10: Math.round(centre * (1 - spread)),
            p50: Math.round(centre),
            p90: Math.round(centre * (1 + spread)),
            isForecast: true,
        });
    }
    return points;
}
function latestModal(mandiName, cropId = "onion") {
    const mandi = mandis_1.MANDIS.find((m) => m.name === mandiName) ?? mandis_1.MANDIS[0];
    return todayPrice(cropId, mandi.id);
}
function miniSeries(mandiName, cropId = "onion", n = 30) {
    const mandi = mandis_1.MANDIS.find((m) => m.name === mandiName) ?? mandis_1.MANDIS[0];
    return seriesRaw(cropId, mandi.id)
        .slice(-n)
        .map((v, i) => ({ i, v: Math.round(v) }));
}
exports.ALL_CROP_IDS = crops_1.CROPS.map((c) => c.id);
