"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import type { Grade, RiskProfile, Storage } from "@/lib/types";
import type { LotInput } from "@/lib/api";
import { cropById } from "@/lib/mock/crops";
import { cx } from "@/lib/format";
import CropPicker from "./CropPicker";

const GRADES: { value: Grade; label: string; hint: string }[] = [
  { value: "A", label: "A", hint: "Large, clean, well cured" },
  { value: "B", label: "B", hint: "Average size, some spotting" },
  { value: "C", label: "C", hint: "Small or damaged" },
];

const STORAGES: { value: Storage; label: string; hint: string }[] = [
  { value: "ambient", label: "Open / ambient", hint: "No protection" },
  { value: "shed", label: "Shed", hint: "Ventilated shed" },
  { value: "cold_store", label: "Cold store", hint: "Rented cold storage" },
];

const RISKS: { value: RiskProfile; label: string; hint: string }[] = [
  { value: "cautious", label: "Cautious", hint: "I cannot afford a bad month" },
  { value: "balanced", label: "Balanced", hint: "Some risk is fine" },
  { value: "aggressive", label: "Aggressive", hint: "I can wait for a better price" },
];

export default function LotForm({
  initial,
  onSubmit,
  loading,
}: {
  initial: LotInput;
  onSubmit: (lot: LotInput) => void;
  loading?: boolean;
}) {
  const [cropId, setCropId] = useState(initial.cropId);
  const [qty, setQty] = useState(String(initial.qtyQtl));
  const [grade, setGrade] = useState<Grade>(initial.grade);
  const [storage, setStorage] = useState<Storage>(initial.storage);
  const [risk, setRisk] = useState<RiskProfile>(initial.risk);

  useEffect(() => setCropId(initial.cropId), [initial.cropId]);

  const crop = cropById(cropId);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ cropId, qtyQtl: Math.max(1, Number(qty) || 1), grade, storage, risk });
      }}
      className="card p-6"
    >
      <h2 className="h3">Your lot</h2>
      <p className="mt-1 text-[0.85rem] text-muted">
        Vinchur, Nashik. Change anything and the advice recalculates.
      </p>

      <div className="mt-6 space-y-6">
        <div>
          <p className="label">Crop</p>
          <CropPicker value={cropId} onChange={setCropId} />
          <p className="mt-2 text-[0.76rem] text-muted">
            {crop.season} · shelf life {crop.shelfLifeDays} days · we never advise holding{" "}
            {crop.name.toLowerCase()} beyond {crop.maxHoldDays} days.
          </p>
        </div>

        <div>
          <label className="label" htmlFor="qty">
            Quantity (quintals)
          </label>
          <input
            id="qty"
            inputMode="decimal"
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            className="input"
          />
        </div>

        <div>
          <p className="label">Grade</p>
          <div className="flex gap-2">
            {GRADES.map((g) => (
              <button
                type="button"
                key={g.value}
                onClick={() => setGrade(g.value)}
                title={g.hint}
                className={cx("segment", grade === g.value && "segment-active")}
              >
                {g.label}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[0.76rem] text-muted">
            {GRADES.find((g) => g.value === grade)?.hint}
          </p>
        </div>

        <div>
          <p className="label">Storage</p>
          <div className="grid gap-2">
            {STORAGES.map((s) => (
              <button
                type="button"
                key={s.value}
                onClick={() => setStorage(s.value)}
                className={cx(
                  "flex items-center justify-between rounded-xl border px-4 py-3 text-left transition",
                  storage === s.value
                    ? "border-ink bg-ink text-cream"
                    : "border-line bg-card hover:border-ink/30"
                )}
              >
                <span className="text-[0.9rem] font-medium">{s.label}</span>
                <span
                  className={cx(
                    "text-[0.74rem]",
                    storage === s.value ? "text-cream/70" : "text-muted"
                  )}
                >
                  {s.hint}
                </span>
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="label">How much risk can you take?</p>
          <div className="flex gap-2">
            {RISKS.map((r) => (
              <button
                type="button"
                key={r.value}
                onClick={() => setRisk(r.value)}
                className={cx("segment", risk === r.value && "segment-active")}
              >
                {r.label}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[0.76rem] text-muted">
            {RISKS.find((r) => r.value === risk)?.hint}
          </p>
        </div>
      </div>

      <button type="submit" disabled={loading} className="btn-primary mt-7 w-full">
        {loading && <Loader2 size={15} className="animate-spin" />}
        {loading ? "Working it out…" : `Get advice for ${crop.name.toLowerCase()}`}
      </button>
    </form>
  );
}
