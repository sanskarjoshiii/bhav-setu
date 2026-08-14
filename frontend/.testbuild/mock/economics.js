"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.COST_MODEL = void 0;
exports.spoilageFraction = spoilageFraction;
exports.netInHand = netInHand;
exports.compareMandis = compareMandis;
const mandis_1 = require("./mandis");
const crops_1 = require("./crops");
const prices_1 = require("./prices");
/**
 * The Net In-Hand engine, mirrored in TypeScript for the demo.
 *
 * Same formula the Python side will use: gross, minus percentage fees, minus
 * per-quintal handling, minus transport, minus holding — and net_per_qtl is
 * divided by the ORIGINAL quantity so spoilage shows up as a lower rate.
 */
exports.COST_MODEL = {
    gradeFactor: { A: 1.1, B: 1.0, C: 0.86 },
    storageFactor: { ambient: 1.0, shed: 0.7, cold_store: 0.25 },
    storageCostPerQtlPerDay: { ambient: 0, shed: 0.6, cold_store: 3.5 },
    hamaliPerQtl: 12,
    weighingPerQtl: 3,
    packingPerQtl: 8,
    truckCapacityQtl: 90,
    transportPerKm: 42,
    interestRateAnnual: 0.14,
    commissionPct: 3.0,
    apmcCessPct: 1.05,
    otherFeesPct: 0.3,
    kC: 0.006,
};
function spoilageFraction(days, storage, cropId = "onion", tmaxMean = 32) {
    const fStorage = exports.COST_MODEL.storageFactor[storage];
    const fTemp = 1 + 0.04 * Math.max(0, tmaxMean - 30);
    return 1 - Math.exp(-(0, crops_1.cropById)(cropId).kC * fStorage * fTemp * days);
}
function netInHand(input) {
    const { pricePerQtl, qtyQtl, daysHeld, distanceKm, grade, storage, cropId = "onion" } = input;
    const spoil = spoilageFraction(daysHeld, storage, cropId);
    const qEff = qtyQtl * (1 - spoil);
    const gross = pricePerQtl * qEff * exports.COST_MODEL.gradeFactor[grade];
    const pctFees = (exports.COST_MODEL.commissionPct + exports.COST_MODEL.apmcCessPct + exports.COST_MODEL.otherFeesPct) / 100;
    const perQtlFee = exports.COST_MODEL.hamaliPerQtl + exports.COST_MODEL.weighingPerQtl + exports.COST_MODEL.packingPerQtl;
    const commission = gross * (exports.COST_MODEL.commissionPct / 100);
    const cess = gross * (exports.COST_MODEL.apmcCessPct / 100);
    const other = gross * (exports.COST_MODEL.otherFeesPct / 100);
    const handling = qEff * perQtlFee;
    const deductions = gross * pctFees + handling;
    const trucks = Math.ceil(qEff / exports.COST_MODEL.truckCapacityQtl);
    const transport = trucks * distanceKm * exports.COST_MODEL.transportPerKm;
    const storageCost = exports.COST_MODEL.storageCostPerQtlPerDay[storage] * qtyQtl * daysHeld;
    const interest = gross * (exports.COST_MODEL.interestRateAnnual / 365) * daysHeld;
    const holding = storageCost + interest;
    const netTotal = gross - deductions - transport - holding;
    const lines = [
        { label: "Gross at mandi", labelMr: "बाजारातील एकूण", amount: gross, kind: "gross" },
        { label: "APMC commission (3.0%)", labelMr: "आडत (३.०%)", amount: -commission, kind: "deduction" },
        { label: "Market cess (1.05%)", labelMr: "बाजार उपकर (१.०५%)", amount: -cess, kind: "deduction" },
        { label: "Other fees (0.3%)", labelMr: "इतर शुल्क (०.३%)", amount: -other, kind: "deduction" },
        { label: "Hamali, weighing, packing", labelMr: "हमाली, वजन, पॅकिंग", amount: -handling, kind: "deduction" },
        { label: `Transport (${trucks} truck${trucks > 1 ? "s" : ""} × ${distanceKm} km)`, labelMr: `वाहतूक (${distanceKm} कि.मी.)`, amount: -transport, kind: "deduction" },
    ];
    if (holding > 0) {
        lines.push({
            label: `Holding ${daysHeld} days (storage + interest)`,
            labelMr: `${daysHeld} दिवस साठवण + व्याज`,
            amount: -holding,
            kind: "deduction",
        });
    }
    return {
        gross,
        deductions,
        transport,
        holding,
        spoilageQtl: qtyQtl - qEff,
        netTotal,
        netPerQtl: netTotal / qtyQtl,
        grossPerQtl: pricePerQtl * exports.COST_MODEL.gradeFactor[grade],
        lines,
    };
}
/** The money shot: rank by gross, rank by net, flag where the two disagree. */
function compareMandis(qtyQtl, daysHeld, grade, storage, cropId = "onion", pool = mandis_1.HOME_MANDIS) {
    const rows = pool.map((m) => {
        const price = (0, prices_1.latestModal)(m.name, cropId);
        const net = netInHand({
            pricePerQtl: price,
            qtyQtl,
            daysHeld,
            distanceKm: m.distanceKm,
            grade,
            storage,
            cropId,
        });
        return {
            mandi: m.name,
            distanceKm: m.distanceKm,
            grossPerQtl: net.grossPerQtl,
            netPerQtl: net.netPerQtl,
            rankByGross: 0,
            rankByNet: 0,
            rankFlipped: false,
            breakdown: net.lines,
        };
    });
    [...rows]
        .sort((a, b) => b.grossPerQtl - a.grossPerQtl)
        .forEach((r, i) => (r.rankByGross = i + 1));
    [...rows].sort((a, b) => b.netPerQtl - a.netPerQtl).forEach((r, i) => (r.rankByNet = i + 1));
    rows.forEach((r) => (r.rankFlipped = r.rankByGross !== r.rankByNet));
    return rows.sort((a, b) => a.rankByNet - b.rankByNet);
}
