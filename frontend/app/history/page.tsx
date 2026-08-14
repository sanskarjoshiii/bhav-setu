"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight, RotateCcw, Search, Trash2 } from "lucide-react";
import PageHeader from "@/components/PageHeader";
import Section from "@/components/Section";
import StatCard from "@/components/StatCard";
import { useHistory, type HistoryEntry } from "@/lib/history";
import { cx, qtl, rupees } from "@/lib/format";

const ACTION_LABEL: Record<string, string> = {
  sell_now: "Sell now",
  hold: "Hold",
  split: "Split",
  sell_to_procurement: "Procurement",
};

function when(iso: string): string {
  const d = new Date(iso);
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hour${hours > 1 ? "s" : ""} ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} day${days > 1 ? "s" : ""} ago`;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export default function HistoryPage() {
  const { entries, remove, clear } = useHistory();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  const filtered = query.trim()
    ? entries.filter(
        (e) =>
          e.cropName.toLowerCase().includes(query.toLowerCase()) ||
          e.mandi.toLowerCase().includes(query.toLowerCase())
      )
    : entries;

  const totalGain = entries.reduce((sum, e) => sum + e.expectedGain, 0);
  const crops = new Set(entries.map((e) => e.cropId)).size;

  return (
    <>
      <PageHeader
        eyebrow="History"
        title="Everything you have asked us"
        lede="Every lot you checked, what we advised, and what it was worth. Open any one to see the full recommendation again."
      >
        {entries.length > 0 && (
          <button onClick={clear} className="btn-ghost">
            <Trash2 size={15} />
            Clear history
          </button>
        )}
      </PageHeader>

      <Section>
        <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Searches" value={String(entries.length)} hint="Saved on this device" />
          <StatCard label="Crops checked" value={String(crops)} hint="Vegetables and fruits" />
          <StatCard
            label="Total expected gain"
            value={rupees(totalGain)}
            hint="Versus selling immediately"
            tone="up"
          />
          <StatCard
            label="Last search"
            value={entries[0] ? entries[0].cropName : "—"}
            hint={entries[0] ? when(entries[0].at) : "Nothing yet"}
          />
        </div>

        <label className="relative mb-5 flex max-w-md items-center">
          <Search size={15} className="pointer-events-none absolute left-3.5 text-muted" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter by crop or mandi…"
            className="input pl-10"
          />
        </label>

        {filtered.length === 0 ? (
          <div className="card grid place-items-center py-20 text-center">
            <div>
              <p className="h3">Nothing here yet</p>
              <p className="lede mx-auto mt-2 max-w-sm">
                Ask the Advisor about a lot and it will show up here automatically.
              </p>
              <Link href="/advisor" className="btn-primary mt-6">
                Get selling advice
              </Link>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {filtered.map((e) => (
              <HistoryRow
                key={e.id}
                entry={e}
                open={open === e.id}
                onToggle={() => setOpen(open === e.id ? null : e.id)}
                onRemove={() => remove(e.id)}
              />
            ))}
          </div>
        )}
      </Section>
    </>
  );
}

function HistoryRow({
  entry,
  open,
  onToggle,
  onRemove,
}: {
  entry: HistoryEntry;
  open: boolean;
  onToggle: () => void;
  onRemove: () => void;
}) {
  return (
    <div className={cx("card overflow-hidden transition", open && "ring-1 ring-ink/10")}>
      <button onClick={onToggle} className="flex w-full items-center gap-4 p-5 text-left">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-panel text-[1.2rem]">
          {entry.cropEmoji}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[0.98rem] font-semibold">{entry.cropName}</p>
            <span className="chip">{qtl(entry.qtyQtl)}</span>
            <span className="chip">Grade {entry.grade}</span>
            <span
              className={cx(
                "rounded-full px-2.5 py-0.5 text-[0.7rem] font-semibold",
                entry.action === "sell_now"
                  ? "bg-down/10 text-down"
                  : entry.action === "hold"
                  ? "bg-up/10 text-up"
                  : "bg-ink/10 text-ink"
              )}
            >
              {ACTION_LABEL[entry.action] ?? entry.action}
            </span>
          </div>
          <p className="mt-1 truncate text-[0.85rem] text-muted">{entry.headline}</p>
        </div>

        <div className="hidden shrink-0 text-right sm:block">
          <p className="text-[0.98rem] font-bold tabular-nums">{rupees(entry.netPerQtl)}/qtl</p>
          <p className="text-[0.75rem] text-muted">{when(entry.at)}</p>
        </div>
      </button>

      {open && (
        <div className="border-t border-line bg-panel/30 px-5 py-5">
          <div className="grid gap-5 sm:grid-cols-4">
            {[
              ["Mandi", entry.mandi],
              ["Storage", entry.storage.replace("_", " ")],
              ["Risk profile", entry.risk],
              ["Confidence", `${Math.round(entry.confidence * 100)}%`],
              ["Net per quintal", rupees(entry.netPerQtl)],
              ["Expected gain", rupees(entry.expectedGain)],
              ["Quantity", qtl(entry.qtyQtl)],
              ["Reference", entry.id],
            ].map(([k, v]) => (
              <div key={k}>
                <p className="stat-label">{k}</p>
                <p className="mt-1 text-[0.9rem] font-medium capitalize">{v}</p>
              </div>
            ))}
          </div>

          <div className="mt-5 flex flex-wrap gap-2">
            <Link href={`/advisor?crop=${entry.cropId}`} className="btn-primary">
              <RotateCcw size={15} />
              Run this again
            </Link>
            <Link href="/compare" className="btn-ghost">
              Compare mandis
              <ArrowUpRight size={15} />
            </Link>
            <button onClick={onRemove} className="btn-quiet ml-auto text-down">
              <Trash2 size={15} />
              Remove
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
