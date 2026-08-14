/**
 * The single seam between the UI and the backend.
 *
 * Right now every function returns seeded mock data synchronously wrapped in a
 * promise. When the FastAPI layer exists, each body becomes a `fetch` to
 * NEXT_PUBLIC_API_BASE_URL and NO COMPONENT CHANGES — they already await these.
 *
 * Keep the return shapes identical to lib/types.ts.
 */

import type {
  AccuracySummary,
  Grade,
  Mandi,
  MandiComparison,
  PricePoint,
  Recommendation,
  RiskProfile,
  SaleReport,
  Storage,
  TransparencyScore,
} from "./types";
import { MANDIS } from "./mock/mandis";
import { seriesFor } from "./mock/prices";
import { compareMandis } from "./mock/economics";
import { recommend, type LotInput } from "./mock/recommendation";
import { ACCURACY } from "./mock/accuracy";
import { SALE_REPORTS, TRANSPARENCY_SCORES } from "./mock/transparency";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
export const USING_MOCK_DATA = false;

/** A touch of latency so loading states are visible while recording. */
function settle<T>(value: T, ms = 260): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

// GET /api/v1/mandis
export function getMandis(): Promise<Mandi[]> {
  return settle(MANDIS);
}

// GET /api/v1/forecast?mandi=&commodity=onion
export function getForecast(mandiName: string, cropId = "onion"): Promise<PricePoint[]> {
  return settle(seriesFor(mandiName, cropId));
}

// POST /api/v1/recommend
export function postRecommend(lot: LotInput): Promise<Recommendation> {
  return settle(recommend(lot), 620);
}

// GET /api/v1/compare
export function getComparison(
  qtyQtl: number,
  daysHeld: number,
  grade: Grade,
  storage: Storage,
  cropId = "onion"
): Promise<MandiComparison[]> {
  return settle(compareMandis(qtyQtl, daysHeld, grade, storage, cropId));
}

// GET /api/v1/accuracy
export function getAccuracy(): Promise<AccuracySummary> {
  return settle(ACCURACY);
}

// GET /api/v1/transparency
export function getTransparency(): Promise<{
  scores: TransparencyScore[];
  reports: SaleReport[];
}> {
  return settle({ scores: TRANSPARENCY_SCORES, reports: SALE_REPORTS });
}

// POST /api/v1/sale-reports
export function postSaleReport(payload: {
  mandi: string;
  qtl: number;
  receivedPerQtl: number;
}): Promise<{ ok: true; id: string }> {
  return settle({ ok: true as const, id: `SR-2026-${Math.floor(Math.random() * 900 + 100)}` }, 500);
}

export type { LotInput, RiskProfile };
