"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, CalendarDays, MapPin, Search, TrendingDown, TrendingUp } from "lucide-react";
import PageHeader from "@/components/PageHeader";
import Section from "@/components/Section";
import StatCard from "@/components/StatCard";
import ForecastChart from "@/components/ForecastChart";
import { CROPS, FRUITS, VEGETABLES, type CropCategory } from "@/lib/mock/crops";
import { DISTRICTS, mandisInDistrict } from "@/lib/mock/mandis";
import { seriesFor, todayArrivals, todayChangePct, todayPrice } from "@/lib/mock/prices";
import { cx, pct, rupees } from "@/lib/format";
import { longDate } from "@/lib/seed";

type Tab = "all" | CropCategory;

const TABS: { id: Tab; label: string }[] = [
  { id: "all", label: "Today — all produce" },
  { id: "vegetable", label: "Vegetables" },
  { id: "fruit", label: "Fruits" },
];

export default function DashboardPage() {
  const [district, setDistrict] = useState(DISTRICTS[0]);
  const [tab, setTab] = useState<Tab>("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>("onion");

  const mandis = useMemo(() => mandisInDistrict(district), [district]);

  const crops = useMemo(() => {
    const base = tab === "all" ? CROPS : tab === "vegetable" ? VEGETABLES : FRUITS;
    const q = query.trim().toLowerCase();
    return q ? base.filter((c) => c.name.toLowerCase().includes(q) || c.nameMr.includes(q)) : base;
  }, [tab, query]);

  /** District price = the average across that district's mandis. */
  const rows = useMemo(
    () =>
      crops.map((crop) => {
        const prices = mandis.map((m) => todayPrice(crop.id, m.id));
        const avg = prices.reduce((a, b) => a + b, 0) / prices.length;
        const best = mandis[prices.indexOf(Math.max(...prices))];
        const change = todayChangePct(crop.id, mandis[0].id);
        const arrivals = mandis.reduce((sum, m) => sum + todayArrivals(crop.id, m.id), 0);
        return { crop, avg, best, bestPrice: Math.max(...prices), change, arrivals };
      }),
    [crops, mandis]
  );

  const gainers = [...rows].sort((a, b) => b.change - a.change).slice(0, 3);
  const losers = [...rows].sort((a, b) => a.change - b.change).slice(0, 3);
  const selectedCrop = CROPS.find((c) => c.id === selected) ?? CROPS[0];
  const chartMandi = mandis[0];

  return (
    <>
      <PageHeader
        eyebrow="Dashboard"
        title={`Today's mandi prices — ${district}`}
        lede="Every crop trading in your district right now, which mandi is paying the most for it, and how it moved since yesterday."
      >
        <div className="flex items-center gap-2 rounded-full border border-line bg-card px-4 py-2.5">
          <CalendarDays size={15} className="text-muted" />
          <span className="text-[0.86rem] font-medium">{longDate("2026-08-14")}</span>
        </div>
      </PageHeader>

      <Section>
        {/* District + search */}
        <div className="card mb-6 flex flex-wrap items-end gap-6 p-5">
          <div className="min-w-[220px]">
            <p className="label">District</p>
            <div className="flex flex-wrap gap-1.5">
              {DISTRICTS.map((d) => (
                <button
                  key={d}
                  onClick={() => setDistrict(d)}
                  className={cx("chip", district === d && "chip-active")}
                >
                  <MapPin size={12} />
                  {d}
                </button>
              ))}
            </div>
          </div>

          <div className="min-w-[240px] flex-1">
            <p className="label">Find a crop</p>
            <label className="relative flex items-center">
              <Search size={15} className="pointer-events-none absolute left-3.5 text-muted" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Tomato, कांदा, pomegranate…"
                className="input pl-10"
              />
            </label>
          </div>
        </div>

        <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Mandis reporting" value={String(mandis.length)} hint={`${district} district`} />
          <StatCard label="Crops trading" value={String(rows.length)} hint={tab === "all" ? "Vegetables and fruits" : tab === "vegetable" ? "Vegetables only" : "Fruits only"} />
          <StatCard label="Biggest gainer" value={gainers[0]?.crop.name ?? "—"} hint={gainers[0] ? pct(gainers[0].change) : ""} tone="up" />
          <StatCard label="Biggest faller" value={losers[0]?.crop.name ?? "—"} hint={losers[0] ? pct(losers[0].change) : ""} tone="down" />
        </div>

        {/* Category tabs */}
        <div className="mb-4 flex flex-wrap gap-1.5">
          {TABS.map((tb) => (
            <button
              key={tb.id}
              onClick={() => setTab(tb.id)}
              className={cx(
                "rounded-full border px-4 py-2 text-[0.86rem] font-medium transition",
                tab === tb.id
                  ? "border-ink bg-ink text-cream"
                  : "border-line bg-card text-ink/70 hover:border-ink/30"
              )}
            >
              {tb.label}
              <span className={cx("ml-2 text-[0.75rem]", tab === tb.id ? "text-cream/60" : "text-muted")}>
                {tb.id === "all" ? CROPS.length : tb.id === "vegetable" ? VEGETABLES.length : FRUITS.length}
              </span>
            </button>
          ))}
        </div>

        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px]">
              <thead className="border-b border-line bg-panel/40">
                <tr>
                  <th className="th">Crop</th>
                  <th className="th">Category</th>
                  <th className="th text-right">District avg ₹/qtl</th>
                  <th className="th text-right">Change</th>
                  <th className="th">Best mandi today</th>
                  <th className="th text-right">Arrivals</th>
                  <th className="th" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.crop.id}
                    onClick={() => setSelected(r.crop.id)}
                    className={cx(
                      "cursor-pointer border-b border-line/70 last:border-0 transition",
                      selected === r.crop.id ? "bg-panel/55" : "hover:bg-panel/30"
                    )}
                  >
                    <td className="td">
                      <div className="flex items-center gap-3">
                        <span className="text-[1.15rem]">{r.crop.emoji}</span>
                        <div>
                          <p className="font-medium">{r.crop.name}</p>
                          <p className="text-[0.75rem] text-muted">{r.crop.nameMr}</p>
                        </div>
                      </div>
                    </td>
                    <td className="td">
                      <span className="chip capitalize">{r.crop.category}</span>
                    </td>
                    <td className="td text-right text-[0.98rem] font-semibold tabular-nums">
                      {rupees(r.avg)}
                    </td>
                    <td className={cx("td text-right tabular-nums font-medium", r.change >= 0 ? "text-up" : "text-down")}>
                      <span className="inline-flex items-center gap-1">
                        {r.change >= 0 ? <TrendingUp size={13} /> : <TrendingDown size={13} />}
                        {pct(r.change)}
                      </span>
                    </td>
                    <td className="td">
                      <p className="font-medium">{r.best.name}</p>
                      <p className="text-[0.75rem] tabular-nums text-muted">{rupees(r.bestPrice)}/qtl</p>
                    </td>
                    <td className="td text-right tabular-nums text-muted">
                      {r.arrivals.toLocaleString("en-IN")} qtl
                    </td>
                    <td className="td text-right">
                      <Link
                        href={`/advisor?crop=${r.crop.id}`}
                        className="inline-flex items-center gap-1 whitespace-nowrap text-[0.8rem] text-muted transition hover:text-ink"
                        onClick={(e) => e.stopPropagation()}
                      >
                        Get advice
                        <ArrowUpRight size={13} />
                      </Link>
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={7} className="td py-12 text-center text-muted">
                      Nothing matches “{query}”.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </Section>

      <Section
        title={`${selectedCrop.name} at ${chartMandi.name}`}
        description="Click any row above to change the crop. Dashed line and shaded band are the 15-day forecast."
        aside={
          <Link href={`/advisor?crop=${selectedCrop.id}`} className="btn-ghost">
            Advice for {selectedCrop.name.toLowerCase()}
            <ArrowUpRight size={15} />
          </Link>
        }
      >
        <div className="card p-6">
          <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-[2.1rem] font-bold leading-none tracking-[-0.02em]">
                {rupees(todayPrice(selectedCrop.id, chartMandi.id))}
                <span className="text-[0.85rem] font-medium text-muted">/quintal</span>
              </p>
              <p className="mt-2 text-[0.82rem] text-muted">
                {selectedCrop.season} · shelf life {selectedCrop.shelfLifeDays} days · hold at most{" "}
                {selectedCrop.maxHoldDays} days
              </p>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {mandis.slice(0, 5).map((m) => (
                <span key={m.id} className="chip">
                  {m.name} · {rupees(todayPrice(selectedCrop.id, m.id))}
                </span>
              ))}
            </div>
          </div>
          <ForecastChart data={seriesFor(chartMandi.name, selectedCrop.id).slice(-80)} />
        </div>
      </Section>
    </>
  );
}
