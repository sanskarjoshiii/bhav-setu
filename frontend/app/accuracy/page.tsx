"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import PageHeader from "@/components/PageHeader";
import Section from "@/components/Section";
import StatCard from "@/components/StatCard";
import { ACCURACY, BACKTEST, CALIBRATION, residuals } from "@/lib/mock/accuracy";
import { cx, plainPct, rupees } from "@/lib/format";

const TOOLTIP = {
  contentStyle: {
    borderRadius: 12,
    border: "1px solid #E2E2D6",
    fontSize: 12,
    boxShadow: "0 8px 30px rgba(22,22,15,0.12)",
  },
};

export default function AccuracyPage() {
  const scatter = residuals();

  return (
    <>
      <PageHeader
        eyebrow="Accuracy"
        title="How wrong are we, honestly?"
        lede="Every model here is measured against four dumb baselines on data it never trained on. If we could not beat “tomorrow will be the same as today”, you deserve to know."
      />

      <Section>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Uplift vs sell-now" value={`+${ACCURACY.upliftPct}%`} hint="₹ per quintal, backtested" tone="up" />
          <StatCard label="Win rate" value={plainPct(ACCURACY.winRate * 100, 0)} hint="Scenarios beating baseline" />
          <StatCard label="Band coverage (PICP)" value={ACCURACY.picp.toFixed(2)} hint="Target ≈ 0.80" />
          <StatCard label="Direction at 7 days" value={plainPct(ACCURACY.directionalAccuracy * 100)} hint="Target > 60%" />
        </div>
      </Section>

      <Section
        title="Against the baselines"
        description="MAPE, lower is better. Walk-forward validation with a purge gap — never a random split."
      >
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px]">
              <thead className="border-b border-line bg-panel/40">
                <tr>
                  <th className="th">Horizon</th>
                  <th className="th text-right">Naive</th>
                  <th className="th text-right">Seasonal</th>
                  <th className="th text-right">MA-7</th>
                  <th className="th text-right">Bhav Setu</th>
                  <th className="th text-right">Improvement</th>
                </tr>
              </thead>
              <tbody>
                {ACCURACY.mape.map((row) => {
                  const gain = ((row.naive - row.model) / row.naive) * 100;
                  return (
                    <tr key={row.horizon} className="border-b border-line/70 last:border-0">
                      <td className="td font-medium">{row.horizon} day{row.horizon > 1 ? "s" : ""}</td>
                      <td className="td text-right tabular-nums text-muted">{row.naive}%</td>
                      <td className="td text-right tabular-nums text-muted">{row.seasonal}%</td>
                      <td className="td text-right tabular-nums text-muted">{row.ma7}%</td>
                      <td className="td text-right font-semibold tabular-nums">{row.model}%</td>
                      <td className="td text-right font-medium tabular-nums text-up">
                        −{gain.toFixed(0)}%
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </Section>

      <Section title="Following the advice versus selling immediately" description="Average net ₹/quintal, month by month, over the held-out period.">
        <div className="card p-6">
          <div className="h-[300px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={BACKTEST} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="#E2E2D6" vertical={false} />
                <XAxis dataKey="month" tick={{ fontSize: 11, fill: "#6F6F63" }} axisLine={{ stroke: "#E2E2D6" }} tickLine={false} />
                <YAxis tickFormatter={(v) => `₹${v}`} tick={{ fontSize: 11, fill: "#6F6F63" }} axisLine={false} tickLine={false} width={58} />
                <Tooltip {...TOOLTIP} formatter={(v: unknown) => rupees(Number(v))} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="baseline" name="Sell immediately" fill="#C3C3B4" radius={[4, 4, 0, 0]} />
                <Bar dataKey="strategy" name="Bhav Setu plan" fill="#1F3D2B" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </Section>

      <Section>
        <div className="grid gap-3 lg:grid-cols-2">
          <div className="card p-6">
            <h3 className="h3">Are the ranges honest?</h3>
            <p className="mt-1 text-[0.84rem] text-muted">
              If we say 80% of prices land inside the band, roughly 80% should. Close to the
              diagonal is good.
            </p>
            <div className="mt-5 h-[260px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={CALIBRATION} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#E2E2D6" />
                  <XAxis dataKey="nominal" tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11, fill: "#6F6F63" }} axisLine={{ stroke: "#E2E2D6" }} tickLine={false} />
                  <YAxis tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11, fill: "#6F6F63" }} axisLine={false} tickLine={false} width={44} />
                  <Tooltip {...TOOLTIP} />
                  <Line dataKey="nominal" stroke="#C3C3B4" strokeDasharray="4 4" dot={false} name="Perfect" />
                  <Line dataKey="observed" stroke="#1F3D2B" strokeWidth={2} name="Observed" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="card p-6">
            <h3 className="h3">Predicted versus actual</h3>
            <p className="mt-1 text-[0.84rem] text-muted">
              Each dot is one forecast on the held-out period. Tight around the line is good.
            </p>
            <div className="mt-5 h-[260px]">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#E2E2D6" />
                  <XAxis type="number" dataKey="predicted" name="Predicted" domain={[1400, 2500]} tickFormatter={(v) => `₹${v}`} tick={{ fontSize: 11, fill: "#6F6F63" }} axisLine={{ stroke: "#E2E2D6" }} tickLine={false} />
                  <YAxis type="number" dataKey="actual" name="Actual" domain={[1400, 2500]} tickFormatter={(v) => `₹${v}`} tick={{ fontSize: 11, fill: "#6F6F63" }} axisLine={false} tickLine={false} width={58} />
                  <ZAxis range={[26, 26]} />
                  <Tooltip {...TOOLTIP} formatter={(v: unknown) => rupees(Number(v))} />
                  <Scatter data={scatter} fill="#1F3D2B" fillOpacity={0.45} />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </Section>

      <Section title="Model in production">
        <div className="card grid gap-6 p-7 sm:grid-cols-4">
          {[
            ["Version", ACCURACY.modelVersion],
            ["Trained", ACCURACY.trainedAt],
            ["Training rows", ACCURACY.trainRows.toLocaleString("en-IN")],
            ["Algorithm", "LightGBM quantile ×12"],
          ].map(([label, value]) => (
            <div key={label}>
              <p className="stat-label">{label}</p>
              <p className="mt-1.5 text-[0.95rem] font-semibold">{value}</p>
            </div>
          ))}
        </div>
      </Section>
    </>
  );
}
