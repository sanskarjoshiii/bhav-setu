"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.FRUITS = exports.VEGETABLES = exports.CROPS = void 0;
exports.cropById = cropById;
exports.CROPS = [
    { id: "onion", name: "Onion", nameMr: "कांदा", category: "vegetable", basePrice: 2010, perishability: 3, kC: 0.006, shelfLifeDays: 90, maxHoldDays: 20, season: "Kharif & Rabi", emoji: "🧅" },
    { id: "tomato", name: "Tomato", nameMr: "टोमॅटो", category: "vegetable", basePrice: 1480, perishability: 1, kC: 0.032, shelfLifeDays: 12, maxHoldDays: 4, season: "Year round", emoji: "🍅" },
    { id: "potato", name: "Potato", nameMr: "बटाटा", category: "vegetable", basePrice: 1240, perishability: 4, kC: 0.004, shelfLifeDays: 120, maxHoldDays: 30, season: "Rabi", emoji: "🥔" },
    { id: "brinjal", name: "Brinjal", nameMr: "वांगी", category: "vegetable", basePrice: 1620, perishability: 2, kC: 0.021, shelfLifeDays: 18, maxHoldDays: 6, season: "Kharif", emoji: "🍆" },
    { id: "cauliflower", name: "Cauliflower", nameMr: "फुलकोबी", category: "vegetable", basePrice: 1350, perishability: 2, kC: 0.024, shelfLifeDays: 15, maxHoldDays: 5, season: "Rabi", emoji: "🥦" },
    { id: "cabbage", name: "Cabbage", nameMr: "कोबी", category: "vegetable", basePrice: 980, perishability: 3, kC: 0.014, shelfLifeDays: 30, maxHoldDays: 10, season: "Rabi", emoji: "🥬" },
    { id: "green_chilli", name: "Green Chilli", nameMr: "हिरवी मिरची", category: "vegetable", basePrice: 3450, perishability: 2, kC: 0.026, shelfLifeDays: 14, maxHoldDays: 5, season: "Kharif", emoji: "🌶️" },
    { id: "okra", name: "Okra (Bhindi)", nameMr: "भेंडी", category: "vegetable", basePrice: 2870, perishability: 1, kC: 0.034, shelfLifeDays: 8, maxHoldDays: 3, season: "Kharif", emoji: "🫑" },
    { id: "carrot", name: "Carrot", nameMr: "गाजर", category: "vegetable", basePrice: 1760, perishability: 3, kC: 0.011, shelfLifeDays: 45, maxHoldDays: 14, season: "Rabi", emoji: "🥕" },
    { id: "garlic", name: "Garlic", nameMr: "लसूण", category: "vegetable", basePrice: 8900, perishability: 4, kC: 0.003, shelfLifeDays: 150, maxHoldDays: 40, season: "Rabi", emoji: "🧄" },
    { id: "banana", name: "Banana", nameMr: "केळी", category: "fruit", basePrice: 1680, perishability: 1, kC: 0.038, shelfLifeDays: 10, maxHoldDays: 3, season: "Year round", emoji: "🍌" },
    { id: "mango", name: "Mango", nameMr: "आंबा", category: "fruit", basePrice: 5400, perishability: 1, kC: 0.03, shelfLifeDays: 14, maxHoldDays: 5, season: "Summer", emoji: "🥭" },
    { id: "pomegranate", name: "Pomegranate", nameMr: "डाळिंब", category: "fruit", basePrice: 7250, perishability: 3, kC: 0.009, shelfLifeDays: 60, maxHoldDays: 18, season: "Year round", emoji: "🍎" },
    { id: "grapes", name: "Grapes", nameMr: "द्राक्ष", category: "fruit", basePrice: 6100, perishability: 2, kC: 0.019, shelfLifeDays: 21, maxHoldDays: 7, season: "Rabi", emoji: "🍇" },
    { id: "orange", name: "Orange", nameMr: "संत्रा", category: "fruit", basePrice: 3900, perishability: 3, kC: 0.012, shelfLifeDays: 35, maxHoldDays: 12, season: "Winter", emoji: "🍊" },
    { id: "sweet_lime", name: "Sweet Lime", nameMr: "मोसंबी", category: "fruit", basePrice: 3200, perishability: 3, kC: 0.013, shelfLifeDays: 30, maxHoldDays: 10, season: "Winter", emoji: "🍋" },
];
exports.VEGETABLES = exports.CROPS.filter((c) => c.category === "vegetable");
exports.FRUITS = exports.CROPS.filter((c) => c.category === "fruit");
function cropById(id) {
    return exports.CROPS.find((c) => c.id === id) ?? exports.CROPS[0];
}
