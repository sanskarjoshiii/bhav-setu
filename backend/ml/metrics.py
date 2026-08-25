"""Phase A3 — the scoreboard both forecasters are held to.

Written before either forecaster, on purpose. These four numbers are how Phase B3
decides whether the trained model replaces the baseline, and a metric written
after seeing a model's output is a metric shaped to flatter it.

    pinball_loss           the one that matters for quantiles
    picp                   is the p10-p90 band honest, or decoration?
    mape                   the number a human asks for
    directional_accuracy   did we at least get the sign right?

All of them take plain arrays and return plain floats. No model, no database, no
config — so the same function grades the baseline, the booster and any argument
about which is better.
"""

from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

ArrayLike = Sequence[float] | np.ndarray


def _clean_pair(a: ArrayLike, b: ArrayLike) -> tuple[np.ndarray, np.ndarray]:
    """Align two series and drop any position where either is missing.

    Dropping silently would let a metric be computed over three of a hundred
    rows and reported as if it covered all hundred, so callers get the surviving
    count back through `n_scored` on the summary.
    """
    first = np.asarray(a, dtype=float).ravel()
    second = np.asarray(b, dtype=float).ravel()
    if first.shape != second.shape:
        raise ValueError(f"length mismatch: {first.shape} vs {second.shape}")
    keep = np.isfinite(first) & np.isfinite(second)
    return first[keep], second[keep]


# ══════════════════════════════════════════════════════════════════════════
# quantile quality
# ══════════════════════════════════════════════════════════════════════════

def pinball_loss(y_true: ArrayLike, y_pred: ArrayLike, quantile: float) -> float:
    """The proper scoring rule for a single quantile. Lower is better.

    Asymmetric on purpose: predicting the 10th percentile too high is penalised
    nine times as hard as predicting it too low. That asymmetry is the whole
    reason we quote a band — a p10 that is optimistic is exactly the error that
    ruins a farmer with a loan, and a symmetric metric would not notice it.
    """
    if not 0.0 < quantile < 1.0:
        raise ValueError(f"quantile must be in (0, 1), got {quantile}")
    truth, prediction = _clean_pair(y_true, y_pred)
    if truth.size == 0:
        return float("nan")
    delta = truth - prediction
    return float(np.mean(np.maximum(quantile * delta, (quantile - 1.0) * delta)))


def mean_pinball(
    y_true: ArrayLike,
    predictions: Mapping[float, ArrayLike],
) -> float:
    """Average pinball across the quantiles we actually serve.

    One number for "is this set of bands better than that set of bands", which
    is the comparison Phase B3 makes.
    """
    if not predictions:
        raise ValueError("no quantile predictions given")
    losses = [pinball_loss(y_true, values, q) for q, values in predictions.items()]
    finite = [loss for loss in losses if np.isfinite(loss)]
    return float(np.mean(finite)) if finite else float("nan")


def picp(y_true: ArrayLike, lower: ArrayLike, upper: ArrayLike) -> float:
    """Prediction Interval Coverage Probability — the share of outcomes inside the band.

    For a p10-p90 band the honest answer is 0.80. Wildly above it means the band
    is so wide it says nothing; below it means we are promising more precision
    than we have. Phase B3 requires 0.72-0.88, and a model outside that range is
    rejected however good its point forecast looks.
    """
    truth = np.asarray(y_true, dtype=float).ravel()
    low = np.asarray(lower, dtype=float).ravel()
    high = np.asarray(upper, dtype=float).ravel()
    if not truth.shape == low.shape == high.shape:
        raise ValueError(f"length mismatch: {truth.shape}, {low.shape}, {high.shape}")
    keep = np.isfinite(truth) & np.isfinite(low) & np.isfinite(high)
    if not keep.any():
        return float("nan")
    inside = (truth[keep] >= low[keep]) & (truth[keep] <= high[keep])
    return float(np.mean(inside))


def mean_interval_width(lower: ArrayLike, upper: ArrayLike,
                        reference: ArrayLike | None = None) -> float:
    """Band width, relative to the reference price when one is given.

    PICP alone is gameable: a band from zero to infinity covers everything. This
    is the other half of the pair, and the two must always be read together.
    """
    low = np.asarray(lower, dtype=float).ravel()
    high = np.asarray(upper, dtype=float).ravel()
    width = high - low
    if reference is not None:
        base = np.asarray(reference, dtype=float).ravel()
        with np.errstate(divide="ignore", invalid="ignore"):
            width = np.where(base > 0, width / base, np.nan)
    finite = width[np.isfinite(width)]
    return float(np.mean(finite)) if finite.size else float("nan")


# ══════════════════════════════════════════════════════════════════════════
# point quality
# ══════════════════════════════════════════════════════════════════════════

def mape(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    """Mean absolute percentage error, as a percentage. Zero-truth rows are dropped."""
    truth, prediction = _clean_pair(y_true, y_pred)
    keep = truth != 0
    if not keep.any():
        return float("nan")
    return float(np.mean(np.abs((truth[keep] - prediction[keep]) / truth[keep])) * 100.0)


def mae(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    truth, prediction = _clean_pair(y_true, y_pred)
    return float(np.mean(np.abs(truth - prediction))) if truth.size else float("nan")


def rmse(y_true: ArrayLike, y_pred: ArrayLike) -> float:
    truth, prediction = _clean_pair(y_true, y_pred)
    return float(np.sqrt(np.mean((truth - prediction) ** 2))) if truth.size else float("nan")


def directional_accuracy(price_now: ArrayLike, y_true: ArrayLike,
                         y_pred: ArrayLike) -> float:
    """Share of cases where we called up-or-down correctly, relative to today.

    The metric a farmer actually cares about. "Will it go up or down?" is the
    question behind hold-or-sell, and a model can have a respectable MAPE while
    being no better than a coin toss on the only bit that changes his decision.

    Two kinds of row are excluded, for the same reason — no direction was in
    play, so there is nothing to be right or wrong about:

      * the true price did not move; and
      * **the forecast did not move**. A naive forecast predicts "same as
        today" every time. Scoring that as 0% correct is not a measurement, it
        is a category error: the method makes no directional call at all. We
        printed 0.000 for the baseline before fixing this and it read as
        "always wrong" rather than "never asked".

    Returns NaN when no row survives, which is the honest answer for a method
    that never calls a direction.
    """
    now = np.asarray(price_now, dtype=float).ravel()
    truth = np.asarray(y_true, dtype=float).ravel()
    prediction = np.asarray(y_pred, dtype=float).ravel()
    if not now.shape == truth.shape == prediction.shape:
        raise ValueError(f"length mismatch: {now.shape}, {truth.shape}, {prediction.shape}")
    keep = np.isfinite(now) & np.isfinite(truth) & np.isfinite(prediction)
    actual = np.sign(truth - now)
    called = np.sign(prediction - now)
    keep &= (actual != 0) & (called != 0)
    if not keep.any():
        return float("nan")
    return float(np.mean(called[keep] == actual[keep]))


# ══════════════════════════════════════════════════════════════════════════
# the whole scoreboard, for one horizon
# ══════════════════════════════════════════════════════════════════════════

def score_horizon(
    y_true: ArrayLike,
    p10: ArrayLike,
    p50: ArrayLike,
    p90: ArrayLike,
    price_now: ArrayLike | None = None,
) -> dict[str, float]:
    """Every metric for one horizon, as a flat dict ready for `model_registry.metrics`."""
    truth = np.asarray(y_true, dtype=float).ravel()
    result: dict[str, float] = {
        "n_scored": float(np.sum(np.isfinite(truth))),
        "pinball_p10": pinball_loss(y_true, p10, 0.10),
        "pinball_p50": pinball_loss(y_true, p50, 0.50),
        "pinball_p90": pinball_loss(y_true, p90, 0.90),
        "pinball_mean": mean_pinball(y_true, {0.10: p10, 0.50: p50, 0.90: p90}),
        "picp": picp(y_true, p10, p90),
        "interval_width_rel": mean_interval_width(p10, p90, truth),
        "mape": mape(y_true, p50),
        "mae": mae(y_true, p50),
        "rmse": rmse(y_true, p50),
    }
    if price_now is not None:
        result["directional_accuracy"] = directional_accuracy(price_now, y_true, p50)
    return result


def skill_score(candidate: float, benchmark: float) -> float:
    """Fractional improvement over a benchmark loss. Positive means better.

    Phase B3 reads this: `skill_score(lgbm_pinball, naive_pinball) > 0` at every
    horizon is the gate. Expressing it as a ratio rather than a difference makes
    it comparable across crops whose prices differ by an order of magnitude.
    """
    if not np.isfinite(candidate) or not np.isfinite(benchmark) or benchmark == 0:
        return float("nan")
    return float((benchmark - candidate) / abs(benchmark))
