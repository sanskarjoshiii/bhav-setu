"""Phase A3 — four forecasters too stupid to be wrong in an interesting way.

These exist for two reasons, and the second one is the important one.

  1. Today they are the engine. `BaselineProvider` serves the whole product from
     them while the trained model does not exist.
  2. On swap day they are the opponent. Phase B3 promotes LightGBM only if it
     beats these, at every horizon, on pinball loss. Projects that skip this step
     find out on stage that their model is worse than "same as yesterday".

Every function takes a price series ordered oldest-to-newest and a horizon, and
returns the predicted price `horizon` days after the last observation. None of
them look at anything but past prices — that is the point. A signal that cannot
beat a straight line drawn through last week is not a signal.
"""

from __future__ import annotations

from typing import Callable, Mapping, Sequence

import numpy as np

from core.config import settings
from core.errors import InsufficientData

_CFG = settings.model.baseline
SEASONAL_PERIOD: int = int(_CFG.seasonal_period)
MA_WINDOW: int = int(_CFG.ma_window)
SWITCH_MARGIN: float = float(_CFG.switch_margin)

ArrayLike = Sequence[float] | np.ndarray


def _as_series(values: ArrayLike) -> np.ndarray:
    series = np.asarray(values, dtype=float).ravel()
    series = series[np.isfinite(series)]
    if series.size == 0:
        raise InsufficientData("baseline needs at least one observation, got none")
    return series


# ══════════════════════════════════════════════════════════════════════════
# the four
# ══════════════════════════════════════════════════════════════════════════

def naive(values: ArrayLike, horizon: int) -> float:
    """Tomorrow is today. The benchmark everything else must beat.

    Unglamorous and genuinely hard to beat: daily mandi prices are close to a
    random walk at short horizons, so at h=1 this is often the best any method
    manages. If a clever model cannot beat it, the cleverness is not helping.
    """
    return float(_as_series(values)[-1])


def seasonal_naive(values: ArrayLike, horizon: int, period: int = SEASONAL_PERIOD) -> float:
    """The value from the most recent same-phase point in the cycle.

    Mandi prices have a weekly rhythm — market days, weekend arrivals — so the
    default period is 7. For horizon h the reference is h - period*ceil(h/period)
    steps back, which for h=7 is simply today and for h=1 is six days ago.
    """
    series = _as_series(values)
    if period < 1:
        raise ValueError(f"seasonal period must be >= 1, got {period}")
    offset = int(np.ceil(horizon / period)) * period - horizon
    index = series.size - 1 - offset
    if index < 0:
        # Not enough history to reach the same phase; fall back rather than
        # wrap around to an arbitrary point and pretend it is seasonal.
        return float(series[0])
    return float(series[index])


def drift(values: ArrayLike, horizon: int) -> float:
    """Extend the straight line from the first observation to the last.

    The cheapest possible trend model. Included because it is the one baseline
    that can be badly wrong in a useful way: when it loses heavily to naive, the
    series has no persistent trend, which itself is worth knowing.
    """
    series = _as_series(values)
    if series.size < 2:
        return float(series[-1])
    slope = (series[-1] - series[0]) / (series.size - 1)
    return float(series[-1] + horizon * slope)


def moving_average(values: ArrayLike, horizon: int, window: int = MA_WINDOW) -> float:
    """Flat forecast at the mean of the last `window` observations.

    Trades responsiveness for noise rejection. Beats naive on jittery series and
    loses to it whenever the price has genuinely moved, which is exactly the
    trade-off the winner-selection below is there to resolve per series.
    """
    series = _as_series(values)
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    return float(np.mean(series[-min(window, series.size):]))


#: name -> function. The registry `BaselineProvider` and Phase B3 both read.
METHODS: dict[str, Callable[[ArrayLike, int], float]] = {
    "naive": naive,
    "seasonal_naive": seasonal_naive,
    "drift": drift,
    "moving_average": moving_average,
}

#: the benchmark Phase B3 measures skill against. Not the best baseline — the
#: dumbest one, because "beats the dumbest thing that works" is the claim we
#: want to be able to make without an asterisk.
BENCHMARK: str = "naive"


def predict(method: str, values: ArrayLike, horizon: int) -> float:
    try:
        function = METHODS[method]
    except KeyError as exc:
        raise ValueError(f"unknown baseline {method!r}; have {sorted(METHODS)}") from exc
    return function(values, horizon)


# ══════════════════════════════════════════════════════════════════════════
# rolling-origin evaluation — how we learn which one to trust
# ══════════════════════════════════════════════════════════════════════════

def rolling_residuals(
    values: ArrayLike,
    horizon: int,
    method: str,
    *,
    min_train: int = 2,
) -> np.ndarray:
    """Signed errors (actual - predicted) this method would have made, at this horizon.

    Walks the series forward: at each cut-off, forecast `horizon` ahead using
    only what existed at that point, then compare with what actually happened.
    No row is ever scored against information from its own future, which is what
    makes the resulting spread a usable estimate of how wrong we tend to be.

    This is where the bands come from. We do not assume a distribution; we look
    up how badly this method has actually missed on this series and quote that.
    """
    series = _as_series(values)
    errors: list[float] = []
    for cut in range(max(min_train, 1), series.size - horizon + 1):
        history = series[:cut]
        actual = series[cut + horizon - 1]
        try:
            predicted = predict(method, history, horizon)
        except InsufficientData:
            continue
        if np.isfinite(predicted):
            errors.append(float(actual - predicted))
    return np.asarray(errors, dtype=float)


def evaluate_methods(
    values: ArrayLike,
    horizon: int,
    methods: Sequence[str] | None = None,
    *,
    min_train: int = 2,
) -> dict[str, dict[str, float]]:
    """Every method's rolling error profile at one horizon.

    Returns per method: `mae`, `n` (residuals scored), and the residual array's
    10th/90th percentiles. The provider picks a winner from this; Phase B3 reads
    the benchmark's row from it.
    """
    wanted = list(methods or METHODS)
    out: dict[str, dict[str, float]] = {}
    for method in wanted:
        residuals = rolling_residuals(values, horizon, method, min_train=min_train)
        if residuals.size == 0:
            out[method] = {"mae": float("nan"), "n": 0.0,
                           "q10": float("nan"), "q90": float("nan")}
            continue
        out[method] = {
            "mae": float(np.mean(np.abs(residuals))),
            "n": float(residuals.size),
            "q10": float(np.quantile(residuals, 0.10)),
            "q90": float(np.quantile(residuals, 0.90)),
        }
    return out


def best_method(
    profiles: Mapping[str, Mapping[str, float]],
    *,
    fallback: str = BENCHMARK,
    margin: float = SWITCH_MARGIN,
) -> str:
    """The benchmark, unless a challenger beats it by more than `margin`.

    Not a plain argmin, and the difference matters. Measured on real series, the
    four methods often sit within 1% of each other at the longer horizons —
    taking the argmin of four near-tied noisy estimates is close to picking at
    random, and it produced a "tuned" baseline that scored *worse than plain
    naive* at two of the four horizons. A forecaster that loses to "same as
    today" while being offered as the benchmark is worse than useless: it would
    make Phase B3's gate trivial to clear.

    So the benchmark holds the floor and a challenger has to earn the switch. On
    the series we measured this keeps naive at h=1 and h=7, where the margins
    were noise, and still switches to the moving average at h=3 and h=15, where
    it wins by 25%+.

    Choosing among four fixed candidates on the series' own history is still a
    mild form of selection, and worth naming as such — but four hypotheses with
    a margin is a rounding error next to a boosted tree, and the alternative is
    picking one method by taste and being quietly wrong on half the crops.
    """
    scored = {
        name: float(stats["mae"])
        for name, stats in profiles.items()
        if np.isfinite(stats.get("mae", float("nan"))) and stats.get("n", 0)
    }
    if not scored:
        return fallback

    challenger = min(scored, key=lambda name: scored[name])
    benchmark_mae = scored.get(fallback)
    if benchmark_mae is None:
        return challenger
    return challenger if scored[challenger] < benchmark_mae * (1.0 - margin) else fallback
