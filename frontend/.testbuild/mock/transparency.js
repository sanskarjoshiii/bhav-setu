"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TRANSPARENCY_TOTALS = exports.TRANSPARENCY_SCORES = exports.SALE_REPORTS = void 0;
const mandis_1 = require("./mandis");
const seed_1 = require("../seed");
const NAMES = [
    "Ramesh Pawar", "Sunita Jadhav", "Balasaheb More", "Kavita Shinde", "Dattatray Gaikwad",
    "Mangal Sonawane", "Vikas Deshmukh", "Sarika Bhosale", "Ganesh Wagh", "Nanda Kale",
    "Prakash Chavan", "Rekha Nikam", "Sanjay Borude", "Ashwini Thorat", "Manoj Salunkhe",
    "Vaishali Dhage", "Ravindra Patil", "Jyoti Aher", "Sachin Kadam", "Meena Gadge",
    "Arun Bhagat", "Shobha Nagre", "Kishor Mali", "Pallavi Ugale", "Tanaji Bhoye",
    "Nilesh Ahire", "Surekha Pagar", "Yogesh Zope", "Anita Khairnar", "Popat Jagtap",
];
const VILLAGES = ["Vinchur", "Niphad", "Ugaon", "Saykheda", "Kotamgaon", "Palkhed", "Dixi"];
/** 32 sale reports — what the farmer was quoted versus what he actually took home.
 *  The gap is the whole point: it is always positive and it varies by mandi. */
exports.SALE_REPORTS = (() => {
    const rand = (0, seed_1.mulberry32)(884422);
    const reports = [];
    for (let i = 0; i < 32; i++) {
        const mandi = mandis_1.MANDIS[Math.floor(rand() * mandis_1.MANDIS.length)];
        const quoted = Math.round(1750 + rand() * 480);
        // Each mandi has its own habitual gap; Yeola is the honest one.
        const mandiGap = { Lasalgaon: 0.11, "Pimpalgaon Baswant": 0.14, Nashik: 0.16, Yeola: 0.08, Chandvad: 0.13 }[mandi.name] ?? 0.12;
        const gap = mandiGap + (rand() - 0.5) * 0.05;
        const received = Math.round(quoted * (1 - gap));
        reports.push({
            id: `SR-2026-${String(1000 + i).slice(1)}`,
            farmer: NAMES[i % NAMES.length],
            village: VILLAGES[Math.floor(rand() * VILLAGES.length)],
            mandi: mandi.name,
            date: (0, seed_1.isoDate)((0, seed_1.addDays)(seed_1.TODAY, -Math.floor(rand() * 58) - 1)),
            qtl: Math.round((6 + rand() * 70) * 10) / 10,
            quotedPerQtl: quoted,
            receivedPerQtl: received,
            gapPct: ((quoted - received) / quoted) * 100,
            followedAdvice: rand() > 0.32,
            verification: rand() > 0.72 ? "slip_photo" : rand() > 0.4 ? "self_reported" : "fpo_verified",
        });
    }
    return reports.sort((a, b) => b.date.localeCompare(a.date));
})();
exports.TRANSPARENCY_SCORES = mandis_1.MANDIS.map((m) => {
    const mine = exports.SALE_REPORTS.filter((r) => r.mandi === m.name);
    const gaps = mine.map((r) => r.gapPct).sort((a, b) => a - b);
    const median = gaps.length ? gaps[Math.floor(gaps.length / 2)] : 12;
    return {
        mandi: m.name,
        reports: mine.length,
        medianGapPct: median,
        score: Math.max(0, Math.min(10, 10 - (median - 6) * 0.9)),
        trend: (median < 11 ? "up" : median > 14 ? "down" : "flat"),
    };
}).sort((a, b) => b.score - a.score);
exports.TRANSPARENCY_TOTALS = {
    reports: exports.SALE_REPORTS.length,
    farmers: new Set(exports.SALE_REPORTS.map((r) => r.farmer)).size,
    villages: new Set(exports.SALE_REPORTS.map((r) => r.village)).size,
    medianGap: exports.SALE_REPORTS.map((r) => r.gapPct).sort((a, b) => a - b)[Math.floor(exports.SALE_REPORTS.length / 2)],
    followedAdvice: exports.SALE_REPORTS.filter((r) => r.followedAdvice).length,
};
