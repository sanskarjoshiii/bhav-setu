"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PricePoint } from "@/lib/types";
import { rupees } from "@/lib/format";
import { shortDate } from "@/lib/seed";

/**
 * History as a solid line, forecast as a dashed median inside a P10–P90 band.
 * The band is drawn as an Area of [p10, p90] so it reads as uncertainty rather
 * than as two more predictions.
 */
export default function ForecastChart({
  data,
  height = 320,
}: {
  data: PricePoint[];
  height?: number;
}) {
  const rows = data.map((d) => ({
    date: d.date,
    modal: d.modal,
    p50: d.p50 ?? null,
    band: d.p10 != null && d.p90 != null ? [d.p10, d.p90] : null,
  }));

  const firstForecast = data.find((d) => d.isForecast)?.date;
  const values = data.flatMap((d) =>
    [d.modal, d.p10, d.p90].filter((v): v is number => typeof v === "number")
  );
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min) * 0.12;

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#E2E2D6" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={shortDate}
            tick={{ fontSize: 11, fill: "#6F6F63" }}
            axisLine={{ stroke: "#E2E2D6" }}
            tickLine={false}
            minTickGap={44}
          />
          <YAxis
            domain={[Math.floor(min - pad), Math.ceil(max + pad)]}
            tickFormatter={(v) => `₹${v}`}
            tick={{ fontSize: 11, fill: "#6F6F63" }}
            axisLine={false}
            tickLine={false}
            width={58}
          />
          <Tooltip
            contentStyle={{
              borderRadius: 12,
              border: "1px solid #E2E2D6",
              fontSize: 12,
              boxShadow: "0 8px 30px rgba(22,22,15,0.12)",
            }}
            labelFormatter={(l) => shortDate(String(l))}
            formatter={(value: unknown, name: string) => {
              if (Array.isArray(value)) {
                return [`${rupees(value[0])} – ${rupees(value[1])}`, "P10–P90 range"];
              }
              if (value == null) return ["—", name];
              return [rupees(Number(value)), name === "modal" ? "Actual" : "Forecast (P50)"];
            }}
          />

          <Area
            dataKey="band"
            stroke="none"
            fill="#8AA79A"
            fillOpacity={0.22}
            isAnimationActive={false}
            connectNulls
          />
          {firstForecast && (
            <ReferenceLine
              x={firstForecast}
              stroke="#16160F"
              strokeDasharray="3 3"
              strokeOpacity={0.35}
              label={{ value: "today", position: "insideTopLeft", fontSize: 10, fill: "#6F6F63" }}
            />
          )}
          <Line
            dataKey="modal"
            stroke="#16160F"
            strokeWidth={1.8}
            dot={false}
            isAnimationActive={false}
            connectNulls={false}
          />
          <Line
            dataKey="p50"
            stroke="#1F3D2B"
            strokeWidth={1.8}
            strokeDasharray="5 4"
            dot={false}
            isAnimationActive={false}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
