import type { PricePoint } from "../types";
import { MANDIS } from "./mandis";
import { CROPS, cropById } from "./crops";
import { TODAY, addDays, gaussian, isoDate, mulberry32 } from "../seed";

/**
 * Price series that behave like real produce: a seasonal swing, a post-harvest
 * slump, one policy shock that knocks ~18% off over four days, and daily noise.
 * Every series is generated from a fixed seed, so nothing moves between renders
 * and the server and client always agree.
 */

const HISTORY_DAYS = 180;
const FORECAST_DAYS = 15;

/** Each mandi trades a little above or below the belt reference. */
function mandiFactor(mandiId: number): number {
  const rand = mulberry32(mandiId * 3301 + 17);
  return 0.94 + rand() * 0.12;
}

function buildSeries(seedBase: number, level: number, volatility: number): number[] {
  const rand = mulberry32(seedBase);
  const out: number[] = [];
  let price = level * 0.82;

  for (let i = 0; i < HISTORY_DAYS; i++) {
    const t = i / HISTORY_DAYS;
    const seasonal = Math.sin((i / 365) * Math.PI * 2 - 1.1) * 0.09;
    const drift = 0.22 * t;
    const shock =
      i > HISTORY_DAYS - 78 && i < HISTORY_DAYS - 60
        ? -0.18 * Math.min(1, (i - (HISTORY_DAYS - 78)) / 4)
        : 0;
    const recovery =
      i >= HISTORY_DAYS - 60 ? 0.11 * Math.min(1, (i - (HISTORY_DAYS - 60)) / 25) : 0;
    const noise = gaussian(rand) * volatility;

    const target = level * (0.82 + seasonal + drift + shock + recovery);
    price = price * 0.86 + target * 0.14 + price * noise;
    out.push(Math.max(level * 0.25, price));
  }
  return out;
}

const CACHE = new Map<string, number[]>();

/** Perishable produce swings harder — volatility scales with perishability. */
function seriesRaw(cropId: string, mandiId: number): number[] {
  const key = `${cropId}:${mandiId}`;
  const hit = CACHE.get(key);
  if (hit) return hit;

  const crop = cropById(cropId);
  const mandi = MANDIS.find((m) => m.id === mandiId) ?? MANDIS[0];
  const level = crop.basePrice * mandiFactor(mandiId);
  const volatility = 0.014 + (5 - crop.perishability) * 0.006;

  const raw = buildSeries(
    mandiId * 9173 + cropId.length * 811 + crop.basePrice,
    level,
    volatility
  );
  // Anchor the last point on the board price so every page quotes one number.
  const target = todayPrice(cropId, mandi.id);
  const k = target / raw[raw.length - 1];
  const scaled = raw.map((v) => v * k);
  CACHE.set(key, scaled);
  return scaled;
}

/** The board price for a crop at a mandi, today. */
export function todayPrice(cropId: string, mandiId: number): number {
  const crop = cropById(cropId);
  const mandi = MANDIS.find((m) => m.id === mandiId) ?? MANDIS[0];
  if (cropId === "onion") return mandi.todayModal;
  return Math.round(crop.basePrice * mandiFactor(mandiId));
}

export function todayChangePct(cropId: string, mandiId: number): number {
  const rand = mulberry32(mandiId * 77 + cropId.length * 991 + cropById(cropId).basePrice);
  return Math.round((rand() * 9 - 3.6) * 10) / 10;
}

export function todayArrivals(cropId: string, mandiId: number): number {
  const mandi = MANDIS.find((m) => m.id === mandiId) ?? MANDIS[0];
  const rand = mulberry32(mandiId * 131 + cropId.length * 577);
  return Math.round(mandi.arrivalQtl * (0.25 + rand() * 0.9));
}

/** History plus a P10–P50–P90 fan for the next 15 days. */
export function seriesFor(mandiName: string, cropId = "onion"): PricePoint[] {
  const mandi = MANDIS.find((m) => m.name === mandiName) ?? MANDIS[0];
  const history = seriesRaw(cropId, mandi.id);
  const points: PricePoint[] = [];

  for (let i = 0; i < history.length; i++) {
    points.push({
      date: isoDate(addDays(TODAY, i - history.length + 1)),
      modal: Math.round(history[i]),
      isForecast: false,
    });
  }

  const last = history[history.length - 1];
  const crop = cropById(cropId);
  const rand = mulberry32(Math.round(last) + 7717);

  /**
   * Expected drift per day. Storable produce is coming off a supply squeeze —
   * arrivals are below normal and prices are recovering — so holding it can pay
   * for the spoilage and interest it costs. Perishables have almost no drift,
   * which is what makes the engine tell you to sell them today.
   */
  const trend = crop.perishability >= 3 ? 0.012 : crop.perishability === 2 ? 0.004 : 0.0015;
  const spreadBase = 0.038 + (5 - crop.perishability) * 0.005;

  points[points.length - 1] = {
    ...points[points.length - 1],
    p10: Math.round(last),
    p50: Math.round(last),
    p90: Math.round(last),
  };

  for (let h = 1; h <= FORECAST_DAYS; h++) {
    const centre = last * (1 + trend * h + gaussian(rand) * 0.004);
    const spread = spreadBase * Math.sqrt(h);
    points.push({
      date: isoDate(addDays(TODAY, h)),
      modal: null,
      p10: Math.round(centre * (1 - spread)),
      p50: Math.round(centre),
      p90: Math.round(centre * (1 + spread)),
      isForecast: true,
    });
  }

  return points;
}

export function latestModal(mandiName: string, cropId = "onion"): number {
  const mandi = MANDIS.find((m) => m.name === mandiName) ?? MANDIS[0];
  return todayPrice(cropId, mandi.id);
}

export function miniSeries(mandiName: string, cropId = "onion", n = 30): { i: number; v: number }[] {
  const mandi = MANDIS.find((m) => m.name === mandiName) ?? MANDIS[0];
  return seriesRaw(cropId, mandi.id)
    .slice(-n)
    .map((v, i) => ({ i, v: Math.round(v) }));
}

export const ALL_CROP_IDS = CROPS.map((c) => c.id);
