"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.CALIBRATION = exports.BACKTEST = exports.ACCURACY = void 0;
exports.residuals = residuals;
const seed_1 = require("../seed");
/** Numbers sit inside the sanity bands PLAN.md asks for: h=1 MAPE under 5%,
 *  h=7 under 10%, PICP between 0.72 and 0.88, directional accuracy above 0.60. */
exports.ACCURACY = {
    mape: [
        { horizon: 1, naive: 4.9, seasonal: 11.7, ma7: 5.6, model: 3.8 },
        { horizon: 3, naive: 7.4, seasonal: 12.4, ma7: 7.9, model: 5.9 },
        { horizon: 7, naive: 11.2, seasonal: 13.8, ma7: 10.8, model: 8.4 },
        { horizon: 15, naive: 16.7, seasonal: 15.9, ma7: 15.4, model: 12.6 },
    ],
    pinball: [
        { horizon: 1, naive: 24.1, seasonal: 51.3, ma7: 27.2, model: 18.4 },
        { horizon: 3, naive: 37.8, seasonal: 58.9, ma7: 39.6, model: 28.7 },
        { horizon: 7, naive: 56.4, seasonal: 67.2, ma7: 54.1, model: 41.2 },
        { horizon: 15, naive: 84.9, seasonal: 79.6, ma7: 78.3, model: 62.8 },
    ],
    picp: 0.79,
    directionalAccuracy: 0.643,
    modelVersion: "lgbm-q-2026.08.11-3",
    trainedAt: "11 August 2026, 01:12",
    trainRows: 41830,
    upliftPct: 8.4,
    winRate: 0.64,
};
exports.BACKTEST = [
    { month: "Feb", strategy: 1786, baseline: 1702 },
    { month: "Mar", strategy: 1691, baseline: 1648 },
    { month: "Apr", strategy: 1842, baseline: 1690 },
    { month: "May", strategy: 1934, baseline: 1771 },
    { month: "Jun", strategy: 2015, baseline: 1848 },
    { month: "Jul", strategy: 1968, baseline: 1836 },
    { month: "Aug", strategy: 2104, baseline: 1921 },
];
exports.CALIBRATION = [
    { nominal: 10, observed: 11.4 },
    { nominal: 25, observed: 26.8 },
    { nominal: 50, observed: 48.9 },
    { nominal: 75, observed: 73.2 },
    { nominal: 90, observed: 88.1 },
];
/** Residual scatter for the "how wrong were we" panel. */
function residuals() {
    const rand = (0, seed_1.mulberry32)(20260811);
    const out = [];
    for (let i = 0; i < 120; i++) {
        const predicted = 1500 + rand() * 900;
        const actual = predicted * (1 + (rand() - 0.5) * 0.16);
        out.push({ predicted: Math.round(predicted), actual: Math.round(actual) });
    }
    return out;
}
