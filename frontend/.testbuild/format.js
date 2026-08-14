"use strict";
/** Indian-format money and number helpers. ₹1,82,73,558 not ₹18,273,558. */
Object.defineProperty(exports, "__esModule", { value: true });
exports.rupees = rupees;
exports.compactRupees = compactRupees;
exports.qtl = qtl;
exports.pct = pct;
exports.plainPct = plainPct;
exports.cx = cx;
function rupees(value, decimals = 0) {
    return "₹" + value.toLocaleString("en-IN", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });
}
function compactRupees(value) {
    if (Math.abs(value) >= 10000000)
        return `₹${(value / 10000000).toFixed(2)} Cr`;
    if (Math.abs(value) >= 100000)
        return `₹${(value / 100000).toFixed(2)} L`;
    if (Math.abs(value) >= 1000)
        return `₹${(value / 1000).toFixed(1)}K`;
    return rupees(value);
}
function qtl(value) {
    return `${value.toLocaleString("en-IN", { maximumFractionDigits: 1 })} qtl`;
}
function pct(value, decimals = 1) {
    return `${value >= 0 ? "+" : ""}${value.toFixed(decimals)}%`;
}
function plainPct(value, decimals = 1) {
    return `${value.toFixed(decimals)}%`;
}
function cx(...parts) {
    return parts.filter(Boolean).join(" ");
}
