"""Phase A3 — the borrowed engine: a real ForecastProvider with no training.

It answers the same question the trained model will, through the same port, so
the decision engine, the API, the website and the WhatsApp agent can all be built
and demonstrated before a single tree is fitted.

How a band gets made, and why it is honest:

  1. Walk the series forward, scoring all four baselines at this horizon using
     only what existed at each cut-off. Pick the one with the lowest error on
     *this* crop at *this* market — tomato in Pune is not onion in Lasalgaon.
  2. Take that method's forecast as a starting point.
  3. Add the 10th, 50th and 90th percentiles of its own past errors at this
     horizon.

Step 3 is the whole idea. We do not assume a bell curve and we do not invent a
±15%. We look up how badly this method has actually missed on this series and
quote that back. Two consequences fall out for free:

  * The p50 is the point forecast, NOT the point forecast plus the median
    past error. We built the bias-corrected version first and measured it: it
    made the baseline WORSE than plain naive at two of four horizons. On a
    random walk the historical median error is statistically significant and
    predictively worthless, and adding it back is just a second, worse drift
    model. Trend belongs in the method choice — `drift` is already one of the
    four candidates — not bolted onto another method's output.
  * A thin-history crop gets a wider band than a dense one — but NOT for free.
    Reading the 10th percentile straight off thirty residuals makes a thin crop
    look *more* certain, because small samples miss tails. `tail_levels()` is
    the correction, and it exists because a test caught the naive version
    shipping false confidence on exactly the crops we know least about.

It is a humble forecast with a truthful error bar, which beats a confident
forecast with an invented one. And on swap day it is the opponent.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from typing import Sequence

import numpy as np
from sqlalchemy import text

from core.config import settings
from core.db import get_conn
from core.errors import InsufficientData
from ml import baselines
from ml.port import DEFAULT_HORIZONS, Forecast, Quantiles, validate_forecast

_CFG = settings.model.baseline
VERSION: str = str(_CFG.version)
MIN_HISTORY_DAYS: int = int(_CFG.min_history_days)
MIN_RESIDUALS: int = int(_CFG.min_residuals)
FALLBACK_BAND_PCT: float = float(_CFG.fallback_band_pct)
MIN_BAND_PCT: float = float(_CFG.min_band_pct)
TAIL_Z: float = float(_CFG.tail_confidence_z)

#: how many (crop, mandi, as_of) series to keep in memory. A request asks for
#: four horizons at one as_of, so a small cache turns four queries into one.
CACHE_SIZE: int = 256

_HISTORY_SQL = text(
    """
    SELECT obs_date, avg(modal_price)::float8 AS modal_price
    FROM price_observations
    WHERE commodity_id = :commodity_id
      AND mandi_id     = :mandi_id
      AND obs_date    <= :as_of
      AND modal_price IS NOT NULL
    GROUP BY obs_date
    ORDER BY obs_date
    """
)


@dataclass(frozen=True)
class BandBasis:
    """Why one band looks the way it does. Logged, and shown on the accuracy page."""

    horizon: int
    method: str
    point: float
    residuals: int
    empirical: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "horizon": self.horizon,
            "method": self.method,
            "point": round(self.point, 2),
            "residuals": self.residuals,
            "empirical": self.empirical,
        }


class BaselineProvider:
    """Satisfies `ml.port.ForecastProvider`. Registered as `baseline` in model.yaml."""

    name = "baseline"
    version = VERSION

    def __init__(self) -> None:
        self._history: OrderedDict[tuple[int, int, date], np.ndarray] = OrderedDict()
        #: how the last call built each band — read by tests and diagnostics
        self.last_basis: list[BandBasis] = []

    # ── history ───────────────────────────────────────────────────────────

    def _load_history(self, commodity_id: int, mandi_id: int, as_of: date) -> np.ndarray:
        """Daily modal prices up to and including `as_of`. Never beyond.

        The cut-off is in the SQL rather than applied afterwards, so there is no
        code path in which a future row could reach a forecast.
        """
        key = (int(commodity_id), int(mandi_id), as_of)
        cached = self._history.get(key)
        if cached is not None:
            self._history.move_to_end(key)
            return cached

        with get_conn() as conn:
            rows = conn.execute(
                _HISTORY_SQL,
                {"commodity_id": int(commodity_id), "mandi_id": int(mandi_id), "as_of": as_of},
            ).all()
        series = np.asarray([float(r.modal_price) for r in rows], dtype=float)

        self._history[key] = series
        if len(self._history) > CACHE_SIZE:
            self._history.popitem(last=False)
        return series

    def clear_cache(self) -> None:
        """Drop cached history. Call after loading new prices in the same process."""
        self._history.clear()

    # ── the contract ──────────────────────────────────────────────────────

    def predict_quantiles(
        self,
        commodity_id: int,
        mandi_id: int,
        as_of: date,
        horizons: Sequence[int] = DEFAULT_HORIZONS,
    ) -> Forecast:
        series = self._load_history(commodity_id, mandi_id, as_of)
        if series.size < MIN_HISTORY_DAYS:
            raise InsufficientData(
                f"commodity {commodity_id} at mandi {mandi_id} has {series.size} "
                f"observations on or before {as_of}; the baseline needs "
                f"{MIN_HISTORY_DAYS}. Showing a price is fine — forecasting is not.",
                needed=MIN_HISTORY_DAYS,
                found=int(series.size),
            )
        return self.forecast_series(series, horizons)

    def forecast_series(self, series: np.ndarray, horizons: Sequence[int]) -> Forecast:
        """The maths, separated from the database so tests can drive it directly."""
        basis: list[BandBasis] = []
        result: dict[int, Quantiles] = {}

        for horizon in (int(h) for h in horizons):
            profiles = baselines.evaluate_methods(series, horizon)
            method = baselines.best_method(profiles)
            point = baselines.predict(method, series, horizon)
            residuals = baselines.rolling_residuals(series, horizon, method)

            if residuals.size >= MIN_RESIDUALS:
                lo_level, hi_level = tail_levels(residuals.size)
                low, mid, high = (
                    float(q) for q in np.quantile(residuals, [lo_level, 0.50, hi_level])
                )
                # The band is the residual spread, recentred on the point
                # forecast. The residual MEDIAN is deliberately thrown away —
                # see the note on bias correction in this module's docstring.
                p10 = point + (low - mid)
                p50 = point
                p90 = point + (high - mid)
                empirical = True
            else:
                # Too few residuals for percentiles to mean anything. Say so with
                # a wide band rather than a precise-looking narrow one.
                half = FALLBACK_BAND_PCT * math.sqrt(horizon) * point
                p10, p50, p90 = point - half, point, point + half
                empirical = False

            p10, p50, p90 = _floor_band(p10, p50, p90)
            result[horizon] = Quantiles.of(p10, p50, p90)
            basis.append(BandBasis(horizon, method, point, int(residuals.size), empirical))

        self.last_basis = basis
        return validate_forecast(result, horizons)

    def explain_last(self) -> list[dict[str, object]]:
        return [b.as_dict() for b in self.last_basis]


def tail_levels(n_residuals: int) -> tuple[float, float]:
    """The quantile levels to read off `n` residuals for an honest 10-90 band.

    Not 0.10 and 0.90. The empirical 10th percentile of thirty numbers is a
    *noisy* estimate of the true 10th percentile, and noisy in a direction that
    matters: small samples systematically miss the tails, so reading 0.10
    straight off makes a thin-history crop look MORE certain than a dense one.
    We shipped exactly that until a test caught it.

    So we read a one-sided confidence bound on the tail instead. The sampling
    standard error of an empirical quantile is sqrt(q(1-q)/n), and we step that
    many standard errors outward:

        n =  30 residuals -> read the 3rd and 97th percentiles
        n = 400 residuals -> read the 8th and 92nd

    The conservatism costs almost nothing once the evidence is real, and it is
    the difference between honest and confident on a crop we barely know.
    """
    if n_residuals <= 0:
        return 0.10, 0.90
    spread = TAIL_Z * math.sqrt(0.10 * 0.90 / n_residuals)
    return max(0.10 - spread, 0.005), min(0.90 + spread, 0.995)


def _floor_band(p10: float, p50: float, p90: float) -> tuple[float, float, float]:
    """Keep the band above a minimum width and strictly positive.

    A degenerate band — every past error identical, which happens on a short
    flat stretch — would tell the decision engine there is no downside at all,
    and it would then happily hold everything. There is always downside.
    """
    p10, p50, p90 = sorted((float(p10), float(p50), float(p90)))
    centre = max(p50, 1.0)
    minimum = MIN_BAND_PCT * centre
    if (p90 - p10) < minimum:
        p10, p90 = centre - minimum / 2.0, centre + minimum / 2.0
        p50 = centre
    # A negative price is not a cheap market; clamp without moving the median.
    if p10 < 1.0:
        p10 = min(1.0, p50 * 0.5)
    return p10, p50, p90
