"use client";

import { Package, Plus } from "lucide-react";
import PageHeader from "@/components/PageHeader";
import Section from "@/components/Section";
import { cx, qtl } from "@/lib/format";

/** TODO (Phase 8): GET /api/v1/lots. Seeded for the demo. */
const LOTS = [
  {
    id: "LOT-2026-0041",
    crop: "Onion",
    qty: 80,
    remaining: 30,
    grade: "B",
    storage: "Shed",
    harvest: "28 July 2026",
    status: "partially_sold",
  },
  {
    id: "LOT-2026-0038",
    crop: "Onion",
    qty: 45,
    remaining: 0,
    grade: "A",
    storage: "Cold store",
    harvest: "12 July 2026",
    status: "closed",
  },
  {
    id: "LOT-2026-0033",
    crop: "Onion",
    qty: 120,
    remaining: 120,
    grade: "C",
    storage: "Ambient",
    harvest: "02 August 2026",
    status: "open",
  },
];

const TONE = {
  open: "bg-up/10 text-up",
  partially_sold: "bg-ink/10 text-ink",
  closed: "bg-muted/15 text-muted",
} as const;

export default function LotsPage() {
  return (
    <>
      <PageHeader
        eyebrow="My lots"
        title="What you have in store"
        lede="Each lot tracks what you harvested, what is left, and what we advised."
      >
        <button className="btn-primary">
          <Plus size={16} /> Add a lot
        </button>
      </PageHeader>

      <Section>
        <div className="grid gap-3 md:grid-cols-3">
          {LOTS.map((l) => (
            <div key={l.id} className="card p-6">
              <div className="flex items-start justify-between">
                <span className="grid h-10 w-10 place-items-center rounded-full bg-panel">
                  <Package size={18} />
                </span>
                <span
                  className={cx(
                    "rounded-full px-2.5 py-1 text-[0.7rem] font-medium capitalize",
                    TONE[l.status as keyof typeof TONE]
                  )}
                >
                  {l.status.replace("_", " ")}
                </span>
              </div>

              <h3 className="h3 mt-4">
                {l.crop} · grade {l.grade}
              </h3>
              <p className="mt-1 font-mono text-[0.75rem] text-muted">{l.id}</p>

              <dl className="mt-5 space-y-2 text-[0.86rem]">
                {[
                  ["Harvested", l.harvest],
                  ["Quantity", qtl(l.qty)],
                  ["Remaining", qtl(l.remaining)],
                  ["Storage", l.storage],
                ].map(([k, v]) => (
                  <div key={k} className="flex justify-between">
                    <dt className="text-muted">{k}</dt>
                    <dd className="font-medium">{v}</dd>
                  </div>
                ))}
              </dl>

              <div className="mt-5 h-1.5 w-full overflow-hidden rounded-full bg-line">
                <div
                  className="h-full rounded-full bg-ink"
                  style={{ width: `${((l.qty - l.remaining) / l.qty) * 100}%` }}
                />
              </div>
              <p className="mt-2 text-[0.74rem] text-muted">{qtl(l.qty - l.remaining)} sold</p>
            </div>
          ))}
        </div>
      </Section>
    </>
  );
}
