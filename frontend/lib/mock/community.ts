import { COST_MODEL } from "./economics";

/**
 * Transport pooling. One farmer with 25 quintals still hires a whole truck; four
 * farmers heading to the same mandi on the same day split one, and each pays a
 * quarter of the diesel.
 *
 * The saving below is computed, not typed in: solo cost is one truck for the
 * distance, pooled cost is that same truck divided by the number of members.
 */

export interface PoolMember {
  name: string;
  nameMr: string;
  village: string;
  phone: string;
  cropId: string;
  cropName: string;
  cropEmoji: string;
  qtyQtl: number;
  isYou?: boolean;
  verified: boolean;
}

export interface TransportPool {
  id: string;
  mandi: string;
  district: string;
  distanceKm: number;
  date: string;
  dateLabel: string;
  departTime: string;
  truckCapacityQtl: number;
  status: "forming" | "confirmed" | "full";
  organiser: string;
  organiserPhone: string;
  members: PoolMember[];
}

export const POOLS: TransportPool[] = [
  {
    id: "POOL-2026-018",
    mandi: "Lasalgaon",
    district: "Nashik",
    distanceKm: 12,
    date: "2026-08-15",
    dateLabel: "Tomorrow, 15 August",
    departTime: "5:30 AM",
    truckCapacityQtl: 90,
    status: "forming",
    organiser: "Ramesh Pawar",
    organiserPhone: "+919673338564",
    members: [
      { name: "Ramesh Pawar", nameMr: "रमेश पवार", village: "Vinchur", phone: "+919673338564", cropId: "onion", cropName: "Onion", cropEmoji: "🧅", qtyQtl: 24, verified: true },
      { name: "Sunita Jadhav", nameMr: "सुनीता जाधव", village: "Niphad", phone: "+919545616125", cropId: "onion", cropName: "Onion", cropEmoji: "🧅", qtyQtl: 18, verified: true },
      { name: "You", nameMr: "तुम्ही", village: "Vinchur", phone: "+919673338564", cropId: "onion", cropName: "Onion", cropEmoji: "🧅", qtyQtl: 30, isYou: true, verified: true },
    ],
  },
  {
    id: "POOL-2026-019",
    mandi: "Pimpalgaon Baswant",
    district: "Nashik",
    distanceKm: 38,
    date: "2026-08-16",
    dateLabel: "Sunday, 16 August",
    departTime: "4:45 AM",
    truckCapacityQtl: 90,
    status: "confirmed",
    organiser: "Balasaheb More",
    organiserPhone: "+919356476263",
    members: [
      { name: "Balasaheb More", nameMr: "बाळासाहेब मोरे", village: "Saykheda", phone: "+919356476263", cropId: "tomato", cropName: "Tomato", cropEmoji: "🍅", qtyQtl: 20, verified: true },
      { name: "Kavita Shinde", nameMr: "कविता शिंदे", village: "Ugaon", phone: "+919881766547", cropId: "tomato", cropName: "Tomato", cropEmoji: "🍅", qtyQtl: 16, verified: true },
      { name: "Dattatray Gaikwad", nameMr: "दत्तात्रय गायकवाड", village: "Palkhed", phone: "+919595322341", cropId: "brinjal", cropName: "Brinjal", cropEmoji: "🍆", qtyQtl: 22, verified: false },
      { name: "Mangal Sonawane", nameMr: "मंगल सोनवणे", village: "Kotamgaon", phone: "+919673956309", cropId: "tomato", cropName: "Tomato", cropEmoji: "🍅", qtyQtl: 14, verified: true },
    ],
  },
  {
    id: "POOL-2026-020",
    mandi: "Nashik",
    district: "Nashik",
    distanceKm: 62,
    date: "2026-08-17",
    dateLabel: "Monday, 17 August",
    departTime: "5:00 AM",
    truckCapacityQtl: 90,
    status: "forming",
    organiser: "Vikas Deshmukh",
    organiserPhone: "+919545616125",
    members: [
      { name: "Vikas Deshmukh", nameMr: "विकास देशमुख", village: "Dixi", phone: "+919545616125", cropId: "pomegranate", cropName: "Pomegranate", cropEmoji: "🍎", qtyQtl: 12, verified: true },
      { name: "Sarika Bhosale", nameMr: "सारिका भोसले", village: "Vinchur", phone: "+919620592353", cropId: "grapes", cropName: "Grapes", cropEmoji: "🍇", qtyQtl: 9, verified: true },
    ],
  },
  {
    id: "POOL-2026-021",
    mandi: "Yeola",
    district: "Nashik",
    distanceKm: 24,
    date: "2026-08-15",
    dateLabel: "Tomorrow, 15 August",
    departTime: "6:00 AM",
    truckCapacityQtl: 90,
    status: "full",
    organiser: "Ganesh Wagh",
    organiserPhone: "+919356476263",
    members: [
      { name: "Ganesh Wagh", nameMr: "गणेश वाघ", village: "Niphad", phone: "+919356476263", cropId: "onion", cropName: "Onion", cropEmoji: "🧅", qtyQtl: 30, verified: true },
      { name: "Nanda Kale", nameMr: "नंदा काळे", village: "Ugaon", phone: "+919881766547", cropId: "onion", cropName: "Onion", cropEmoji: "🧅", qtyQtl: 28, verified: true },
      { name: "Prakash Chavan", nameMr: "प्रकाश चव्हाण", village: "Palkhed", phone: "+919595322341", cropId: "potato", cropName: "Potato", cropEmoji: "🥔", qtyQtl: 32, verified: true },
    ],
  },
];

export interface PoolEconomics {
  soloCost: number;
  pooledCostEach: number;
  savingEach: number;
  savingPct: number;
  totalQtl: number;
  capacityUsedPct: number;
}

export function poolEconomics(pool: TransportPool): PoolEconomics {
  const soloCost = pool.distanceKm * COST_MODEL.transportPerKm;
  const pooledCostEach = soloCost / pool.members.length;
  const totalQtl = pool.members.reduce((sum, m) => sum + m.qtyQtl, 0);
  return {
    soloCost,
    pooledCostEach,
    savingEach: soloCost - pooledCostEach,
    savingPct: ((soloCost - pooledCostEach) / soloCost) * 100,
    totalQtl,
    capacityUsedPct: Math.min(100, (totalQtl / pool.truckCapacityQtl) * 100),
  };
}

export const COMMUNITY_TOTALS = {
  activePools: POOLS.length,
  farmers: new Set(POOLS.flatMap((p) => p.members.map((m) => m.name))).size,
  savedThisMonth: POOLS.reduce((sum, p) => sum + poolEconomics(p).savingEach * p.members.length, 0),
};
