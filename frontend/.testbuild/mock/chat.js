"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.resetChat = resetChat;
exports.openingMessages = openingMessages;
exports.nextReply = nextReply;
const SCRIPT = {
    greeting: {
        en: [
            "Namaskar 🙏 I am Bhav Setu. I tell you when and where to sell so you take home more.",
            "Which crop, and how many quintals?",
        ],
        mr: [
            "नमस्कार 🙏 मी भाव सेतू. कधी आणि कुठे विकायचं ते सांगतो, म्हणजे तुमच्या हातात जास्त पैसे राहतील.",
            "कोणतं पीक, आणि किती क्विंटल?",
        ],
        buttons: ["Onion 80 quintal", "Tomato 25 quintal", "Pomegranate 40 quintal"],
    },
    crop: {
        en: ["Got it. What grade is the lot?"],
        mr: ["समजलं. मालाचा दर्जा काय आहे?"],
        buttons: ["Grade A", "Grade B", "Grade C"],
    },
    grade: {
        en: ["Where is it stored right now?"],
        mr: ["सध्या माल कुठे साठवला आहे?"],
        buttons: ["Shed", "Open / ambient", "Cold store"],
    },
    storage: {
        en: [
            "Here is my advice 👇",
            "*Sell 50 quintal today at Lasalgaon* — ₹1,842 per quintal in your hand.\n*Hold 30 quintal for 9 days* — expected ₹1,918 (range ₹1,731 to ₹2,104).",
            "Why: arrivals are 22% below normal this week, and nearby markets are paying 3% more.\nConfidence: 71%",
            "That is about *₹6,240 more* than selling everything today at the nearest mandi.",
            "Three other farmers are taking a truck to Lasalgaon tomorrow — joining them cuts your transport from ₹504 to ₹126. Reply POOL to see it.",
        ],
        mr: [
            "हा माझा सल्ला 👇",
            "*आज लासलगावमध्ये ५० क्विंटल विका* — तुमच्या हातात ₹१,८४२ प्रति क्विंटल.\n*३० क्विंटल ९ दिवस थांबवा* — अपेक्षित ₹१,९१८ (₹१,७३१ ते ₹२,१०४).",
            "कारण: या आठवड्यात आवक नेहमीपेक्षा २२% कमी आहे, आणि जवळचे बाजार ३% जास्त भाव देत आहेत.\nविश्वास: ७१%",
            "आज सगळं जवळच्या बाजारात विकण्यापेक्षा हे सुमारे *₹६,२४० जास्त* आहे.",
            "उद्या तीन शेतकरी लासलगावला ट्रक घेऊन जात आहेत — त्यांच्यासोबत गेलात तर वाहतूक ₹५०४ वरून ₹१२६ होईल. POOL लिहा.",
        ],
        buttons: ["I sold today", "Remind me in 9 days", "POOL"],
    },
    advice: {
        en: ["Good. What price did you actually get, per quintal? 🙏"],
        mr: ["छान. तुम्हाला प्रत्यक्षात प्रति क्विंटल किती भाव मिळाला? 🙏"],
    },
    sale: {
        en: [
            "Recorded. Thank you — this makes the advice better for every farmer in your taluka.",
            "You can see it on the History page any time.",
        ],
        mr: [
            "नोंदवलं. धन्यवाद — यामुळे तुमच्या तालुक्यातील प्रत्येक शेतकऱ्याला चांगला सल्ला मिळेल.",
            "तुम्ही ते इतिहास पानावर कधीही पाहू शकता.",
        ],
        buttons: ["Ask about another lot"],
    },
    recorded: {
        en: ["Which crop, and how many quintals?"],
        mr: ["कोणतं पीक, आणि किती क्विंटल?"],
        buttons: ["Onion 80 quintal", "Tomato 25 quintal"],
    },
};
const POOL_REPLY = {
    en: [
        "*Truck to Lasalgaon — tomorrow 5:30 AM*\nRamesh Pawar (24 qtl), Sunita Jadhav (18 qtl), you (30 qtl).",
        "Cost alone: ₹504. Split three ways: ₹168 each. Organiser: Ramesh, 96733 38564.",
    ],
    mr: [
        "*लासलगावला ट्रक — उद्या सकाळी ५:३०*\nरमेश पवार (२४ क्विंटल), सुनीता जाधव (१८ क्विंटल), तुम्ही (३० क्विंटल).",
        "एकट्याचा खर्च: ₹५०४. तिघांत वाटल्यास: प्रत्येकी ₹१६८. संयोजक: रमेश, ९६७३३ ३८५६४.",
    ],
    buttons: ["I sold today"],
};
const FALLBACK = {
    en: [
        "Sorry, I did not follow that. You can tell me a crop and quantity like “onion 80 quintal”, or type POOL to share a truck.",
    ],
    mr: [
        "माफ करा, समजलं नाही. “कांदा ८० क्विंटल” असं पीक आणि प्रमाण सांगा, किंवा ट्रक शेअर करण्यासाठी POOL लिहा.",
    ],
    buttons: ["Onion 80 quintal", "POOL"],
};
const ORDER = ["greeting", "crop", "grade", "storage", "advice", "sale", "recorded"];
const MATCHERS = {
    crop: /onion|tomato|potato|pomegranate|grape|banana|okra|chilli|कांदा|टोमॅटो|डाळिंब|\d/i,
    grade: /grade|दर्जा|^\s*[abc]\s*$/i,
    storage: /shed|ambient|cold|open|शेड|साठवण/i,
    advice: /sold|विकल|price|भाव|remind/i,
    sale: /^\s*₹?\s*\d{3,6}\s*$/,
    recorded: /another|पुन्हा|new lot/i,
};
let cursor = 0;
function resetChat() {
    cursor = 0;
}
function toMessages(payload, lang, tag) {
    const stamp = new Date().toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
    return payload[lang].map((text, i) => ({
        id: `${tag}-${i}`,
        from: "bot",
        text,
        time: stamp,
        buttons: i === payload[lang].length - 1 ? payload.buttons : undefined,
    }));
}
function openingMessages(lang) {
    cursor = 1;
    const payload = SCRIPT.greeting;
    return payload[lang].map((text, i) => ({
        id: `bot-open-${i}`,
        from: "bot",
        text,
        time: "9:02 AM",
        buttons: i === payload[lang].length - 1 ? payload.buttons : undefined,
    }));
}
function nextReply(input, lang) {
    const tag = `bot-${Date.now()}`;
    // POOL works at any point in the conversation.
    if (/^\s*pool\s*$/i.test(input.trim())) {
        return toMessages(POOL_REPLY, lang, tag);
    }
    const expected = ORDER[cursor];
    const matcher = expected ? MATCHERS[expected] : undefined;
    if (expected && (!matcher || matcher.test(input))) {
        cursor = Math.min(cursor + 1, ORDER.length - 1);
        return toMessages(SCRIPT[expected], lang, tag);
    }
    // Let the farmer jump ahead — try any later step that matches.
    const jump = ORDER.slice(cursor).find((s) => MATCHERS[s]?.test(input));
    if (jump) {
        cursor = Math.min(ORDER.indexOf(jump) + 1, ORDER.length - 1);
        return toMessages(SCRIPT[jump], lang, tag);
    }
    return toMessages(FALLBACK, lang, tag);
}
