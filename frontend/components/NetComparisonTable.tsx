"use client";

import { Fragment, useState } from "react";
import { ArrowDownRight, ArrowUpRight, ChevronDown } from "lucide-react";
import type { MandiComparison } from "@/lib/types";
import { cx, rupees } from "@/lib/format";
import CostWaterfall from "./CostWaterfall";

/**
 * The demo moment. Rank by the board price and rank by what actually reaches the
 * farmer, side by side — and mark every row where the two disagree.
 */
export default function NetComparisonTable({ rows }: { rows: MandiComparison[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const flips = rows.filter((r) => r.rankFlipped).length;

  return (
    <div className="card overflow-hidden">
      {flips > 0 && (
        <div className="flex items-start gap-2.5 border-b border-line bg-panel/60 px-5 py-3.5">
          <ArrowDownRight size={16} className="mt-0.5 shrink-0 text-down" />
          <p className="text-[0.85rem] leading-relaxed">
            <span className="font-semibold">{flips} of {rows.length} markets change position</span>{" "}
            once commission, cess, hamali and transport come out. The highest board price is not the
            best market for this lot.
          </p>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px]">
          <thead className="border-b border-line bg-panel/40">
            <tr>
              <th className="th">Mandi</th>
              <th className="th">Distance</th>
              <th className="th text-right">Gross ₹/qtl</th>
              <th className="th text-right">Net in hand ₹/qtl</th>
              <th className="th text-center">By gross</th>
              <th className="th text-center">By net</th>
              <th className="th" />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const isOpen = open === r.mandi;
              const moved = r.rankByGross - r.rankByNet;
              return (
                <Fragment key={r.mandi}>
                  <tr
                    className={cx(
                      "border-b border-line/70 transition",
                      isOpen ? "bg-panel/50" : "hover:bg-panel/30"
                    )}
                  >
                    <td className="td font-medium">
                      {r.mandi}
                      {r.rankByNet === 1 && (
                        <span className="ml-2 rounded-full bg-ink px-2 py-0.5 text-[0.62rem] font-semibold uppercase tracking-wide text-cream">
                          Best
                        </span>
                      )}
                    </td>
                    <td className="td text-muted">{r.distanceKm} km</td>
                    <td className="td text-right tabular-nums text-muted">
                      {rupees(r.grossPerQtl)}
                    </td>
                    <td className="td text-right text-[1rem] font-semibold tabular-nums">
                      {rupees(r.netPerQtl)}
                    </td>
                    <td className="td text-center tabular-nums text-muted">#{r.rankByGross}</td>
                    <td className="td text-center">
                      <span
                        className={cx(
                          "inline-flex items-center gap-1 tabular-nums font-medium",
                          moved > 0 && "text-up",
                          moved < 0 && "text-down"
                        )}
                      >
                        #{r.rankByNet}
                        {moved > 0 && <ArrowUpRight size={13} />}
                        {moved < 0 && <ArrowDownRight size={13} />}
                      </span>
                    </td>
                    <td className="td text-right">
                      <button
                        onClick={() => setOpen(isOpen ? null : r.mandi)}
                        className="inline-flex items-center gap-1 text-[0.8rem] text-muted transition hover:text-ink"
                      >
                        Breakdown
                        <ChevronDown
                          size={14}
                          className={cx("transition", isOpen && "rotate-180")}
                        />
                      </button>
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="border-b border-line/70 bg-panel/25">
                      <td colSpan={7} className="px-5 py-6">
                        <CostWaterfall lines={r.breakdown} netPerQtl={r.netPerQtl} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
