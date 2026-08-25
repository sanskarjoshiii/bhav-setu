"""Phase A0 — the one seam between the forecasting model and the rest of the product.

The decision engine, the API, the website and the WhatsApp agent may know about
`ForecastProvider` and nothing else. None of them may import LightGBM, open a
booster file, or touch a feature frame. If that rule holds, the model is a plug
that swaps with one line in config/model.yaml. If it leaks — even once, even
"just for the accuracy page" — swap day becomes a rewrite.

Two things live here:

  * `ForecastProvider`  — what a forecaster must offer.
  * `build_serving_row` — the single inference-time feature path, so a model
    trained on one column order can never be served on another.

The contract is enforced by tests, not by hope: `tests/contract_forecast.py`
runs the same suite against every provider, and B2's LightGBM wrapper must pass
that file unmodified.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Mapping, NamedTuple, Protocol, Sequence, runtime_checkable

import numpy as np
from sqlalchemy.engine import Connection

from core.config import settings
from core.errors import ForecastContractError
from features.registry import FEATURE_NAMES

# Horizons come from app.yaml so training, serving and the UI cannot drift apart.
DEFAULT_HORIZONS: tuple[int, ...] = tuple(int(h) for h in settings.app.horizons)

# A forecast is a price in ₹/quintal. Anything outside this is a bug, not a market.
MIN_PLAUSIBLE_PRICE: float = 1.0
MAX_PLAUSIBLE_PRICE: float = 1_000_000.0


# ══════════════════════════════════════════════════════════════════════════
# what a forecast is
# ══════════════════════════════════════════════════════════════════════════

class Quantiles(NamedTuple):
    """A predicted price band in ₹/quintal: low case, likely case, high case.

    We never return a single number. Nobody can predict onion to the rupee, and
    pretending otherwise is how a farmer with a loan gets advice that ruins him.
    The decision engine reads `p10` as the downside it must price in.
    """

    p10: float
    p50: float
    p90: float

    @classmethod
    def of(cls, low: float, mid: float, high: float) -> "Quantiles":
        """Build a band, sorting the three values.

        Sorting is not politeness. Quantile regressors are fitted independently
        per quantile and *do* cross on hard rows — an unsorted band silently
        flips the sign of the decision engine's downside term, which produces a
        confident recommendation built on a negative risk penalty. Every
        provider must come through here.
        """
        values = (float(low), float(mid), float(high))
        for value in values:
            if not math.isfinite(value):
                raise ForecastContractError(f"forecast quantile is not finite: {values}")
            if not MIN_PLAUSIBLE_PRICE <= value <= MAX_PLAUSIBLE_PRICE:
                raise ForecastContractError(
                    f"forecast quantile {value} ₹/qtl is outside the plausible range "
                    f"[{MIN_PLAUSIBLE_PRICE}, {MAX_PLAUSIBLE_PRICE}]"
                )
        p10, p50, p90 = sorted(values)
        return cls(p10=p10, p50=p50, p90=p90)

    @property
    def width(self) -> float:
        """p90 − p10, in ₹/quintal."""
        return self.p90 - self.p10

    @property
    def relative_width(self) -> float:
        """Band width as a fraction of the median — the raw material of confidence."""
        return self.width / self.p50 if self.p50 else float("inf")

    def as_dict(self) -> dict[str, float]:
        return {"p10": self.p10, "p50": self.p50, "p90": self.p90}


#: horizon in days -> band. Always exactly the horizons that were asked for.
Forecast = dict[int, Quantiles]


@runtime_checkable
class ForecastProvider(Protocol):
    """Anything that can answer "what will this cost, and how sure are you?".

    Implemented by `BaselineProvider` (Phase A3) and later `LgbmProvider`
    (Phase B2). Consumers depend on this and never on either name.
    """

    #: short stable id, matching the key in config/model.yaml -> providers
    name: str

    #: the version recorded in model_registry and shown on the accuracy page
    version: str

    def predict_quantiles(
        self,
        commodity_id: int,
        mandi_id: int,
        as_of: date,
        horizons: Sequence[int] = DEFAULT_HORIZONS,
    ) -> Forecast:
        """Bands for each horizon, as known on `as_of`.

        Must use only information available on `as_of` — a provider that peeks
        forward looks brilliant in the backtest and useless in the field.

        Raises `InsufficientData` when there is not enough history. It must
        never invent a number to avoid raising: a silent zero travels all the
        way to a farmer's screen looking exactly like a real answer.
        """
        ...


def validate_forecast(result: Mapping[int, Quantiles], horizons: Sequence[int]) -> Forecast:
    """Check a provider's output against the contract. Cheap; call it on every return.

    Providers should wrap their own result in this rather than trusting
    themselves — the failure this catches is silent everywhere else.
    """
    wanted = [int(h) for h in horizons]
    missing = [h for h in wanted if h not in result]
    extra = [h for h in result if h not in wanted]
    if missing or extra:
        raise ForecastContractError(
            f"forecast horizons do not match the request — missing={missing} unexpected={extra}"
        )
    validated: Forecast = {}
    for horizon in wanted:
        band = result[horizon]
        if not isinstance(band, Quantiles):
            raise ForecastContractError(
                f"horizon {horizon} returned {type(band).__name__}, expected Quantiles"
            )
        if not band.p10 <= band.p50 <= band.p90:
            raise ForecastContractError(
                f"horizon {horizon} band is unsorted: {band} — build it with Quantiles.of()"
            )
        validated[horizon] = band
    return validated


# ══════════════════════════════════════════════════════════════════════════
# the serving feature path
# ══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ServingRow:
    """One feature row, ready for a model and readable by an explanation.

    `vector` is what the booster consumes; `values` is what the reason line is
    written from. They are two views of the same row, built once, so the number
    a farmer is shown and the number the model used cannot diverge.
    """

    as_of: date
    mandi_id: int
    commodity_id: int
    values: dict[str, float]
    vector: np.ndarray

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(FEATURE_NAMES)


def build_serving_row(
    as_of: date,
    mandi_id: int,
    commodity_id: int,
    conn: Connection,
    cache: object | None = None,
) -> ServingRow:
    """The single inference-time entry point into the feature builder.

    Training and serving both end up in `features.builder.build_features`; this
    wrapper exists so that serving has exactly one call site and one column
    order. A model trained on one order and served on another does not crash —
    it just gets quietly, unfixably worse — so the order is asserted here rather
    than assumed.
    """
    from features.builder import build_features  # local: keeps pandas off the API import path

    values = build_features(as_of, mandi_id, commodity_id, conn, cache)  # type: ignore[arg-type]
    if list(values) != FEATURE_NAMES:
        raise ForecastContractError(
            "serving row column order does not match features/registry.py — "
            "the builder and the registry have drifted apart"
        )
    vector = np.asarray([values[name] for name in FEATURE_NAMES], dtype=float)
    return ServingRow(
        as_of=as_of,
        mandi_id=int(mandi_id),
        commodity_id=int(commodity_id),
        values=dict(values),
        vector=vector,
    )
