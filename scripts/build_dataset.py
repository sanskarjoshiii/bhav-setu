"""Phase B1 — build the training matrix, and refuse to write a bad one.

    python scripts/build_dataset.py --from 2022-01-01
    python scripts/build_dataset.py --from 2022-01-01 --allow-thin   # inspect only
    python scripts/build_dataset.py --from 2022-01-01 --crops onion tomato

`ml/dataset.py` does the building; this adds the gates PLAN-NOMODEL.md puts on
Phase B1, and the breakdown that tells you *which* series are carrying the set.
That breakdown matters more than the total: 20,000 rows that are 95% onion is
not a multi-crop dataset, it is an onion dataset with decoration, and the pooled
metrics will not reveal that.

The gates, all of them fatal unless --allow-thin:

  * ≥ 20,000 rows
  * no infinite values anywhere
  * no all-NaN feature column
  * every crop present in the matrix has enough rows to be scored separately

Nothing is written unless the gates pass. A bad parquet on disk gets trained on
by someone in a hurry three days later.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime

import _bootstrap  # noqa: F401  (sys.path side effect)

import numpy as np
import pandas as pd

from core.config import settings
from features.registry import FEATURE_NAMES, LABEL_COLUMN
from ml.dataset import MATRIX_PATH, build_training_matrix

TARGET_ROWS: int = 20_000
MIN_ROWS_PER_CROP: int = 200

#: Features that are legitimately NaN for every historical row, so an all-NaN
#: column here is a known property rather than a broken builder.
#:
#: `rain_forecast_7d` is the only one. A 7-day rain forecast genuinely was on the
#: table the morning of a live query, but nobody stored the forecast that was
#: issued on some Tuesday in 2022 — only the rain that actually fell. Filling it
#: from the archive would be leakage dressed up as a feature, so it stays NaN in
#: training and carries a real value only at serving time. See the comment in
#: `features.builder.weather_features`, which made this call deliberately.
EXPECTED_ALL_NAN_IN_HISTORY: frozenset[str] = frozenset({"rain_forecast_7d"})


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _commodity_ids_for(crops: list[str] | None) -> list[int] | None:
    if not crops:
        return None
    from sqlalchemy import text

    from core.db import get_conn

    wanted = {c.strip().lower().replace("_", " ") for c in crops}
    with get_conn() as conn:
        rows = conn.execute(text("SELECT id, name FROM commodities")).all()
    ids = [int(r.id) for r in rows if str(r.name).lower() in wanted]
    if not ids:
        raise SystemExit(f"⛔ none of {sorted(wanted)} are in the commodities table")
    return ids


def _report_composition(matrix: pd.DataFrame) -> None:
    print("\n  rows per crop")
    print("  " + "─" * 54)
    by_crop = matrix.groupby("commodity_id").size().sort_values(ascending=False)
    total = int(by_crop.sum())
    for commodity_id, count in by_crop.items():
        share = count / total * 100
        flag = "  ⚠️ dominates" if share > 60 else ("  ⚠️ too thin" if count < MIN_ROWS_PER_CROP else "")
        print(f"  commodity {int(commodity_id):<4}{count:>9,}{share:>8.1f}%{flag}")

    print("\n  rows per horizon")
    print("  " + "─" * 54)
    for horizon, count in matrix.groupby("horizon").size().items():
        print(f"  h={int(horizon):<6}{count:>9,}")


def _check_gates(matrix: pd.DataFrame, allow_thin: bool) -> int:
    problems: list[str] = []

    if len(matrix) < TARGET_ROWS:
        problems.append(
            f"only {len(matrix):,} rows — the gate is {TARGET_ROWS:,}. "
            f"Run scripts/check_data_readiness.py to see what is missing."
        )

    features = matrix[FEATURE_NAMES]
    infinite = int(np.isinf(features.to_numpy(dtype=float)).sum())
    if infinite:
        problems.append(f"{infinite} infinite value(s) in the feature block")

    all_nan = [c for c in FEATURE_NAMES
               if features[c].isna().all() and c not in EXPECTED_ALL_NAN_IN_HISTORY]
    if all_nan:
        problems.append(f"all-NaN feature column(s): {all_nan}")

    dead = sorted(set(FEATURE_NAMES) & EXPECTED_ALL_NAN_IN_HISTORY
                  & {c for c in FEATURE_NAMES if features[c].isna().all()})
    if dead:
        print(f"\n  ℹ️  always-NaN in history, by design: {dead}")
        print("     A 7-day rain forecast existed on the morning of a live query but was "
              "never stored for past dates, so the model cannot learn from it and will "
              "not split on it. Harmless; see weather_features() in features/builder.py.")

    if matrix[LABEL_COLUMN].isna().any():
        problems.append("the label column contains NaN")

    thin = [int(c) for c, n in matrix.groupby("commodity_id").size().items()
            if n < MIN_ROWS_PER_CROP]
    if thin:
        problems.append(
            f"commodity id(s) {thin} have under {MIN_ROWS_PER_CROP} rows — "
            f"they will be invisible in per-crop metrics"
        )

    # Cheap leakage smoke test: a feature perfectly correlated with the label is
    # almost always a future value that leaked in.
    label = matrix[LABEL_COLUMN].to_numpy(dtype=float)
    for column in FEATURE_NAMES:
        values = features[column].to_numpy(dtype=float)
        mask = np.isfinite(values) & np.isfinite(label)
        if mask.sum() < 100:
            continue
        if abs(float(np.corrcoef(values[mask], label[mask])[0, 1])) > 0.98:
            problems.append(f"feature {column!r} correlates > 0.98 with the label — leakage?")

    if not problems:
        print("\n  ✅ all gates passed")
        return 0

    print("\n  gate failures")
    print("  " + "─" * 54)
    for problem in problems:
        print(f"  ❌ {problem}")
    if allow_thin:
        print("\n  ⚠️  --allow-thin: writing anyway. Do NOT train a promotable model on this.")
        return 0
    print("\n  ⛔ nothing written. Re-run with --allow-thin to inspect it anyway.")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and gate the training matrix.")
    parser.add_argument("--from", dest="start", type=_parse_date, required=True)
    parser.add_argument("--to", dest="end", type=_parse_date, default=date.today())
    parser.add_argument("--horizons", type=int, nargs="+", default=None)
    parser.add_argument("--crops", nargs="+", default=None,
                        help="limit to these crop names (default: all)")
    parser.add_argument("--allow-thin", action="store_true",
                        help="write the matrix even if the gates fail")
    args = parser.parse_args(argv)

    print(f"\nBuilding training matrix  {args.start} → {args.end}")
    print("This walks every (crop, mandi) x business day. It is slow the first time.\n")

    commodity_ids = _commodity_ids_for(args.crops)
    matrix = build_training_matrix(
        args.start, args.end, args.horizons, commodity_ids=commodity_ids, write=False
    )

    if matrix.empty:
        print("⛔ the matrix came out EMPTY.\n")
        print("   This is almost always density, not volume: build_features() needs")
        print(f"   {settings.app.features.min_observations} real observations inside a "
              f"{settings.app.history_lookback_days}-day window.\n")
        print("   Diagnose it:  python scripts/check_data_readiness.py")
        return 1

    print(f"  built     {len(matrix):,} rows x {len(FEATURE_NAMES)} features")
    print(f"  window    {matrix['as_of'].min()} .. {matrix['as_of'].max()}")
    _report_composition(matrix)

    status = _check_gates(matrix, args.allow_thin)
    if status != 0:
        return status

    MATRIX_PATH.parent.mkdir(parents=True, exist_ok=True)
    matrix.to_parquet(MATRIX_PATH, index=False)
    print(f"\n  written to {MATRIX_PATH}")
    print(f"\n  Next:  python scripts/train.py --from {args.start}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
