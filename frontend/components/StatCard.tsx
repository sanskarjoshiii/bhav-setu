import { cx } from "@/lib/format";

export default function StatCard({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "default" | "up" | "down";
}) {
  return (
    <div className="stat">
      <p className="stat-label">{label}</p>
      <p
        className={cx(
          "stat-value",
          tone === "up" && "text-up",
          tone === "down" && "text-down"
        )}
      >
        {value}
      </p>
      {hint && <p className="mt-1 text-[0.76rem] text-muted">{hint}</p>}
    </div>
  );
}
