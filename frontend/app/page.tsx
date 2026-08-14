"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { ArrowRight, ArrowUpRight, Scale, ShieldCheck, TrendingUp } from "lucide-react";
import ForecastChart from "@/components/ForecastChart";
import Section from "@/components/Section";
import StatCard from "@/components/StatCard";
import { HOME_MANDIS as MANDIS } from "@/lib/mock/mandis";
import { seriesFor } from "@/lib/mock/prices";
import { ACCURACY } from "@/lib/mock/accuracy";
import { TRANSPARENCY_TOTALS } from "@/lib/mock/transparency";
import { CROPS } from "@/lib/mock/crops";
import { compactRupees, cx, pct, rupees } from "@/lib/format";

const MandiMap = dynamic(() => import("@/components/MandiMap"), {
  ssr: false,
  loading: () => <div className="h-[420px] animate-pulse rounded-2xl bg-panel" />,
});

const PILLARS = [
  {
    icon: TrendingUp,
    title: "A range, never a single number",
    body: "Every forecast comes as P10–P50–P90. Nobody can predict onion to the rupee, and pretending otherwise is how a farmer gets ruined.",
  },
  {
    icon: Scale,
    title: "Net in hand, not the board price",
    body: "Commission, cess, hamali, the diesel to get there, and what rots while you wait — all subtracted before we show you a number.",
  },
  {
    icon: ShieldCheck,
    title: "Checked against what really happened",
    body: "Farmers report the price they actually got. Those reports score every mandi and keep us honest on the Accuracy page.",
  },
];

export default function HomePage() {
  const [active, setActive] = useState(MANDIS[0].name);
  const series = useMemo(() => seriesFor(active), [active]);
  const mandi = MANDIS.find((m) => m.name === active)!;

  return (
    <>
      {/* Hero */}
      <div className="shell">
        <div className="panel grid items-center gap-10 rounded-2xl px-7 py-12 lg:grid-cols-2 lg:px-12 lg:py-16">
          <div>
            <p className="eyebrow">Selling decisions for farmers</p>
            <h1 className="h1 mt-4">
              Know what you will
              <br />
              actually take home.
            </h1>
            <p className="lede mt-5 max-w-md">
              Bhav Setu forecasts onion prices across the Nashik belt, subtracts every cost a
              farmer really pays, and tells you how much to sell today and how much to hold.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/advisor" className="btn-primary">
                Get my selling advice
                <ArrowRight size={16} />
              </Link>
              <Link href="/compare" className="btn-ghost">
                Compare mandis
              </Link>
            </div>
          </div>

          <div className="card p-6">
            <div className="flex items-baseline justify-between">
              <div>
                <p className="eyebrow">{mandi.name} · onion</p>
                <p className="mt-2 text-[2.1rem] font-bold tracking-[-0.02em]">
                  {rupees(mandi.todayModal)}
                  <span className="text-[0.9rem] font-medium text-muted">/quintal</span>
                </p>
              </div>
              <span
                className={cx(
                  "rounded-full px-2.5 py-1 text-[0.78rem] font-semibold",
                  mandi.changePct >= 0 ? "bg-up/10 text-up" : "bg-down/10 text-down"
                )}
              >
                {pct(mandi.changePct)}
              </span>
            </div>

            <div className="mt-4">
              <ForecastChart data={series.slice(-70)} height={190} />
            </div>

            <div className="mt-4 flex flex-wrap gap-1.5">
              {MANDIS.map((m) => (
                <button
                  key={m.id}
                  onClick={() => setActive(m.name)}
                  className={cx("chip", active === m.name && "chip-active")}
                >
                  {m.name}
                </button>
              ))}
            </div>
            <p className="mt-3 text-[0.74rem] text-muted">
              Solid line is what happened. Dashed line with the shaded band is the next 15 days.
            </p>
          </div>
        </div>
      </div>

      {/* Headline numbers */}
      <Section>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Uplift vs selling immediately"
            value={`+${ACCURACY.upliftPct}%`}
            hint="Backtested over the last 6 months"
            tone="up"
          />
          <StatCard
            label="Win rate"
            value={`${Math.round(ACCURACY.winRate * 100)}%`}
            hint="Scenarios that beat the baseline"
          />
          <StatCard
            label="Forecast error at 7 days"
            value={`${ACCURACY.mape[2].model}%`}
            hint={`Naive baseline: ${ACCURACY.mape[2].naive}%`}
          />
          <StatCard
            label="Crops covered"
            value={String(CROPS.length)}
            hint="Vegetables and fruits"
          />
        </div>
      </Section>

      {/* Pillars */}
      <Section title="What makes this different" description="Three decisions that shape everything else.">
        <div className="grid gap-3 md:grid-cols-3">
          {PILLARS.map((p) => (
            <div key={p.title} className="card p-6">
              <span className="grid h-10 w-10 place-items-center rounded-full bg-panel">
                <p.icon size={18} />
              </span>
              <h3 className="h3 mt-4">{p.title}</h3>
              <p className="mt-2.5 text-[0.88rem] leading-relaxed text-muted">{p.body}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* Live board */}
      <Section
        title="Today across the belt"
        description="Modal price and arrivals at each mandi we cover."
        aside={
          <Link href="/compare" className="btn-ghost">
            See net comparison
            <ArrowUpRight size={15} />
          </Link>
        }
      >
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px]">
              <thead className="border-b border-line bg-panel/40">
                <tr>
                  <th className="th">Mandi</th>
                  <th className="th">Distance</th>
                  <th className="th text-right">Modal ₹/qtl</th>
                  <th className="th text-right">Change</th>
                  <th className="th text-right">Arrivals</th>
                  <th className="th">Liquidity</th>
                </tr>
              </thead>
              <tbody>
                {MANDIS.map((m) => (
                  <tr key={m.id} className="border-b border-line/70 last:border-0 hover:bg-panel/30">
                    <td className="td font-medium">{m.name}</td>
                    <td className="td text-muted">{m.distanceKm} km</td>
                    <td className="td text-right font-semibold tabular-nums">
                      {rupees(m.todayModal)}
                    </td>
                    <td
                      className={cx(
                        "td text-right tabular-nums",
                        m.changePct >= 0 ? "text-up" : "text-down"
                      )}
                    >
                      {pct(m.changePct)}
                    </td>
                    <td className="td text-right tabular-nums text-muted">
                      {m.arrivalQtl.toLocaleString("en-IN")} qtl
                    </td>
                    <td className="td">
                      <span className="chip capitalize">{m.liquidity}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Section>

      {/* Map */}
      <Section
        title="Where these markets are"
        description="Distance is why the highest price is not always the best market."
      >
        <MandiMap />
      </Section>

      {/* CTA */}
      <Section>
        <div className="panel flex flex-col items-start justify-between gap-6 rounded-2xl px-8 py-10 md:flex-row md:items-center">
          <div className="max-w-lg">
            <h2 className="h3">Ask in Marathi, on WhatsApp</h2>
            <p className="mt-2 text-[0.92rem] leading-relaxed text-muted">
              The same engine answers on WhatsApp — tell it your crop, quantity and grade, and it
              replies with the plan. Then it asks what price you actually got.
            </p>
          </div>
          <Link href="/chat" className="btn-primary shrink-0">
            Open the chat demo
            <ArrowRight size={16} />
          </Link>
        </div>
      </Section>
    </>
  );
}
