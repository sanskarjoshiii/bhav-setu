"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.DEMO_ACCOUNTS = void 0;
exports.findAccount = findAccount;
exports.DEMO_ACCOUNTS = [
    {
        phone: "9673338564",
        otp: "123456",
        name: "Sanskar Joshi",
        village: "Vinchur",
        district: "Nashik",
        riskProfile: "balanced",
        note: "Main demo account — 80 qtl onion in a shed",
    },
    {
        phone: "9545616125",
        otp: "123456",
        name: "Sunita Jadhav",
        village: "Niphad",
        district: "Nashik",
        riskProfile: "cautious",
        note: "Has a loan — gets safer, sell-sooner advice",
    },
    {
        phone: "9356476263",
        otp: "123456",
        name: "Balasaheb More",
        village: "Saykheda",
        district: "Nashik",
        riskProfile: "aggressive",
        note: "Cold store access — willing to hold longer",
    },
];
function findAccount(phone) {
    const digits = phone.replace(/[^0-9]/g, "").slice(-10);
    return exports.DEMO_ACCOUNTS.find((a) => a.phone === digits);
}
