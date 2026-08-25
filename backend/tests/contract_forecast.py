"""Phase A0 — the contract every ForecastProvider must satisfy.

Not a test module (no `test_` prefix, so pytest does not collect it). It is a
suite that other test modules run against a concrete provider:

    tests/test_phaseA0_port.py   -> a stub, proving the machinery works
    tests/test_phaseA3_baseline.py -> BaselineProvider
    tests/test_phaseB2_lgbm.py   -> LgbmProvider, this file UNMODIFIED

That last line is the whole point. The day the trained model arrives it is held
to the same standard the baseline already meets, using the same code — so
"it passes the contract" means the same thing before and after swap day.

Some of these checks are anti-vacuity: they fail a provider that is technically
returning valid shapes while doing nothing useful. Our own suite once passed
47/47 while every crop silently returned "sell now", which is why they are here.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date
from typing import Sequence

from core.errors import InsufficientData
from ml.port import DEFAULT_HORIZONS, ForecastProvider, Quantiles, validate_forecast


@dataclass(frozen=True)
class ProbeCase:
    """One (crop, mandi, day) the provider will be asked about."""

    commodity_id: int
    mandi_id: int
    as_of: date
    label: str = ""

    def __str__(self) -> str:
        return self.label or f"commodity={self.commodity_id} mandi={self.mandi_id} as_of={self.as_of}"


class ContractViolation(AssertionError):
    """A provider broke ml/port.py. Named so the failure reads clearly in pytest."""


def _fail(provider: ForecastProvider, message: str) -> None:
    name = getattr(provider, "name", type(provider).__name__)
    version = getattr(provider, "version", "?")
    raise ContractViolation(f"[{name}:{version}] {message}")


# ══════════════════════════════════════════════════════════════════════════
# the individual clauses
# ══════════════════════════════════════════════════════════════════════════

def check_identity(provider: ForecastProvider) -> None:
    """A provider must say who it is — the accuracy page prints this."""
    if not isinstance(provider, ForecastProvider):
        _fail(provider, "does not satisfy the ForecastProvider protocol")
    for attribute in ("name", "version"):
        value = getattr(provider, attribute, "")
        if not isinstance(value, str) or not value.strip():
            _fail(provider, f"has no usable .{attribute} — it is shown on the accuracy page")


def check_shape(provider: ForecastProvider, cases: Sequence[ProbeCase],
                horizons: Sequence[int]) -> None:
    """Exactly the horizons requested, every band sorted and finite."""
    for case in cases:
        result = provider.predict_quantiles(case.commodity_id, case.mandi_id,
                                            case.as_of, horizons)
        try:
            validate_forecast(result, horizons)
        except Exception as exc:
            _fail(provider, f"{case}: {exc}")


def check_ordering(provider: ForecastProvider, cases: Sequence[ProbeCase],
                   horizons: Sequence[int]) -> None:
    """p10 <= p50 <= p90, always.

    Quantile regressors are fitted independently and genuinely do cross on hard
    rows. An unsorted band flips the sign of the decision engine's downside
    term, which turns a risk penalty into a risk *bonus* — and nothing crashes.
    """
    for case in cases:
        for horizon, band in provider.predict_quantiles(
            case.commodity_id, case.mandi_id, case.as_of, horizons
        ).items():
            if not band.p10 <= band.p50 <= band.p90:
                _fail(provider, f"{case} h={horizon}: quantiles cross — {band}")
            if band.p10 <= 0:
                _fail(provider, f"{case} h={horizon}: non-positive price {band.p10}")


def check_determinism(provider: ForecastProvider, cases: Sequence[ProbeCase],
                      horizons: Sequence[int]) -> None:
    """The same question twice must give the same answer.

    A provider that samples fresh noise per call makes the backtest
    unreproducible and lets two pages show a farmer two different numbers for
    the same lot on the same morning.
    """
    for case in cases:
        first = provider.predict_quantiles(case.commodity_id, case.mandi_id, case.as_of, horizons)
        second = provider.predict_quantiles(case.commodity_id, case.mandi_id, case.as_of, horizons)
        if first != second:
            _fail(provider, f"{case}: not deterministic — {first} then {second}")


def check_horizon_subset(provider: ForecastProvider, case: ProbeCase,
                         horizons: Sequence[int]) -> None:
    """Asking for fewer horizons must return fewer, not the default set."""
    if len(horizons) < 2:
        return
    subset = [int(horizons[0])]
    result = provider.predict_quantiles(case.commodity_id, case.mandi_id, case.as_of, subset)
    if sorted(result) != subset:
        _fail(provider, f"{case}: asked for horizons {subset}, got {sorted(result)}")


def check_unknown_raises(provider: ForecastProvider, unknown: ProbeCase) -> None:
    """No data must raise, never return a number.

    This is the clause that matters most on stage. A silent zero, or a band
    extrapolated from nothing, travels all the way to a farmer's screen looking
    exactly like a real answer. `InsufficientData` becomes a clean 422 and an
    honest "I don't have data for that" from the WhatsApp agent.
    """
    try:
        result = provider.predict_quantiles(
            unknown.commodity_id, unknown.mandi_id, unknown.as_of, DEFAULT_HORIZONS
        )
    except InsufficientData:
        return
    _fail(provider, f"{unknown}: returned {result} instead of raising InsufficientData")


def check_uncertainty_grows(provider: ForecastProvider, cases: Sequence[ProbeCase],
                            horizons: Sequence[int]) -> None:
    """Anti-vacuity: the band must respond to the horizon, and must not shrink.

    Two separate faults, because they are separate mistakes:

      * **A band that ignores the horizon** is not modelling uncertainty at all,
        it is decorating a point forecast. The decision engine would then hold
        stock for two weeks on the strength of a one-day confidence.
      * **A band that narrows as the horizon grows** is inverted — an outright
        bug, whatever the series.

    Note what is deliberately *not* required: that the band strictly widen. A
    genuinely mean-reverting series has roughly horizon-independent error, and
    an honest provider will report roughly constant width for it. Demanding
    growth there would fail a provider for being right. Measured on medians
    across cases, so one odd series cannot fail an honest provider.
    """
    if len(horizons) < 2 or not cases:
        return
    ordered = sorted(int(h) for h in horizons)
    widths: dict[int, list[float]] = {h: [] for h in ordered}
    for case in cases:
        result = provider.predict_quantiles(case.commodity_id, case.mandi_id, case.as_of, horizons)
        for horizon in ordered:
            widths[horizon].append(result[horizon].relative_width)

    medians = {h: statistics.median(values) for h, values in widths.items()}
    if len(set(round(w, 9) for w in medians.values())) == 1:
        _fail(
            provider,
            f"band width is identical at every horizon ({medians[ordered[0]]:.4f}) — "
            f"the horizon is not reaching the uncertainty at all",
        )
    near, far = medians[ordered[0]], medians[ordered[-1]]
    if far < near:
        _fail(
            provider,
            f"band at h={ordered[-1]} (median relative width {far:.4f}) is NARROWER than at "
            f"h={ordered[0]} ({near:.4f}) — the band is inverted",
        )


def check_responds_to_input(provider: ForecastProvider, cases: Sequence[ProbeCase],
                            horizons: Sequence[int]) -> None:
    """Anti-vacuity: different (crop, mandi, day) must give different forecasts.

    A provider returning one constant everywhere passes every shape check ever
    written. This is the cheapest possible guard against that, and it is exactly
    the failure mode that cost us Round 1.
    """
    if len(cases) < 2:
        return
    horizon = int(max(horizons))
    medians = {
        provider.predict_quantiles(c.commodity_id, c.mandi_id, c.as_of, horizons)[horizon].p50
        for c in cases
    }
    if len(medians) < 2:
        _fail(provider, f"returns the same p50 ({medians}) for {len(cases)} different inputs")


# ══════════════════════════════════════════════════════════════════════════
# the whole suite
# ══════════════════════════════════════════════════════════════════════════

def assert_provider_contract(
    provider: ForecastProvider,
    cases: Sequence[ProbeCase],
    *,
    unknown: ProbeCase,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
) -> None:
    """Run every clause. This is what a provider's test module calls.

    `cases` should be real (crop, mandi, date) triples with enough history;
    `unknown` should be one the provider genuinely cannot answer.
    """
    if not cases:
        raise ContractViolation("the contract suite needs at least one probe case")
    horizons = [int(h) for h in horizons]

    check_identity(provider)
    check_shape(provider, cases, horizons)
    check_ordering(provider, cases, horizons)
    check_determinism(provider, cases, horizons)
    check_horizon_subset(provider, cases[0], horizons)
    check_unknown_raises(provider, unknown)
    check_uncertainty_grows(provider, cases, horizons)
    check_responds_to_input(provider, cases, horizons)


__all__ = [
    "ContractViolation",
    "ProbeCase",
    "Quantiles",
    "assert_provider_contract",
    "check_determinism",
    "check_horizon_subset",
    "check_identity",
    "check_ordering",
    "check_responds_to_input",
    "check_shape",
    "check_uncertainty_grows",
    "check_unknown_raises",
]
