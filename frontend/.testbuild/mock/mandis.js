"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.REFERENCE_VILLAGE = exports.HOME_MANDIS = exports.DISTRICTS = exports.MANDIS = void 0;
exports.mandiByName = mandiByName;
exports.mandisInDistrict = mandisInDistrict;
/** Three districts so the dashboard's district filter has real content.
 *  Distance is from the reference village, Vinchur (Nashik). */
exports.MANDIS = [
    // ── Nashik ───────────────────────────────────────────────────────────────
    { id: 1, name: "Lasalgaon", nameMr: "लासलगाव", district: "Nashik", lat: 20.1436, lon: 74.2372, distanceKm: 12, todayModal: 2010, changePct: 2.4, arrivalQtl: 14820, liquidity: "high" },
    { id: 2, name: "Pimpalgaon Baswant", nameMr: "पिंपळगाव बसवंत", district: "Nashik", lat: 20.1667, lon: 73.9833, distanceKm: 38, todayModal: 2022, changePct: 3.1, arrivalQtl: 11240, liquidity: "high" },
    { id: 3, name: "Nashik", nameMr: "नाशिक", district: "Nashik", lat: 19.9975, lon: 73.7898, distanceKm: 62, todayModal: 2030, changePct: 1.2, arrivalQtl: 6310, liquidity: "medium" },
    { id: 4, name: "Yeola", nameMr: "येवला", district: "Nashik", lat: 20.0424, lon: 74.4894, distanceKm: 24, todayModal: 1946, changePct: -0.8, arrivalQtl: 5180, liquidity: "medium" },
    { id: 5, name: "Chandvad", nameMr: "चांदवड", district: "Nashik", lat: 20.33, lon: 74.24, distanceKm: 31, todayModal: 1972, changePct: 0.6, arrivalQtl: 3940, liquidity: "low" },
    // ── Ahmadnagar ───────────────────────────────────────────────────────────
    { id: 6, name: "Rahuri", nameMr: "राहुरी", district: "Ahmadnagar", lat: 19.3894, lon: 74.6494, distanceKm: 96, todayModal: 1958, changePct: 1.8, arrivalQtl: 4620, liquidity: "medium" },
    { id: 7, name: "Shrirampur", nameMr: "श्रीरामपूर", district: "Ahmadnagar", lat: 19.6186, lon: 74.6597, distanceKm: 78, todayModal: 1994, changePct: -1.1, arrivalQtl: 3810, liquidity: "medium" },
    { id: 8, name: "Sangamner", nameMr: "संगमनेर", district: "Ahmadnagar", lat: 19.5686, lon: 74.2114, distanceKm: 71, todayModal: 1936, changePct: 0.4, arrivalQtl: 2740, liquidity: "low" },
    // ── Pune ─────────────────────────────────────────────────────────────────
    { id: 9, name: "Pune (Market Yard)", nameMr: "पुणे (मार्केट यार्ड)", district: "Pune", lat: 18.5018, lon: 73.8636, distanceKm: 168, todayModal: 2146, changePct: 2.9, arrivalQtl: 18940, liquidity: "high" },
    { id: 10, name: "Junnar", nameMr: "जुन्नर", district: "Pune", lat: 19.2076, lon: 73.8752, distanceKm: 124, todayModal: 2058, changePct: 1.4, arrivalQtl: 3260, liquidity: "low" },
    { id: 11, name: "Manchar", nameMr: "मंचर", district: "Pune", lat: 19.0028, lon: 73.9403, distanceKm: 139, todayModal: 2082, changePct: 0.9, arrivalQtl: 4470, liquidity: "medium" },
];
exports.DISTRICTS = Array.from(new Set(exports.MANDIS.map((m) => m.district)));
/** The five the advisor and comparison default to — one district, walkable set. */
exports.HOME_MANDIS = exports.MANDIS.filter((m) => m.district === "Nashik");
exports.REFERENCE_VILLAGE = {
    name: "Vinchur",
    nameMr: "विंचूर",
    district: "Nashik",
    lat: 20.11,
    lon: 74.32,
};
function mandiByName(name) {
    return exports.MANDIS.find((m) => m.name === name) ?? exports.MANDIS[0];
}
function mandisInDistrict(district) {
    return district === "All" ? exports.MANDIS : exports.MANDIS.filter((m) => m.district === district);
}
