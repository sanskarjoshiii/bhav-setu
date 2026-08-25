"""Phase A3 — measure the baseline and write the score Phase B3 must beat.

    python scripts/evaluate_baseline.py                 # every usable series
    python scripts/evaluate_baseline.py --crops onion   # just one
    python scripts/evaluate_baseline.py --no-record     # print, store nothing

What it does: walks a held-out tail of each (crop, mandi) series, asks the
provider for a forecast at every horizon using only what existed at that point,
compares against what actually happened, and writes the result to
`model_registry` as the version named in config/model.yaml.

Why it matters more than it looks: this row is the number LightGBM has to beat.
Recording it *now*, before any model exists, is what stops swap day turning into
an argument. A benchmark written down after seeing the model's score is not a
benchmark.

It also records the naive baseline's own score separately, because that — not
the tuned pick — is the benchmark Phase B3 quotes. "Beats the dumbest thing that
works" is a claim we want to make without an asterisk.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from typing import Any, Sequence

import _bootstrap  # noqa: F401  (sys.path side effect)

import numpy as np
from sqlalchemy import text

from core import logging as log
from core.config import settings
from core.db import get_conn
from core.errors import BhavSetuError, InsufficientData
from ml import baselines, metrics
from ml.baseline_provider import BaselineProvider
from ml.port import DEFAULT_HORIZONS

VERSION: str = str(settings.model.baseline.version)

#: fraction of each series held back for scoring. The provider still only ever
#: sees data before each cut-off, so this is about having enough scored points,
#: not about preventing leakage — `rolling_residuals` already guarantees that.
HOLDOUT_FRACTION: float = 0.30
MIN_SCORED_POINTS: int = 20

_SERIES_SQL = text(
    """
    SELECT p.commodity_id, c.name AS commodity, p.mandi_id, m.name AS mandi,
           m.district, count(*) AS n
    FROM price_observations p
    JOIN commodities c ON c.id = p.commodity_id
    JOIN mandis      m ON m.id = p.mandi_id
    WHERE p.modal_price IS NOT NULL
    GROUP BY p.commodity_id, c.name, p.mandi_id, m.name, m.district
    HAVING count(*) >= :min_rows
    ORDER BY c.name, m.name
    """
)

_HISTORY_SQL = text(
    """
    SELECT avg(modal_price)::float8 AS modal_price
    FROM price_observations
    WHERE commodity_id = :commodity_id AND mandi_id = :mandi_id
      AND modal_price IS NOT NULL
    GROUP BY obs_date
    ORDER BY obs_date
    """
)


def _series_to_score(min_rows: int, crops: Sequence[str] | None) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = [dict(r) for r in conn.execute(_SERIES_SQL, {"min_rows": min_rows}).mappings()]
    if crops:
        wanted = {c.strip().lower() for c in crops}
        rows = [r for r in rows if str(r["commodity"]).lower().replace(" ", "_") in wanted
                or str(r["commodity"]).lower() in wanted]
    return rows


def _load_series(commodity_id: int, mandi_id: int) -> np.ndarray:
    with get_conn() as conn:
        rows = conn.execute(
            _HISTORY_SQL, {"commodity_id": commodity_id, "mandi_id": mandi_id}
        ).all()
    return np.asarray([float(r.modal_price) for r in rows], dtype=float)


def score_series(
    provider: BaselineProvider,
    series: np.ndarray,
    horizons: Sequence[int],
) -> dict[int, dict[str, list[float]]]:
    """Rolling-origin predictions over the held-out tail, per horizon.

    Returns raw columns rather than metrics, so the caller can pool every series
    before scoring. Pooling matters: averaging per-series MAPEs would let a
    twelve-row series count as much as a four-hundred-row one.
    """
    collected: dict[int, dict[str, list[float]]] = {
        h: {"truth": [], "p10": [], "p50": [], "p90": [], "now": [], "naive": []}
        for h in horizons
    }
    start = max(int(series.size * (1.0 - HOLDOUT_FRACTION)), 40)

    for horizon in horizons:
        for cut in range(start, series.size - horizon + 1):
            history = series[:cut]
            try:
                band = provider.forecast_series(history, [horizon])[horizon]
            except (InsufficientData, ValueError):
                continue
            bucket = collected[horizon]
            bucket["truth"].append(float(series[cut + horizon - 1]))
            bucket["now"].append(float(history[-1]))
            bucket["p10"].append(band.p10)
            bucket["p50"].append(band.p50)
            bucket["p90"].append(band.p90)
            bucket["naive"].append(baselines.naive(history, horizon))
    return collected


def _merge(into: dict[int, dict[str, list[float]]],
           other: dict[int, dict[str, list[float]]]) -> None:
    for horizon, columns in other.items():
        for key, values in columns.items():
            into.setdefault(horizon, {}).setdefault(key, []).extend(values)


def _score(pooled: dict[int, dict[str, list[float]]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for horizon, columns in sorted(pooled.items()):
        if len(columns["truth"]) < MIN_SCORED_POINTS:
            log.warn("baseline_horizon_thin", horizon=horizon, scored=len(columns["truth"]))
            continue
        scored = metrics.score_horizon(
            columns["truth"], columns["p10"], columns["p50"], columns["p90"],
            price_now=columns["now"],
        )
        # The benchmark Phase B3 quotes, scored on exactly the same rows.
        benchmark = metrics.pinball_loss(columns["truth"], columns["naive"], 0.50)
        scored["benchmark_naive_pinball_p50"] = benchmark
        scored["skill_vs_naive"] = metrics.skill_score(scored["pinball_p50"], benchmark)
        # NaN is a legitimate answer — directional accuracy is undefined for a
        # method that never calls a direction — but `json.dumps` writes it as a
        # bare NaN token and Postgres rejects that from jsonb. Null says the same
        # thing in a form the column will accept.
        out[f"h{horizon}"] = {
            key: (round(float(value), 4) if np.isfinite(value) else None)
            for key, value in scored.items()
        }
    return out


def record(version: str, payload: dict[str, Any], train_start: date | None,
           train_end: date | None) -> None:
    """Upsert the row. Not marked active — `provider:` in model.yaml decides that."""
    with get_conn() as conn:
        conn.execute(
            text(
                """
                INSERT INTO model_registry
                    (version, trained_at, train_start, train_end, algo, params, metrics)
                VALUES (:version, :trained_at, :train_start, :train_end, :algo,
                        CAST(:params AS jsonb), CAST(:metrics AS jsonb))
                ON CONFLICT (version) DO UPDATE SET
                    trained_at  = EXCLUDED.trained_at,
                    train_start = EXCLUDED.train_start,
                    train_end   = EXCLUDED.train_end,
                    algo        = EXCLUDED.algo,
                    params      = EXCLUDED.params,
                    metrics     = EXCLUDED.metrics
                """
            ),
            {
                "version": version,
                "trained_at": datetime.now(timezone.utc),
                "train_start": train_start,
                "train_end": train_end,
                "algo": "baselines:" + ",".join(sorted(baselines.METHODS)),
                "params": json.dumps(settings.model.baseline.to_dict(), default=str),
                "metrics": json.dumps(payload, default=str),
            },
        )


def _print(payload: dict[str, Any], series_count: int) -> None:
    print(f"\n  baseline {VERSION} — {series_count} series\n")
    print(f"  {'h':>3}  {'scored':>7}  {'MAPE%':>7}  {'PICP':>6}  {'width':>6}  "
          f"{'dir.acc':>7}  {'pinball':>8}  {'vs naive':>9}")
    print(f"  {'─'*3}  {'─'*7}  {'─'*7}  {'─'*6}  {'─'*6}  {'─'*7}  {'─'*8}  {'─'*9}")
    for key, row in payload.items():
        skill = row.get("skill_vs_naive")
        flag = "" if skill is None or skill >= 0 else "  ⛔ worse than naive"
        # "no call" is not "always wrong": a flat forecast has no direction.
        direction = row.get("directional_accuracy")
        direction_text = "  n/a  " if direction is None else f"{direction:>7.3f}"
        print(
            f"  {key[1:]:>3}  {int(row['n_scored']):>7}  {row['mape']:>7.2f}  "
            f"{row['picp']:>6.3f}  {row['interval_width_rel']:>6.3f}  "
            f"{direction_text}  {row['pinball_p50']:>8.2f}  "
            f"{'      n/a' if skill is None else format(skill, '>+9.3f')}{flag}"
        )
    print(
        "\n  PICP is the honesty column: 0.80 is the target for a p10-p90 band.\n"
        "  'vs naive' is the number Phase B3 makes LightGBM beat.\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score the baseline forecaster.")
    parser.add_argument("--crops", nargs="+", metavar="CROP", help="only these crops")
    parser.add_argument("--min-rows", type=int, default=80,
                        help="skip series thinner than this (default 80)")
    parser.add_argument("--no-record", action="store_true",
                        help="print the table but do not write model_registry")
    args = parser.parse_args(argv)

    series_rows = _series_to_score(args.min_rows, args.crops)
    if not series_rows:
        print(
            f"\n⛔ no (crop, mandi) series has {args.min_rows}+ observations yet.\n"
            f"   The baseline cannot be scored before there is history to score it on.\n"
            f"   Run `make collect` daily, or lower --min-rows to inspect what exists.\n",
            file=sys.stderr,
        )
        return 2

    provider = BaselineProvider()
    pooled: dict[int, dict[str, list[float]]] = {}
    used = 0
    for row in series_rows:
        series = _load_series(int(row["commodity_id"]), int(row["mandi_id"]))
        if series.size < args.min_rows:
            continue
        _merge(pooled, score_series(provider, series, DEFAULT_HORIZONS))
        used += 1
        log.info("baseline_scored", commodity=row["commodity"], mandi=row["mandi"],
                 district=row["district"], rows=int(series.size))

    payload = _score(pooled)
    if not payload:
        print(
            "\n⛔ not enough scored points at any horizon. More history is needed "
            "before this number means anything.\n",
            file=sys.stderr,
        )
        return 2

    payload["series_scored"] = used
    _print({k: v for k, v in payload.items() if k.startswith("h")}, used)

    if args.no_record:
        print("  (--no-record: model_registry not written)\n")
        return 0

    with get_conn() as conn:
        span = conn.execute(
            text("SELECT min(obs_date) AS lo, max(obs_date) AS hi FROM price_observations")
        ).mappings().first()
    record(VERSION, payload, span["lo"] if span else None, span["hi"] if span else None)
    print(f"  recorded as model_registry.version = {VERSION}\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BhavSetuError as exc:
        print(f"⛔ {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
