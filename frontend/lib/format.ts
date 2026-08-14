/** Indian-format money and number helpers. ₹1,82,73,558 not ₹18,273,558. */

export function rupees(value: number, decimals = 0): string {
  return "₹" + value.toLocaleString("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function compactRupees(value: number): string {
  if (Math.abs(value) >= 10000000) return `₹${(value / 10000000).toFixed(2)} Cr`;
  if (Math.abs(value) >= 100000) return `₹${(value / 100000).toFixed(2)} L`;
  if (Math.abs(value) >= 1000) return `₹${(value / 1000).toFixed(1)}K`;
  return rupees(value);
}

export function qtl(value: number): string {
  return `${value.toLocaleString("en-IN", { maximumFractionDigits: 1 })} qtl`;
}

export function pct(value: number, decimals = 1): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(decimals)}%`;
}

export function plainPct(value: number, decimals = 1): string {
  return `${value.toFixed(decimals)}%`;
}

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}
