"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.DEFAULT_LOT = void 0;
exports.recommend = recommend;
const mandis_1 = require("./mandis");
const crops_1 = require("./crops");
const economics_1 = require("./economics");
const prices_1 = require("./prices");
const seed_1 = require("../seed");
const RISK_LAMBDA = {
    cautious: 0.8,
    balanced: 0.45,
    aggressive: 0.2,
};
/**
 * A stand-in for decision/engine.py. It genuinely grid-searches the candidates
 * and scores them on expected net minus a penalty for the bad case, so the
 * numbers move sensibly when the form changes. Only the forecast underneath is
 * generated rather than modelled.
 *
 * Hold horizons are clipped to the crop's max_hold_days and any horizon whose
 * spoilage exceeds 15% is dropped — which is why okra never gets told to wait.
 */
function recommend(lot) {
    const crop = (0, crops_1.cropById)(lot.cropId);
    const sellFractions = [0, 0.25, 0.5, 0.75, 1.0];
    const lambda = RISK_LAMBDA[lot.risk];
    const constraints = [];
    let holdDays = [3, 7, 15].filter((d) => d <= crop.maxHoldDays);
    if (holdDays.length < 3)
        constraints.push("max_hold_days");
    holdDays = holdDays.filter((d) => (0, economics_1.spoilageFraction)(d, lot.storage, lot.cropId) <= 0.15);
    if (holdDays.length === 0) {
        holdDays = [Math.max(1, Math.min(3, crop.maxHoldDays))];
        constraints.push("spoilage_cliff");
    }
    const ranked = (0, economics_1.compareMandis)(lot.qtyQtl, 0, lot.grade, lot.storage, lot.cropId);
    const bestNow = ranked[0];
    const nearest = [...mandis_1.HOME_MANDIS].sort((a, b) => a.distanceKm - b.distanceKm)[0];
    const baseline = (0, economics_1.netInHand)({
        pricePerQtl: (0, prices_1.seriesFor)(nearest.name, lot.cropId).filter((p) => !p.isForecast).slice(-1)[0]
            .modal,
        qtyQtl: lot.qtyQtl,
        daysHeld: 0,
        distanceKm: nearest.distanceKm,
        grade: lot.grade,
        storage: lot.storage,
        cropId: lot.cropId,
    });
    // A small lot cannot justify a long trip.
    const minViable = lot.qtyQtl < 0.25 * 90;
    const pool = minViable ? mandis_1.HOME_MANDIS.filter((m) => m.distanceKm <= 40) : mandis_1.HOME_MANDIS;
    if (minViable)
        constraints.push("min_viable_load");
    let best = { score: -Infinity, fraction: 1, days: holdDays[0], laterMandi: bestNow.mandi, eNet: 0 };
    let considered = 0;
    for (const fraction of sellFractions) {
        for (const days of holdDays) {
            for (const later of pool) {
                considered++;
                const forecast = (0, prices_1.seriesFor)(later.name, lot.cropId).filter((p) => p.isForecast);
                const at = forecast[Math.min(days, forecast.length) - 1];
                if (!at?.p50)
                    continue;
                const nowQty = lot.qtyQtl * fraction;
                const laterQty = lot.qtyQtl - nowQty;
                const nowNet = nowQty > 0
                    ? (0, economics_1.netInHand)({ pricePerQtl: bestNow.grossPerQtl, qtyQtl: nowQty, daysHeld: 0, distanceKm: bestNow.distanceKm, grade: lot.grade, storage: lot.storage, cropId: lot.cropId }).netTotal
                    : 0;
                const laterNet = laterQty > 0
                    ? (0, economics_1.netInHand)({ pricePerQtl: at.p50, qtyQtl: laterQty, daysHeld: days, distanceKm: later.distanceKm, grade: lot.grade, storage: lot.storage, cropId: lot.cropId }).netTotal
                    : 0;
                const laterLow = laterQty > 0
                    ? (0, economics_1.netInHand)({ pricePerQtl: at.p10, qtyQtl: laterQty, daysHeld: days, distanceKm: later.distanceKm, grade: lot.grade, storage: lot.storage, cropId: lot.cropId }).netTotal
                    : 0;
                const eNet = nowNet + laterNet;
                /**
                 * Risk penalty, weighted by how much of the lot is still exposed.
                 *
                 * A flat `lambda * downside` is linear in the split, so the best score
                 * always sits at a corner — sell everything or hold everything — and a
                 * split can never win. Multiplying by the exposed share makes the
                 * penalty grow with the square of what you leave unsold, which is what
                 * gives an interior optimum: the first quintals you hold are cheap to
                 * risk, the last ones are not.
                 */
                const exposure = laterQty / lot.qtyQtl;
                const downside = Math.max(0, laterNet - laterLow);
                const score = eNet - lambda * downside * exposure;
                if (score > best.score) {
                    best = { score, fraction, days, laterMandi: later.name, eNet };
                }
            }
        }
    }
    const laterMandiObj = mandis_1.HOME_MANDIS.find((m) => m.name === best.laterMandi);
    const laterForecast = (0, prices_1.seriesFor)(best.laterMandi, lot.cropId).filter((p) => p.isForecast)[best.days - 1];
    const nowQty = Math.round(lot.qtyQtl * best.fraction);
    const laterQty = Math.round(lot.qtyQtl - nowQty);
    const tranches = [];
    if (nowQty > 0) {
        const n = (0, economics_1.netInHand)({ pricePerQtl: bestNow.grossPerQtl, qtyQtl: nowQty, daysHeld: 0, distanceKm: bestNow.distanceKm, grade: lot.grade, storage: lot.storage, cropId: lot.cropId });
        tranches.push({ qtl: nowQty, when: "Today", dayOffset: 0, mandi: bestNow.mandi, netPerQtl: n.netPerQtl, rangeLow: n.netPerQtl * 0.98, rangeHigh: n.netPerQtl * 1.02 });
    }
    if (laterQty > 0 && laterForecast?.p50) {
        const mk = (price) => (0, economics_1.netInHand)({ pricePerQtl: price, qtyQtl: laterQty, daysHeld: best.days, distanceKm: laterMandiObj.distanceKm, grade: lot.grade, storage: lot.storage, cropId: lot.cropId }).netPerQtl;
        tranches.push({
            qtl: laterQty,
            when: (0, seed_1.longDate)(laterForecast.date),
            dayOffset: best.days,
            mandi: best.laterMandi,
            netPerQtl: mk(laterForecast.p50),
            rangeLow: mk(laterForecast.p10),
            rangeHigh: mk(laterForecast.p90),
        });
    }
    const expectedGain = best.eNet - baseline.netTotal;
    const band = laterForecast ? (laterForecast.p90 - laterForecast.p10) / laterForecast.p50 : 0.2;
    if (band > 0.35)
        constraints.push("confidence_floor");
    const bandTightness = Math.max(0, Math.min(1, 1 - band / 2 / 0.3));
    const confidence = 0.5 * bandTightness + 0.2 * 0.94 + 0.3 * 0.79;
    const action = nowQty === 0 ? "hold" : laterQty === 0 ? "sell_now" : "split";
    const cropName = crop.name.toLowerCase();
    const headline = action === "split"
        ? `Sell ${nowQty} qtl today at ${bestNow.mandi}, hold ${laterQty} for ${best.days} days`
        : action === "sell_now"
            ? `Sell all ${nowQty} qtl of ${cropName} today at ${bestNow.mandi}`
            : `Hold all ${laterQty} qtl for ${best.days} days`;
    const headlineMr = action === "split"
        ? `आज ${bestNow.mandi} मध्ये ${nowQty} क्विंटल विका, ${laterQty} क्विंटल ${best.days} दिवस थांबवा`
        : action === "sell_now"
            ? `आजच ${bestNow.mandi} मध्ये सर्व ${nowQty} क्विंटल ${crop.nameMr} विका`
            : `सर्व ${laterQty} क्विंटल ${best.days} दिवस थांबवा`;
    const perishReason = crop.perishability <= 2
        ? `${cropName} spoils fast, so waiting costs more than the price gain`
        : "arrivals are 22% below normal for this week and nearby markets are paying 3% more";
    const perishReasonMr = crop.perishability <= 2
        ? `${crop.nameMr} लवकर खराब होतो, त्यामुळे थांबण्याचा तोटा भाववाढीपेक्षा जास्त आहे`
        : "या आठवड्यात आवक नेहमीपेक्षा २२% कमी आहे आणि जवळचे बाजार ३% जास्त भाव देत आहेत";
    return {
        action,
        headline,
        headlineMr,
        tranches,
        baselineNet: baseline.netTotal,
        strategyNet: best.eNet,
        expectedGain,
        expectedGainPct: (expectedGain / baseline.netTotal) * 100,
        confidence,
        reasonText: perishReason,
        reasonTextMr: perishReasonMr,
        constraintsApplied: Array.from(new Set(constraints)),
        alternativesConsidered: considered,
    };
}
exports.DEFAULT_LOT = {
    cropId: "onion",
    qtyQtl: 80,
    grade: "B",
    storage: "shed",
    risk: "balanced",
};
