import { cx } from "@/lib/format";

/** Confidence is never a bare number — it always carries the sentence that
 *  tells the farmer what to do about it. */
export default function ConfidenceMeter({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const low = value < 0.5;

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <p className="stat-label">Confidence</p>
        <p className="text-[1.05rem] font-bold">{pct}%</p>
      </div>
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-line">
        <div
          className={cx("h-full rounded-full", low ? "bg-down" : "bg-accent")}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-2 text-[0.76rem] leading-relaxed text-muted">
        {low
          ? "This market is unusually unpredictable right now — it is safer to sell today."
          : "Based on band width, data quality and how often past ranges held."}
      </p>
    </div>
  );
}
