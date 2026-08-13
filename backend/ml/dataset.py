"""Phase 3.4 — build the training matrix from the shared feature builder.

    python -m ml.dataset --from 2022-01-01 --to 2025-06-30

One row per (mandi, commodity, business day, horizon):

    features from build_features(as_of=D)   +   y = log(price[D+h] / price[D])

The features come from the same `build_features()` the live API calls. If this
file ever grows its own feature logic, the backtest becomes fiction.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from core import logging as log
from core.config import settings
from core.db import get_conn
from core.errors import InsufficientData
from features.builder import HistoryCache, build_features
from features.registry import FEATURE_NAMES, LABEL_COLUMN, META_COLUMNS

_DS = settings.model.dataset
LABEL_TOLERANCE_DAYS: int = int(_DS.label_tolerance_days)
MATRIX_PATH: Path = settings.path(*str(_DS.matrix_path).split("/"))
HORIZONS: list[int] = [int(h) for h in settings.app.horizons]


@dataclass
class BuildStats:
    """Why rows disappeared. Printed at the end so nothing vanishes silently."""

    days_attempted: int = 0
    feature_rows: int = 0
    insufficient_data: int = 0
    label_missing: int = 0
    rows: int = 0
    per_mandi: dict[int, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "days_attempted": self.days_attempted,
            "feature_rows": self.feature_rows,
            "skipped_insufficient_data": self.insufficient_data,
            "skipped_label_missing": self.label_missing,
            "rows": self.rows,
            "rows_per_mandi": self.per_mandi,
        }


def _commodity_ids(conn: Connection) -> list[int]:
    return [int(i) for i in conn.execute(
        text("SELECT id FROM commodities ORDER BY id")
    ).scalars().all()]


def _label_lookup(series: pd.DataFrame) -> tuple[pd.DatetimeIndex, np.ndarray]:
    """Dates and modal prices of *real* observations, for settling labels.

    Imputed rows are excluded: a label is what the market actually did, and
    training on a forward-filled price teaches the model that nothing happened.
    """
    real = series[~series["is_imputed"].astype(bool)]
    return pd.DatetimeIndex(real["obs_date"]), real["modal_price"].to_numpy(dtype=float)


def _price_at(index: pd.DatetimeIndex, values: np.ndarray,
              target: pd.Timestamp, tolerance_days: int) -> tuple[float, pd.Timestamp] | None:
    """Most recent real price in [target - tolerance, target]. None if there is none."""
    if len(index) == 0:
        return None
    position = int(index.searchsorted(target, side="right")) - 1
    if position < 0:
        return None
    found = index[position]
    if (target - found).days > tolerance_days:
        return None
    return float(values[position]), found


def build_training_matrix(start: date, end: date, horizons: list[int] | None = None,
                          commodity_ids: Iterable[int] | None = None,
                          write: bool = True) -> pd.DataFrame:
    """Every (mandi, commodity) x business day x horizon, labelled and cached."""
    horizons = list(horizons or HORIZONS)
    stats = BuildStats()
    calendar = pd.bdate_range(start, end)
    records: list[dict[str, Any]] = []

    with get_conn() as conn:
        wanted = list(commodity_ids) if commodity_ids is not None else _commodity_ids(conn)
        for commodity_id in wanted:
            cache = HistoryCache.load(conn, commodity_id)
            for mandi_id in cache.mandi_ids:
                series = cache.price_series(mandi_id)
                if series.empty:
                    continue
                index, values = _label_lookup(series)

                for as_of in calendar:
                    stats.days_attempted += 1
                    try:
                        features = build_features(
                            as_of.date(), mandi_id, commodity_id, conn, cache=cache
                        )
                    except InsufficientData:
                        stats.insufficient_data += 1
                        continue
                    stats.feature_rows += 1

                    now = _price_at(index, values, as_of, LABEL_TOLERANCE_DAYS)
                    if now is None:
                        stats.label_missing += len(horizons)
                        continue
                    price_now, _ = now

                    for horizon in horizons:
                        target = as_of + pd.Timedelta(days=horizon)
                        later = _price_at(index, values, target, LABEL_TOLERANCE_DAYS)
                        if later is None or later[0] <= 0 or price_now <= 0:
                            stats.label_missing += 1
                            continue
                        price_target, settled_on = later
                        records.append(
                            {
                                **features,
                                "as_of": as_of.date(),
                                "horizon": horizon,
                                "target_date": settled_on.date(),
                                "price_now": price_now,
                                "price_target": price_target,
                                LABEL_COLUMN: float(np.log(price_target / price_now)),
                            }
                        )
                        stats.per_mandi[mandi_id] = stats.per_mandi.get(mandi_id, 0) + 1

    matrix = pd.DataFrame(records, columns=[*FEATURE_NAMES, *META_COLUMNS])
    matrix = matrix.replace([np.inf, -np.inf], np.nan)
    matrix = matrix[matrix[LABEL_COLUMN].notna()].reset_index(drop=True)
    stats.rows = int(len(matrix))

    log.info("training_matrix_built", start=str(start), end=str(end),
             horizons=horizons, **stats.to_dict())

    if write:
        MATRIX_PATH.parent.mkdir(parents=True, exist_ok=True)
        matrix.to_parquet(MATRIX_PATH, index=False)
        log.info("training_matrix_cached", path=str(MATRIX_PATH), rows=len(matrix))
    return matrix


def load_cached() -> pd.DataFrame:
    """Read the parquet written by the last build. Raises if it is not there."""
    if not MATRIX_PATH.exists():
        raise InsufficientData(
            f"no training matrix at {MATRIX_PATH}. Run: python -m ml.dataset --from <date>"
        )
    return pd.read_parquet(MATRIX_PATH)


def load_or_build(start: date, end: date, horizons: list[int] | None = None,
                  refresh: bool = False) -> pd.DataFrame:
    """Reuse the cached matrix when it already covers the requested window."""
    horizons = list(horizons or HORIZONS)
    if not refresh and MATRIX_PATH.exists():
        cached = pd.read_parquet(MATRIX_PATH)
        covered = (
            not cached.empty
            and pd.Timestamp(cached["as_of"].min()) <= pd.Timestamp(start)
            and pd.Timestamp(cached["as_of"].max()) >= pd.Timestamp(end) - pd.Timedelta(days=7)
            and set(horizons) <= set(int(h) for h in cached["horizon"].unique())
        )
        if covered:
            log.info("training_matrix_reused", path=str(MATRIX_PATH), rows=len(cached))
            return cached
    return build_training_matrix(start, end, horizons)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Phase 3 training matrix.")
    parser.add_argument("--from", dest="start", type=_parse_date, required=True)
    parser.add_argument("--to", dest="end", type=_parse_date, default=date.today())
    parser.add_argument("--horizons", type=int, nargs="+", default=None)
    args = parser.parse_args(argv)

    matrix = build_training_matrix(args.start, args.end, args.horizons)
    if matrix.empty:
        print("⛔ training matrix is empty — check the audit report first", file=sys.stderr)
        return 1

    print(
        f"\n✅ training matrix\n"
        f"   rows      {len(matrix):,}\n"
        f"   features  {len(FEATURE_NAMES)}\n"
        f"   range     {matrix['as_of'].min()} .. {matrix['as_of'].max()}\n"
        f"   horizons  {sorted(matrix['horizon'].unique())}\n"
        f"   cached to {MATRIX_PATH}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
