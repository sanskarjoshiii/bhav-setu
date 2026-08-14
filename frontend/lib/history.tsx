"use client";

/**
 * Search history — every advice request the farmer has made, newest first.
 *
 * Persisted to localStorage so it survives a reload during a demo. Seeded with a
 * few past searches on first run so the History page is never empty on camera.
 *
 * TODO (Phase 8): move to GET/POST /api/v1/history keyed by farmer id.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { Grade, RiskProfile, Storage } from "./types";

export interface HistoryEntry {
  id: string;
  at: string;
  cropId: string;
  cropName: string;
  cropEmoji: string;
  qtyQtl: number;
  grade: Grade;
  storage: Storage;
  risk: RiskProfile;
  action: string;
  headline: string;
  mandi: string;
  netPerQtl: number;
  expectedGain: number;
  confidence: number;
}

const STORAGE_KEY = "bhavsetu.history";

const SEEDED: HistoryEntry[] = [
  {
    id: "H-2026-0007",
    at: "2026-08-12T09:14:00Z",
    cropId: "tomato",
    cropName: "Tomato",
    cropEmoji: "🍅",
    qtyQtl: 22,
    grade: "B",
    storage: "ambient",
    risk: "cautious",
    action: "sell_now",
    headline: "Sell all 22 qtl of tomato today at Lasalgaon",
    mandi: "Lasalgaon",
    netPerQtl: 1298,
    expectedGain: 1840,
    confidence: 0.74,
  },
  {
    id: "H-2026-0006",
    at: "2026-08-09T17:41:00Z",
    cropId: "pomegranate",
    cropName: "Pomegranate",
    cropEmoji: "🍎",
    qtyQtl: 40,
    grade: "A",
    storage: "cold_store",
    risk: "aggressive",
    action: "split",
    headline: "Sell 10 qtl today at Pimpalgaon Baswant, hold 30 for 15 days",
    mandi: "Pimpalgaon Baswant",
    netPerQtl: 6842,
    expectedGain: 24610,
    confidence: 0.68,
  },
  {
    id: "H-2026-0005",
    at: "2026-08-04T08:02:00Z",
    cropId: "onion",
    cropName: "Onion",
    cropEmoji: "🧅",
    qtyQtl: 80,
    grade: "B",
    storage: "shed",
    risk: "balanced",
    action: "split",
    headline: "Sell 40 qtl today at Lasalgaon, hold 40 for 7 days",
    mandi: "Lasalgaon",
    netPerQtl: 1871,
    expectedGain: 6240,
    confidence: 0.71,
  },
  {
    id: "H-2026-0004",
    at: "2026-07-28T11:26:00Z",
    cropId: "okra",
    cropName: "Okra (Bhindi)",
    cropEmoji: "🫑",
    qtyQtl: 9,
    grade: "B",
    storage: "ambient",
    risk: "balanced",
    action: "sell_now",
    headline: "Sell all 9 qtl of okra today at Yeola",
    mandi: "Yeola",
    netPerQtl: 2604,
    expectedGain: 720,
    confidence: 0.66,
  },
];

interface HistoryState {
  entries: HistoryEntry[];
  add: (entry: Omit<HistoryEntry, "id" | "at">) => void;
  remove: (id: string) => void;
  clear: () => void;
  ready: boolean;
}

const HistoryContext = createContext<HistoryState | null>(null);

export function HistoryProvider({ children }: { children: React.ReactNode }) {
  const [entries, setEntries] = useState<HistoryEntry[]>(SEEDED);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) setEntries(JSON.parse(raw) as HistoryEntry[]);
    } catch {
      // a corrupt demo history is not worth crashing over
    }
    setReady(true);
  }, []);

  const persist = useCallback((next: HistoryEntry[]) => {
    setEntries(next);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  }, []);

  const add = useCallback(
    (entry: Omit<HistoryEntry, "id" | "at">) => {
      setEntries((current) => {
        const next = [
          {
            ...entry,
            id: `H-2026-${String(1000 + current.length + 1).slice(1)}`,
            at: new Date().toISOString(),
          },
          ...current,
        ].slice(0, 40);
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
        return next;
      });
    },
    []
  );

  const remove = useCallback(
    (id: string) => persist(entries.filter((e) => e.id !== id)),
    [entries, persist]
  );

  const clear = useCallback(() => persist([]), [persist]);

  const value = useMemo(
    () => ({ entries, add, remove, clear, ready }),
    [entries, add, remove, clear, ready]
  );

  return <HistoryContext.Provider value={value}>{children}</HistoryContext.Provider>;
}

export function useHistory(): HistoryState {
  const ctx = useContext(HistoryContext);
  if (!ctx) throw new Error("useHistory must be used inside <HistoryProvider>");
  return ctx;
}
