"""Phase B2 — train the 12 quantile boosters, honestly.

    from ml.trainer import train
    report = train(matrix, horizons=[1, 3, 7, 15])

Twelve LightGBM models: 3 quantiles (p10/p50/p90) x 4 horizons. **One global
model per (horizon, quantile), not one per crop** — `commodity_id` and
`mandi_id` are categorical features, which is what lets a crop with 200 rows
borrow strength from a crop with 20,000. Thirteen separate models would leave
the thin crops untrainable, and the thin crops are most of the product.

Three things in here are load-bearing, and skipping any one of them produces a
model that scores beautifully and is worthless:

  1. **The purge gap.** A label at time T contains the price at T+h. Training on
     rows whose labels overlap the validation window leaks the future backwards.
     Every fold drops `h` days between train end and validation start.

  2. **The label is a log return, not a price.** `dataset.py` builds
     `y = log(p[D+h] / p[D])`. Predicting the level lets a model score well by
     memorising that onion costs about ₹2,000, which teaches it nothing about
     what onion is going to *do*.

  3. **The baselines are scored on the identical folds, in the same units.**
     Not looked up from a remembered number — recomputed here, on exactly the
     rows the model was validated on. Boosters are fitted on the log return but
     every metric is computed in ₹/quintal, because that is what
     `evaluate_baseline.py` writes to `model_registry` and a gate comparing two
     different scales is worse than no gate.

Quantile crossing is handled at serving time, in `lgbm_provider`, because it is
a property of the three independent fits and cannot be prevented here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterator, Mapping, Sequence

import lightgbm as lgb
import numpy as np
import pandas as pd

from core import logging as log
from core.config import settings
from core.errors import InsufficientData
from features.registry import CATEGORICAL_FEATURES, FEATURE_NAMES, LABEL_COLUMN
from ml import metrics as M
from ml.port import to_price
from ml.registry import QUANTILES

_PARAMS = settings.model.lightgbm.to_dict()
_VALIDATION = settings.model.validation
N_FOLDS: int = int(_VALIDATION.n_folds)
FOLD_MONTHS: int = int(_VALIDATION.fold_months)
PURGE_EQUALS_HORIZON: bool = bool(_VALIDATION.purge_days_equal_horizon)
HORIZONS: list[int] = [int(h) for h in settings.app.horizons]

#: Below this many training rows in a fold, a booster is noise. We skip the fold
#: rather than fit something we would then have to explain.
MIN_FOLD_TRAIN_ROWS: int = 200
MIN_FOLD_VALID_ROWS: int = 30


# ══════════════════════════════════════════════════════════════════════════
# folds
# ══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Fold:
    """One walk-forward split, with the purge gap already applied."""

    index: int
    train_end: pd.Timestamp
    valid_start: pd.Timestamp
    valid_end: pd.Timestamp

    def describe(self) -> str:
        return (f"fold {self.index}: train ≤ {self.train_end.date()} │ "
                f"valid {self.valid_start.date()} → {self.valid_end.date()}")


def make_folds(as_of: pd.Series, horizon: int, n_folds: int = N_FOLDS,
               fold_months: int = FOLD_MONTHS) -> list[Fold]:
    """Walk-forward folds over the tail of the data, newest fold last.

    The purge gap is the whole point of this function. With
    `purge_days_equal_horizon: true`, training data stops `h` days before the
    validation window opens, so no training label can have been settled by a
    price that falls inside validation.
    """
    stamps = pd.to_datetime(pd.Series(as_of)).sort_values()
    if stamps.empty:
        return []
    last = stamps.iloc[-1]
    purge = pd.Timedelta(days=horizon if PURGE_EQUALS_HORIZON else 0)
    width = pd.DateOffset(months=fold_months)

    folds: list[Fold] = []
    for i in range(n_folds):
        valid_end = last - pd.DateOffset(months=fold_months * (n_folds - 1 - i))
        valid_start = valid_end - width
        folds.append(
            Fold(index=i + 1, train_end=valid_start - purge,
                 valid_start=valid_start, valid_end=valid_end)
        )
    return folds


def split(matrix: pd.DataFrame, fold: Fold) -> tuple[pd.DataFrame, pd.DataFrame]:
    as_of = pd.to_datetime(matrix["as_of"])
    train = matrix[as_of <= fold.train_end]
    valid = matrix[(as_of > fold.valid_start) & (as_of <= fold.valid_end)]
    return train, valid


# ══════════════════════════════════════════════════════════════════════════
# fitting
# ══════════════════════════════════════════════════════════════════════════

def _matrices(frame: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    features = frame[FEATURE_NAMES].astype(float)
    for column in CATEGORICAL_FEATURES:
        features[column] = features[column].fillna(-1).astype(int).astype("category")
    return features, frame[LABEL_COLUMN].to_numpy(dtype=float)


def _params_for(alpha: float) -> dict[str, Any]:
    """LightGBM params for one quantile. `num_boost_round` is not a param."""
    params = {k: v for k, v in _PARAMS.items()
              if k not in {"num_boost_round", "early_stopping_rounds"}}
    params.update(
        objective="quantile",
        alpha=float(alpha),
        metric="quantile",
        verbosity=-1,
        seed=42,
        deterministic=True,
    )
    return params


def fit_booster(train: pd.DataFrame, valid: pd.DataFrame, alpha: float) -> lgb.Booster:
    """One booster, early-stopped on the fold's own validation slice."""
    x_train, y_train = _matrices(train)
    x_valid, y_valid = _matrices(valid)
    train_set = lgb.Dataset(x_train, label=y_train,
                            categorical_feature=CATEGORICAL_FEATURES, free_raw_data=False)
    valid_set = lgb.Dataset(x_valid, label=y_valid, reference=train_set,
                            categorical_feature=CATEGORICAL_FEATURES, free_raw_data=False)
    return lgb.train(
        _params_for(alpha),
        train_set,
        num_boost_round=int(_PARAMS.get("num_boost_round", 800)),
        valid_sets=[valid_set],
        callbacks=[
            lgb.early_stopping(int(_PARAMS.get("early_stopping_rounds", 60)), verbose=False),
            lgb.log_evaluation(period=0),
        ],
    )


# ══════════════════════════════════════════════════════════════════════════
# the baselines, on the same rows
# ══════════════════════════════════════════════════════════════════════════

def baseline_predictions(train: pd.DataFrame, valid: pd.DataFrame) -> dict[str, np.ndarray]:
    """The naive benchmark, in ₹/quintal — the same units the model is scored in.

    `naive` says "the price will not move", so p50 is today's price. The band is
    the empirical spread of the training returns applied to it, which is the
    same idea `baseline_provider` uses at serving time: quote how wrong this
    method has actually been rather than assuming a bell curve.

    Everything here is a price, deliberately. `evaluate_baseline.py` records
    `baseline-v1` in ₹/quintal, and a gate that compared a ₹-scale pinball loss
    against a return-scale one would hand the model a 99% "win" that means
    nothing at all.
    """
    y_train = train[LABEL_COLUMN].to_numpy(dtype=float)
    finite = y_train[np.isfinite(y_train)]
    if finite.size == 0:
        finite = np.zeros(1)
    price_now = valid["price_now"].to_numpy(dtype=float)
    lo, hi = float(np.quantile(finite, 0.10)), float(np.quantile(finite, 0.90))
    return {
        "p50": price_now.copy(),
        "p10": price_now * np.exp(min(lo, 0.0)),
        "p90": price_now * np.exp(max(hi, 0.0)),
    }


def _predictions_to_price(price_now: np.ndarray, log_returns: np.ndarray) -> np.ndarray:
    """Vectorised `to_price`, so training metrics use the serving conversion."""
    return np.asarray(
        [to_price(float(p), float(r)) for p, r in zip(price_now, log_returns)],
        dtype=float,
    )


# ══════════════════════════════════════════════════════════════════════════
# the run
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class TrainReport:
    """Everything the run learned. Printed in full; written to model_registry."""

    horizons: list[int]
    model_metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    baseline_metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    per_crop: dict[str, dict[str, float]] = field(default_factory=dict)
    fold_notes: list[str] = field(default_factory=list)
    rows_trained: int = 0
    train_start: date | None = None
    train_end: date | None = None

    def skill(self, horizon: int) -> float:
        return M.skill_score(
            self.model_metrics.get(f"h{horizon}", {}).get("pinball_mean", float("nan")),
            self.baseline_metrics.get(f"h{horizon}", {}).get("pinball_mean", float("nan")),
        )

    def to_metrics(self) -> dict[str, Any]:
        return {
            "horizons": self.horizons,
            "rows_trained": self.rows_trained,
            **{k: v for k, v in self.model_metrics.items()},
            "baseline": self.baseline_metrics,
            "per_crop": self.per_crop,
        }


def _pooled(frames: Sequence[dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    if not frames:
        return {}
    return {key: np.concatenate([f[key] for f in frames]) for key in frames[0]}


def train(
    matrix: pd.DataFrame,
    horizons: Sequence[int] | None = None,
    *,
    n_folds: int = N_FOLDS,
) -> tuple[dict[tuple[int, str], lgb.Booster], TrainReport]:
    """Fit every (horizon, quantile), validate walk-forward, score the benchmark.

    Returns the boosters keyed by `(horizon, quantile_key)` — refit on all data
    up to the last fold's train end — and the report.
    """
    horizons = [int(h) for h in (horizons or HORIZONS)]
    if matrix.empty:
        raise InsufficientData("training matrix is empty — run scripts/build_dataset.py")

    report = TrainReport(horizons=horizons, rows_trained=int(len(matrix)))
    as_of_all = pd.to_datetime(matrix["as_of"])
    report.train_start, report.train_end = as_of_all.min().date(), as_of_all.max().date()

    boosters: dict[tuple[int, str], lgb.Booster] = {}

    for horizon in horizons:
        slice_ = matrix[matrix["horizon"] == horizon].copy()
        if slice_.empty:
            report.fold_notes.append(f"h={horizon}: no rows, skipped")
            continue

        folds = make_folds(slice_["as_of"], horizon, n_folds=n_folds)
        model_pools: list[dict[str, np.ndarray]] = []
        base_pools: list[dict[str, np.ndarray]] = []
        last_usable: Fold | None = None

        for fold in folds:
            train_part, valid_part = split(slice_, fold)
            if len(train_part) < MIN_FOLD_TRAIN_ROWS or len(valid_part) < MIN_FOLD_VALID_ROWS:
                report.fold_notes.append(
                    f"h={horizon} {fold.describe()} — skipped "
                    f"(train {len(train_part)}, valid {len(valid_part)})"
                )
                continue
            last_usable = fold
            report.fold_notes.append(
                f"h={horizon} {fold.describe()} — train {len(train_part):,}, "
                f"valid {len(valid_part):,}"
            )

            price_now = valid_part["price_now"].to_numpy(dtype=float)
            x_valid, _ = _matrices(valid_part)

            # Predict the log return, then convert to ₹/quintal through the same
            # helper the provider serves with. Everything downstream of here is a
            # price: MAPE on a log return is meaningless (the denominator sits at
            # zero) and directional accuracy on one is degenerate, because
            # `sign(return - price_now)` is negative for every single row.
            predictions: dict[str, np.ndarray] = {}
            for key, alpha in QUANTILES.items():
                booster = fit_booster(train_part, valid_part, alpha)
                raw = booster.predict(x_valid, num_iteration=booster.best_iteration)
                predictions[key] = _predictions_to_price(price_now, np.asarray(raw))

            truth = valid_part["price_target"].to_numpy(dtype=float)
            crop = valid_part["commodity_id"].to_numpy(dtype=float)
            model_pools.append({**predictions, "y": truth, "price_now": price_now,
                                "crop": crop})
            base = baseline_predictions(train_part, valid_part)
            base_pools.append({**base, "y": truth, "price_now": price_now, "crop": crop})

        if not model_pools:
            report.fold_notes.append(f"h={horizon}: every fold too small — no metrics")
            continue

        pooled_model, pooled_base = _pooled(model_pools), _pooled(base_pools)
        report.model_metrics[f"h{horizon}"] = M.score_horizon(
            pooled_model["y"], pooled_model["p10"], pooled_model["p50"],
            pooled_model["p90"], price_now=pooled_model["price_now"],
        )
        report.baseline_metrics[f"h{horizon}"] = M.score_horizon(
            pooled_base["y"], pooled_base["p10"], pooled_base["p50"],
            pooled_base["p90"], price_now=pooled_base["price_now"],
        )
        _score_per_crop(report, horizon, pooled_model)

        # Refit on everything up to the last usable fold's train end. The folds
        # measured how good this configuration is; the shipped booster should
        # then use all the data that measurement licensed.
        final_train = (
            slice_[pd.to_datetime(slice_["as_of"]) <= last_usable.train_end]
            if last_usable else slice_
        )
        holdout = slice_[pd.to_datetime(slice_["as_of"]) > last_usable.train_end] \
            if last_usable is not None else slice_.tail(MIN_FOLD_VALID_ROWS)
        if len(holdout) < MIN_FOLD_VALID_ROWS:
            holdout = final_train.tail(max(MIN_FOLD_VALID_ROWS, len(final_train) // 10))
        for key, alpha in QUANTILES.items():
            boosters[(horizon, key)] = fit_booster(final_train, holdout, alpha)

        log.info("horizon_trained", horizon=horizon, rows=len(slice_),
                 folds=len(model_pools),
                 pinball=report.model_metrics[f"h{horizon}"]["pinball_mean"],
                 skill_vs_naive=report.skill(horizon))

    return boosters, report


def _score_per_crop(report: TrainReport, horizon: int,
                    pooled: Mapping[str, np.ndarray]) -> None:
    """Per-crop metrics, because a pooled number can hide a dead crop.

    With one global model and one crop dominating the rows, the model can score
    well by fitting onion and ignoring everything else. The pooled figure would
    never show it.
    """
    crops = pooled["crop"]
    for commodity_id in np.unique(crops):
        mask = crops == commodity_id
        if int(mask.sum()) < 20:
            continue
        key = f"commodity_{int(commodity_id)}_h{horizon}"
        report.per_crop[key] = {
            "n": float(mask.sum()),
            "pinball_mean": M.mean_pinball(
                pooled["y"][mask],
                {0.10: pooled["p10"][mask], 0.50: pooled["p50"][mask],
                 0.90: pooled["p90"][mask]},
            ),
            "picp": M.picp(pooled["y"][mask], pooled["p10"][mask], pooled["p90"][mask]),
            "mape": M.mape(pooled["y"][mask], pooled["p50"][mask]),
        }


def render_report(report: TrainReport) -> str:
    """The metrics table that goes in the deck."""
    lines: list[str] = []
    lines.append(f"\n  rows trained   {report.rows_trained:,}")
    lines.append(f"  window         {report.train_start} .. {report.train_end}")
    lines.append(f"\n  {'horizon':<9}{'pinball':>10}{'naive':>10}{'skill':>9}"
                 f"{'PICP':>8}{'MAPE%':>9}{'dir.acc':>9}")
    lines.append("  " + "─" * 62)
    for horizon in report.horizons:
        key = f"h{horizon}"
        mine = report.model_metrics.get(key)
        base = report.baseline_metrics.get(key, {})
        if not mine:
            lines.append(f"  h={horizon:<7}{'— not scored —':>46}")
            continue
        lines.append(
            f"  h={horizon:<7}{mine['pinball_mean']:>10.5f}"
            f"{base.get('pinball_mean', float('nan')):>10.5f}"
            f"{report.skill(horizon) * 100:>8.1f}%"
            f"{mine['picp']:>8.3f}{mine['mape']:>9.2f}"
            f"{mine.get('directional_accuracy', float('nan')):>9.3f}"
        )
    if report.per_crop:
        lines.append("\n  per crop (h=7, the horizon the product sells on)")
        lines.append("  " + "─" * 62)
        for key, values in sorted(report.per_crop.items()):
            if not key.endswith("_h7"):
                continue
            lines.append(f"  {key:<28}n={values['n']:>7.0f}  "
                         f"pinball {values['pinball_mean']:.5f}  PICP {values['picp']:.3f}")
    return "\n".join(lines)
