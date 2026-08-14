"use client";

import { useState } from "react";
import { CROPS, FRUITS, VEGETABLES, type Crop } from "@/lib/mock/crops";
import { cx } from "@/lib/format";

/** Vegetables and fruits, filtered by category, with the Marathi name under each. */
export default function CropPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (cropId: string) => void;
}) {
  const [tab, setTab] = useState<"vegetable" | "fruit">(
    (CROPS.find((c) => c.id === value)?.category ?? "vegetable") as "vegetable" | "fruit"
  );
  const list: Crop[] = tab === "vegetable" ? VEGETABLES : FRUITS;

  return (
    <div>
      <div className="mb-2.5 flex gap-2">
        {(["vegetable", "fruit"] as const).map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setTab(c)}
            className={cx("segment", tab === c && "segment-active")}
          >
            {c === "vegetable" ? "Vegetables" : "Fruits"}
          </button>
        ))}
      </div>

      <div className="grid max-h-[218px] grid-cols-2 gap-1.5 overflow-y-auto pr-1">
        {list.map((crop) => (
          <button
            key={crop.id}
            type="button"
            onClick={() => onChange(crop.id)}
            className={cx(
              "flex items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left transition",
              value === crop.id
                ? "border-ink bg-ink text-cream"
                : "border-line bg-card hover:border-ink/30"
            )}
          >
            <span className="text-[1.05rem]">{crop.emoji}</span>
            <span className="min-w-0">
              <span className="block truncate text-[0.84rem] font-medium">{crop.name}</span>
              <span
                className={cx(
                  "block truncate text-[0.7rem]",
                  value === crop.id ? "text-cream/65" : "text-muted"
                )}
              >
                {crop.nameMr}
              </span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
