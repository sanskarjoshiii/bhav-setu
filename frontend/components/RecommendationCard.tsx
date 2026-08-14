"use client";

import { CalendarDays, MapPin, ShieldCheck, TrendingUp } from "lucide-react";
import type { Recommendation } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { cx, qtl, rupees } from "@/lib/format";
import ConfidenceMeter from "./ConfidenceMeter";

export default function RecommendationCard({ rec }: { rec: Recommendation }) {
  const { language } = useAuth();
  const headline = language === "mr" ? rec.headlineMr : rec.headline;
  const reason = language === "mr" ? rec.reasonTextMr : rec.reasonText;

  return (
    <div className="rise card overflow-hidden">
      <div className="bg-ink px-7 py-7 text-cream">
        <p className="text-[0.66rem] font-semibold uppercase tracking-[0.16em] text-cream/60">
          Our recommendation
        </p>
        <h2 className="mt-3 text-[1.55rem] font-bold leading-snug tracking-[-0.02em]">
          {headline}
        </h2>
        <p className="mt-3 text-[0.92rem] leading-relaxed text-cream/75">
          Because {reason}.
        </p>
      </div>

      <div className="grid divide-y divide-line md:grid-cols-3 md:divide-x md:divide-y-0">
        <div className="p-6">
          <p className="stat-label">If you sell everything today</p>
          <p className="mt-2 text-[1.35rem] font-bold tabular-nums text-muted">
            {rupees(rec.baselineNet)}
          </p>
          <p className="mt-1 text-[0.76rem] text-muted">At the nearest mandi</p>
        </div>
        <div className="p-6">
          <p className="stat-label">If you follow this plan</p>
          <p className="mt-2 text-[1.35rem] font-bold tabular-nums">{rupees(rec.strategyNet)}</p>
          <p className="mt-1 text-[0.76rem] text-muted">Expected, net in hand</p>
        </div>
        <div className="bg-panel/50 p-6">
          <p className="stat-label">Difference</p>
          <p
            className={cx(
              "mt-2 flex items-center gap-1.5 text-[1.35rem] font-bold tabular-nums",
              rec.expectedGain >= 0 ? "text-up" : "text-down"
            )}
          >
            <TrendingUp size={19} />
            {rec.expectedGain >= 0 ? "+" : ""}
            {rupees(rec.expectedGain)}
          </p>
          <p className="mt-1 text-[0.76rem] text-muted">
            {rec.expectedGainPct >= 0 ? "+" : ""}
            {rec.expectedGainPct.toFixed(1)}% on this lot
          </p>
        </div>
      </div>

      <div className="border-t border-line p-7">
        <p className="eyebrow mb-4">The plan, step by step</p>
        <ol className="space-y-3">
          {rec.tranches.map((tr, i) => (
            <li key={i} className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl bg-panel/45 px-5 py-4">
              <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-ink text-[0.72rem] font-bold text-cream">
                {i + 1}
              </span>
              <span className="text-[1rem] font-semibold">{qtl(tr.qtl)}</span>
              <span className="flex items-center gap-1.5 text-[0.86rem] text-muted">
                <CalendarDays size={14} />
                {tr.when}
              </span>
              <span className="flex items-center gap-1.5 text-[0.86rem] text-muted">
                <MapPin size={14} />
                {tr.mandi}
              </span>
              <span className="ml-auto text-right">
                <span className="block text-[1rem] font-bold tabular-nums">
                  {rupees(tr.netPerQtl)}/qtl
                </span>
                <span className="block text-[0.74rem] tabular-nums text-muted">
                  range {rupees(tr.rangeLow)} – {rupees(tr.rangeHigh)}
                </span>
              </span>
            </li>
          ))}
        </ol>
      </div>

      <div className="grid gap-6 border-t border-line p-7 md:grid-cols-2">
        <ConfidenceMeter value={rec.confidence} />
        <div>
          <p className="stat-label mb-2.5">Rules that were applied</p>
          <div className="flex flex-wrap gap-2">
            {rec.constraintsApplied.map((c) => (
              <span key={c} className="chip">
                <ShieldCheck size={12} />
                {c.replace(/_/g, " ")}
              </span>
            ))}
          </div>
          <p className="mt-3 text-[0.76rem] text-muted">
            {rec.alternativesConsidered} plans were scored before this one was chosen.
          </p>
        </div>
      </div>
    </div>
  );
}
