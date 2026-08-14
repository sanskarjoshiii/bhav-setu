"use client";

import type { CostLine } from "@/lib/types";
import { cx, rupees } from "@/lib/format";

/** Every rupee that leaves the gross, as a bar you can see. */
export default function CostWaterfall({
  lines,
  netPerQtl,
}: {
  lines: CostLine[];
  netPerQtl: number;
}) {
  const gross = lines.find((l) => l.kind === "gross")?.amount ?? 1;
  const deductions = lines.filter((l) => l.kind === "deduction");
  const net = gross + deductions.reduce((sum, l) => sum + l.amount, 0);

  return (
    <div className="grid gap-8 lg:grid-cols-[1.25fr_1fr]">
      <div>
        <p className="eyebrow mb-4">Where the money goes</p>
        <div className="space-y-2.5">
          {lines.map((l) => {
            const width = Math.max(1.5, (Math.abs(l.amount) / gross) * 100);
            return (
              <div key={l.label} className="grid grid-cols-[1fr_auto] items-center gap-4">
                <div className="min-w-0">
                  <div className="flex items-baseline justify-between gap-3">
                    <p className="truncate text-[0.85rem]">{l.label}</p>
                    <p
                      className={cx(
                        "shrink-0 text-[0.85rem] tabular-nums",
                        l.kind === "gross" ? "font-semibold" : "text-down"
                      )}
                    >
                      {l.kind === "gross" ? rupees(l.amount) : `− ${rupees(Math.abs(l.amount))}`}
                    </p>
                  </div>
                  <div className="mt-1.5 h-1.5 w-full rounded-full bg-line/70">
                    <div
                      className={cx(
                        "h-full rounded-full",
                        l.kind === "gross" ? "bg-ink" : "bg-down/60"
                      )}
                      style={{ width: `${width}%` }}
                    />
                  </div>
                </div>
              </div>
            );
          })}

          <div className="grid grid-cols-[1fr_auto] items-center gap-4 border-t border-line pt-3">
            <p className="text-[0.9rem] font-semibold">Net in hand</p>
            <p className="text-[0.95rem] font-bold tabular-nums">{rupees(net)}</p>
          </div>
        </div>
      </div>

      <div className="panel self-start rounded-2xl p-6">
        <p className="stat-label">Per quintal, after everything</p>
        <p className="mt-2 text-[2rem] font-bold tracking-[-0.02em]">{rupees(netPerQtl)}</p>
        <p className="mt-3 text-[0.82rem] leading-relaxed text-muted">
          Divided by the original quantity, so any spoilage during a hold shows up here as a lower
          rate rather than hiding in the total.
        </p>
      </div>
    </div>
  );
}
