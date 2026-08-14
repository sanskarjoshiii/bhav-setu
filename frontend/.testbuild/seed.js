"use strict";
/**
 * Deterministic pseudo-randomness.
 *
 * Every number on the site is generated, not typed out — but it must be the SAME
 * number on the server and in the browser or React throws a hydration mismatch.
 * A seeded generator gives us data that looks organic and never moves.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.TODAY = void 0;
exports.mulberry32 = mulberry32;
exports.gaussian = gaussian;
exports.addDays = addDays;
exports.isoDate = isoDate;
exports.shortDate = shortDate;
exports.longDate = longDate;
function mulberry32(seed) {
    let a = seed >>> 0;
    return () => {
        a = (a + 0x6d2b79f5) >>> 0;
        let t = Math.imul(a ^ (a >>> 15), 1 | a);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}
/** Box–Muller, so noise is normal rather than uniform — prices look real. */
function gaussian(rand) {
    const u = Math.max(rand(), 1e-9);
    const v = Math.max(rand(), 1e-9);
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}
/** Fixed "today" so the demo never drifts between recordings. */
exports.TODAY = new Date("2026-08-14T00:00:00Z");
function addDays(base, days) {
    const d = new Date(base);
    d.setUTCDate(d.getUTCDate() + days);
    return d;
}
function isoDate(d) {
    return d.toISOString().slice(0, 10);
}
function shortDate(iso) {
    const d = new Date(iso + "T00:00:00Z");
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });
}
function longDate(iso) {
    const d = new Date(iso + "T00:00:00Z");
    return d.toLocaleDateString("en-IN", {
        day: "numeric",
        month: "long",
        year: "numeric",
        timeZone: "UTC",
    });
}
