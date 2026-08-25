"""Phase A3 acceptance — the baseline forecaster.

Run:  make check-phaseA3

The headline test is `test_baseline_satisfies_the_full_contract`: it runs
`tests/contract_forecast.py` — the same file, unmodified — that Phase B2 will run
against LightGBM. Passing it means the same thing before and after swap day.

Everything else here is either the maths (metrics, baselines) or the properties
that make the bands honest. Three of these tests exist because they FAILED first
and changed the implementation:

  * thin history was being reported as MORE certain than dense history
  * a bias correction made the baseline worse than plain naive
  * a flat forecast was scored 0% on direction, reading as "always wrong"
    rather than "never called"

No database. The provider's arithmetic is driven through `forecast_series()`, and
the DB path is exercised by a fake loader.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Sequence

import numpy as np
import pytest

from core.errors import InsufficientData
from ml import baselines, metrics
from ml.baseline_provider import MIN_HISTORY_DAYS, MIN_RESIDUALS, BaselineProvider
from ml.port import DEFAULT_HORIZONS, ForecastProvider, Quantiles
from tests.contract_forecast import ProbeCase, assert_provider_contract

pytestmark = pytest.mark.phaseA3


# ══════════════════════════════════════════════════════════════════════════
# synthetic series — how mandi prices actually behave
# ══════════════════════════════════════════════════════════════════════════

def random_walk(n: int = 400, start: float = 1800.0, sigma: float = 0.018,
                weekly: float = 0.03, seed: int = 11) -> np.ndarray:
    """A log random walk with a weekly wobble.

    Not decoration: daily mandi prices are close to a random walk, and testing a
    forecaster against a smooth periodic curve would flatter every method that
    assumes structure. The weekly term is there because market days are real.
    """
    rng = np.random.default_rng(seed)
    level = start * np.exp(np.cumsum(rng.normal(0.0, sigma, n)))
    t = np.arange(n)
    return level * (1.0 + weekly * np.sin(2.0 * np.pi * t / 7.0))


def mean_reverting(n: int = 400, centre: float = 1800.0, seed: int = 3) -> np.ndarray:
    """An Ornstein-Uhlenbeck-ish series: error does NOT grow with horizon."""
    rng = np.random.default_rng(seed)
    out = np.empty(n)
    value = centre
    for i in range(n):
        value += 0.35 * (centre - value) + rng.normal(0.0, 60.0)
        out[i] = value
    return out


# ══════════════════════════════════════════════════════════════════════════
# 1. metrics — written before either forecaster, on purpose
# ══════════════════════════════════════════════════════════════════════════

def test_pinball_is_zero_for_a_perfect_forecast():
    truth = [100.0, 200.0, 300.0]
    assert metrics.pinball_loss(truth, truth, 0.5) == pytest.approx(0.0)


def test_pinball_punishes_an_optimistic_p10_nine_times_harder():
    """The asymmetry is the reason we quote a band at all.

    A p10 quoted too high is the error that ruins a farmer with a loan; a
    symmetric metric would score both misses the same and never notice.
    """
    truth = [100.0]
    too_high = metrics.pinball_loss(truth, [110.0], 0.10)   # predicted above truth
    too_low = metrics.pinball_loss(truth, [90.0], 0.10)     # predicted below truth
    assert too_high == pytest.approx(9.0 * too_low)


def test_pinball_p90_punishes_the_other_direction():
    truth = [100.0]
    assert metrics.pinball_loss(truth, [90.0], 0.90) == pytest.approx(
        9.0 * metrics.pinball_loss(truth, [110.0], 0.90)
    )


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.1, 1.5])
def test_pinball_rejects_a_quantile_outside_the_open_unit_interval(bad):
    with pytest.raises(ValueError):
        metrics.pinball_loss([100.0], [100.0], bad)


def test_picp_counts_the_share_inside_the_band():
    truth = [100.0, 200.0, 300.0, 400.0]
    low = [90.0, 190.0, 350.0, 390.0]     # third one falls outside
    high = [110.0, 210.0, 380.0, 410.0]
    assert metrics.picp(truth, low, high) == pytest.approx(0.75)


def test_picp_treats_the_boundary_as_covered():
    assert metrics.picp([100.0], [100.0], [110.0]) == pytest.approx(1.0)


def test_interval_width_is_relative_when_a_reference_is_given():
    assert metrics.mean_interval_width([90.0], [110.0], [100.0]) == pytest.approx(0.2)
    assert metrics.mean_interval_width([90.0], [110.0]) == pytest.approx(20.0)


def test_directional_accuracy_ignores_flat_outcomes():
    """No move means there was no direction to call — counting it inflates the score."""
    now = [100.0, 100.0, 100.0]
    truth = [110.0, 90.0, 100.0]          # third did not move
    prediction = [105.0, 95.0, 999.0]     # third would be 'wrong' if counted
    assert metrics.directional_accuracy(now, truth, prediction) == pytest.approx(1.0)


def test_directional_accuracy_is_nan_when_nothing_moved():
    assert math.isnan(metrics.directional_accuracy([100.0], [100.0], [110.0]))


def test_a_flat_forecast_makes_no_directional_call():
    """A naive forecast says "same as today". That is not a wrong call, it is no
    call — scoring it 0% read as "always wrong" instead of "never asked"."""
    assert math.isnan(metrics.directional_accuracy([100.0, 100.0], [110.0, 90.0],
                                                   [100.0, 100.0]))


def test_directional_accuracy_scores_only_the_rows_where_a_call_was_made():
    now = [100.0, 100.0, 100.0]
    truth = [110.0, 90.0, 120.0]
    prediction = [105.0, 100.0, 130.0]      # middle row: no call
    assert metrics.directional_accuracy(now, truth, prediction) == pytest.approx(1.0)


def test_mape_drops_zero_truth_rows_rather_than_dividing_by_zero():
    assert metrics.mape([0.0, 100.0], [50.0, 110.0]) == pytest.approx(10.0)


def test_metrics_ignore_missing_values_pairwise():
    assert metrics.mae([100.0, float("nan"), 300.0], [110.0, 200.0, 290.0]) == pytest.approx(10.0)


def test_metrics_reject_mismatched_lengths():
    with pytest.raises(ValueError):
        metrics.mae([1.0, 2.0], [1.0])


def test_skill_score_is_positive_only_when_the_candidate_wins():
    assert metrics.skill_score(8.0, 10.0) == pytest.approx(0.2)
    assert metrics.skill_score(12.0, 10.0) == pytest.approx(-0.2)


def test_score_horizon_returns_every_field_the_registry_stores():
    series = random_walk(60)
    truth, p50 = series[30:], series[30:] * 1.01
    result = metrics.score_horizon(truth, p50 * 0.95, p50, p50 * 1.05, price_now=series[29:-1])
    for key in ("pinball_p10", "pinball_p50", "pinball_p90", "pinball_mean",
                "picp", "mape", "mae", "rmse", "n_scored", "directional_accuracy"):
        assert key in result and np.isfinite(result[key]), key


# ══════════════════════════════════════════════════════════════════════════
# 2. the four baselines
# ══════════════════════════════════════════════════════════════════════════

def test_naive_is_the_last_value_at_every_horizon():
    series = [100.0, 110.0, 105.0]
    assert all(baselines.naive(series, h) == 105.0 for h in DEFAULT_HORIZONS)


def test_seasonal_naive_returns_the_same_phase_of_the_cycle():
    """With period 7: h=7 is today, h=1 is six days ago."""
    series = list(range(100, 121))          # 21 values, last is 120
    assert baselines.seasonal_naive(series, 7, period=7) == 120.0
    assert baselines.seasonal_naive(series, 1, period=7) == 114.0
    assert baselines.seasonal_naive(series, 14, period=7) == 120.0


def test_seasonal_naive_falls_back_rather_than_wrapping_around():
    """Too short to reach the same phase: use the oldest value, do not pretend."""
    assert baselines.seasonal_naive([100.0, 101.0], 1, period=7) == 100.0


def test_drift_extends_the_line_through_first_and_last():
    series = [100.0, 110.0, 120.0]          # slope 10 per step
    assert baselines.drift(series, 1) == pytest.approx(130.0)
    assert baselines.drift(series, 3) == pytest.approx(150.0)


def test_drift_on_a_single_point_is_flat():
    assert baselines.drift([100.0], 5) == 100.0


def test_moving_average_uses_the_last_window_only():
    series = [0.0] * 10 + [100.0] * 7
    assert baselines.moving_average(series, 1, window=7) == pytest.approx(100.0)


def test_moving_average_shrinks_the_window_on_short_history():
    assert baselines.moving_average([100.0, 200.0], 1, window=7) == pytest.approx(150.0)


def test_every_baseline_ignores_non_finite_values():
    series = [100.0, float("nan"), 110.0]
    for method in baselines.METHODS:
        assert np.isfinite(baselines.predict(method, series, 1))


def test_an_empty_series_raises_rather_than_returning_zero():
    for method in baselines.METHODS:
        with pytest.raises(InsufficientData):
            baselines.predict(method, [], 1)


def test_unknown_method_names_itself_and_the_alternatives():
    with pytest.raises(ValueError, match="unknown baseline"):
        baselines.predict("prophet", [100.0], 1)


def test_the_benchmark_is_the_dumbest_method_not_the_best():
    """Phase B3's claim is "beats the dumbest thing that works", without an asterisk."""
    assert baselines.BENCHMARK == "naive"


# ══════════════════════════════════════════════════════════════════════════
# 3. rolling residuals — the leakage-free bit the bands rest on
# ══════════════════════════════════════════════════════════════════════════

def test_residuals_never_use_information_from_their_own_future():
    """Change the tail; residuals from earlier cut-offs must not move.

    If they do, the band is being computed from data the forecast could not have
    seen, and every coverage number downstream is fiction.
    """
    series = random_walk(120)
    before = baselines.rolling_residuals(series, 3, "naive")

    tampered = series.copy()
    tampered[-10:] *= 3.0
    after = baselines.rolling_residuals(tampered, 3, "naive")

    shared = len(before) - 10
    assert shared > 20
    np.testing.assert_allclose(before[:shared], after[:shared])


def test_residual_count_falls_as_the_horizon_grows():
    series = random_walk(100)
    counts = [baselines.rolling_residuals(series, h, "naive").size for h in (1, 7, 15)]
    assert counts == sorted(counts, reverse=True)


def test_a_perfect_flat_series_has_zero_residuals_for_naive():
    assert np.allclose(baselines.rolling_residuals([500.0] * 40, 1, "naive"), 0.0)


def test_evaluate_methods_scores_all_four():
    profiles = baselines.evaluate_methods(random_walk(120), 3)
    assert set(profiles) == set(baselines.METHODS)
    assert all(profiles[m]["n"] > 0 for m in profiles)


def test_the_winner_is_chosen_per_series_not_by_taste():
    """A random walk should favour naive; a noisy flat series should favour the mean.

    That the answer differs between the two is the point — a single hard-coded
    method would be right for one of them and quietly wrong for the other.
    """
    walk = baselines.best_method(baselines.evaluate_methods(random_walk(300), 1))
    rng = np.random.default_rng(5)
    noisy_flat = 1800.0 + rng.normal(0.0, 120.0, 300)
    flat = baselines.best_method(baselines.evaluate_methods(noisy_flat, 1))
    assert walk == "naive"
    assert flat == "moving_average"
    assert walk != flat


def test_best_method_falls_back_to_the_benchmark_when_nothing_scores():
    empty = {m: {"mae": float("nan"), "n": 0.0} for m in baselines.METHODS}
    assert baselines.best_method(empty) == baselines.BENCHMARK


# ══════════════════════════════════════════════════════════════════════════
# 4. the provider's bands
# ══════════════════════════════════════════════════════════════════════════

def test_bands_are_built_from_measured_errors_not_a_formula():
    provider = BaselineProvider()
    provider.forecast_series(random_walk(300), DEFAULT_HORIZONS)
    assert all(b.empirical for b in provider.last_basis), provider.explain_last()
    assert all(b.residuals >= MIN_RESIDUALS for b in provider.last_basis)


def test_bands_widen_with_horizon_on_a_random_walk():
    provider = BaselineProvider()
    result = provider.forecast_series(random_walk(400), DEFAULT_HORIZONS)
    widths = [result[h].relative_width for h in sorted(result)]
    assert widths[-1] > widths[0], widths


def test_thin_history_is_not_reported_more_confidently_than_dense_history():
    """The property that makes the stub honest — and it does NOT come for free.

    Reading the 10th percentile straight off thirty residuals produced a
    *narrower* band than four hundred residuals gave, i.e. the crops we know
    least about looked the most certain. `tail_levels()` is the fix. This test
    is what caught it, so it is written the way the property is actually true:
    on the median across many series, not on one lucky draw.
    """
    provider = BaselineProvider()
    ratios = []
    for seed in range(30):
        full = random_walk(400, seed=seed)
        dense = provider.forecast_series(full, [7])[7].relative_width
        thin = provider.forecast_series(full[-45:], [7])[7].relative_width
        ratios.append(thin / dense)

    median_ratio = float(np.median(ratios))
    assert median_ratio > 1.0, (
        f"thin history is reported as MORE certain than dense history "
        f"(median width ratio {median_ratio:.3f}) — false confidence on the crops "
        f"we know least about"
    )
    # Deliberately no per-series floor. A short window that happens to cover a
    # calm stretch has genuinely had smaller errors, and quoting a tighter band
    # for it is right, not a bug — volatility clusters. What must not happen is
    # the *systematic* version of it, which the median above catches. The pure
    # sample-size half of the effect is pinned by the next test.


def test_the_tail_correction_relaxes_as_evidence_accumulates():
    """Conservative when we know little, near-exact when we know a lot."""
    from ml.baseline_provider import tail_levels

    thin_lo, thin_hi = tail_levels(30)
    dense_lo, dense_hi = tail_levels(1000)
    assert thin_lo < dense_lo < 0.10, (thin_lo, dense_lo)
    assert thin_hi > dense_hi > 0.90, (thin_hi, dense_hi)
    assert dense_lo == pytest.approx(0.10, abs=0.02), "still conservative with 1000 residuals"


def test_too_few_residuals_falls_back_to_a_wide_band_and_says_so():
    provider = BaselineProvider()
    provider.forecast_series(random_walk(20), [15])
    basis = provider.last_basis[0]
    assert basis.empirical is False
    assert basis.residuals < MIN_RESIDUALS


def test_a_trend_is_handled_by_method_choice_not_by_a_bias_bolt_on():
    """On a rising series the answer is to pick `drift`, not to nudge `naive` up.

    We built the bias-corrected version first — p50 = point + median past error —
    and measured it worse than plain naive at two of four horizons. On a random
    walk the historical median error is statistically significant and
    predictively worthless. Trend is a job for the method choice, and `drift` is
    already a candidate; bolting a second trend model onto another method's
    output double-counts it.
    """
    series = np.arange(200, dtype=float) * 5.0 + 1000.0     # exactly +5/day
    provider = BaselineProvider()
    result = provider.forecast_series(series, [3])[3]

    assert provider.last_basis[0].method == "drift"
    assert result.p50 == pytest.approx(series[-1] + 15.0, abs=0.5)


def test_the_p50_is_the_point_forecast_untouched():
    """No hidden adjustment between the chosen method and what a farmer is shown."""
    provider = BaselineProvider()
    result = provider.forecast_series(random_walk(300, seed=8), DEFAULT_HORIZONS)
    for basis in provider.last_basis:
        assert result[basis.horizon].p50 == pytest.approx(basis.point)


def test_a_degenerate_band_is_floored_rather_than_reported_as_certainty():
    """A flat stretch gives identical residuals. Zero width would tell the
    decision engine there is no downside, and it would hold everything."""
    provider = BaselineProvider()
    result = provider.forecast_series(np.full(200, 1500.0), [7])[7]
    assert result.width > 0
    assert result.p10 < result.p50 < result.p90


def test_quantiles_are_always_ordered_across_many_random_series():
    provider = BaselineProvider()
    for seed in range(25):
        result = provider.forecast_series(random_walk(150, seed=seed), DEFAULT_HORIZONS)
        for horizon, band in result.items():
            assert band.p10 <= band.p50 <= band.p90, (seed, horizon, band)
            assert band.p10 > 0


def test_a_mean_reverting_series_keeps_a_roughly_flat_band():
    """Honest behaviour, and the reason the contract does not demand growth:
    for a mean-reverting series the 15-day error really is like the 1-day error."""
    provider = BaselineProvider()
    result = provider.forecast_series(mean_reverting(400), DEFAULT_HORIZONS)
    widths = [result[h].relative_width for h in sorted(result)]
    assert max(widths) / min(widths) < 2.0, widths


# ══════════════════════════════════════════════════════════════════════════
# 5. refusing to answer
# ══════════════════════════════════════════════════════════════════════════

class FakeHistoryProvider(BaselineProvider):
    """BaselineProvider with the database replaced by a dict of series."""

    def __init__(self, series_by_key: dict[tuple[int, int], np.ndarray]) -> None:
        super().__init__()
        self._series = series_by_key

    def _load_history(self, commodity_id, mandi_id, as_of):  # type: ignore[override]
        series = self._series.get((int(commodity_id), int(mandi_id)))
        if series is None:
            return np.asarray([], dtype=float)
        # honour the as_of cut-off the way the real SQL does
        return series[: min(len(series), (as_of - date(2024, 1, 1)).days + 1)]


def _provider_with_data() -> FakeHistoryProvider:
    return FakeHistoryProvider({
        (1, 1): random_walk(500, start=1860.0, seed=1),
        (1, 2): random_walk(500, start=1795.0, seed=2),
        (2, 1): random_walk(500, start=1240.0, seed=3),
        (2, 2): random_walk(500, start=2310.0, seed=4),
    })


def test_a_crop_with_no_history_raises_instead_of_answering():
    """The clause that keeps an invented price off a farmer's screen."""
    provider = _provider_with_data()
    with pytest.raises(InsufficientData):
        provider.predict_quantiles(-1, -1, date(2025, 1, 1), DEFAULT_HORIZONS)


def test_a_crop_with_too_little_history_raises_and_says_how_much_it_needs():
    provider = FakeHistoryProvider({(1, 1): random_walk(500)})
    with pytest.raises(InsufficientData) as exc:
        provider.predict_quantiles(1, 1, date(2024, 1, 10), DEFAULT_HORIZONS)
    assert exc.value.needed == MIN_HISTORY_DAYS
    assert exc.value.found is not None and exc.value.found < MIN_HISTORY_DAYS


def test_the_history_cut_off_is_respected():
    """Point-in-time correctness: an earlier as_of must see a shorter series."""
    provider = FakeHistoryProvider({(1, 1): random_walk(500)})
    early = provider.predict_quantiles(1, 1, date(2024, 6, 1), [7])[7]
    late = provider.predict_quantiles(1, 1, date(2025, 1, 1), [7])[7]
    assert early.p50 != late.p50


# ══════════════════════════════════════════════════════════════════════════
# 6. THE contract — the same file Phase B2 runs against LightGBM
# ══════════════════════════════════════════════════════════════════════════

CASES: list[ProbeCase] = [
    ProbeCase(1, 1, date(2025, 3, 14), "onion @ mandi 1"),
    ProbeCase(1, 2, date(2025, 3, 14), "onion @ mandi 2"),
    ProbeCase(2, 1, date(2025, 3, 14), "potato @ mandi 1"),
    ProbeCase(2, 2, date(2025, 3, 14), "potato @ mandi 2"),
]
UNKNOWN = ProbeCase(-1, -1, date(2025, 3, 14), "a crop with no history at all")


def test_baseline_satisfies_the_full_contract():
    """The headline. `tests/contract_forecast.py`, unmodified, is swap day's gate."""
    assert_provider_contract(_provider_with_data(), CASES, unknown=UNKNOWN)


def test_baseline_is_recognised_as_a_forecast_provider():
    assert isinstance(BaselineProvider(), ForecastProvider)


def test_the_provider_is_registered_under_the_configured_name():
    from core.config import settings

    paths = settings.model.providers.to_dict()
    assert paths["baseline"].startswith("ml.baseline_provider:")
    assert BaselineProvider.name == "baseline"
    assert BaselineProvider.version == str(settings.model.baseline.version)


def test_repeated_calls_return_identical_objects():
    """Two pages must not show a farmer two numbers for the same lot."""
    provider = _provider_with_data()
    first = provider.predict_quantiles(1, 1, date(2025, 3, 14), DEFAULT_HORIZONS)
    provider.clear_cache()
    second = provider.predict_quantiles(1, 1, date(2025, 3, 14), DEFAULT_HORIZONS)
    assert first == second


# ══════════════════════════════════════════════════════════════════════════
# 7. is the baseline actually any good?
# ══════════════════════════════════════════════════════════════════════════

def _backtest(provider: BaselineProvider, series: np.ndarray, horizon: int,
              cuts: Sequence[int]) -> dict[str, float]:
    truth, p10, p50, p90, now = [], [], [], [], []
    for cut in cuts:
        band = provider.forecast_series(series[:cut], [horizon])[horizon]
        truth.append(series[cut + horizon - 1])
        now.append(series[cut - 1])
        p10.append(band.p10)
        p50.append(band.p50)
        p90.append(band.p90)
    return metrics.score_horizon(truth, p10, p50, p90, price_now=now)


def test_the_band_covers_about_eighty_percent_of_outcomes():
    """PICP is the honesty check. Phase B3 requires 0.72-0.88 of the trained
    model; the baseline it has to beat should already be in that neighbourhood,
    or 'beating it' would mean beating something broken."""
    series = random_walk(500, seed=21)
    provider = BaselineProvider()
    scored = _backtest(provider, series, 7, range(200, 480, 4))
    assert 0.65 <= scored["picp"] <= 0.95, scored["picp"]


def test_the_baseline_beats_a_useless_forecast():
    """Anti-vacuity for the stub itself.

    Its job is to be a real opponent, not a straw man. If it cannot beat "quote
    the long-run average and ignore today", then Phase B3's gate would be
    trivial to clear and would prove nothing about the trained model.
    """
    series = random_walk(500, seed=33)
    provider = BaselineProvider()
    cuts = list(range(200, 480, 4))
    scored = _backtest(provider, series, 7, cuts)

    long_run_mean = float(np.mean(series[:200]))
    truth = [series[c + 6] for c in cuts]
    useless = metrics.mae(truth, [long_run_mean] * len(cuts))

    assert scored["mae"] < useless, f"baseline {scored['mae']:.1f} vs mean {useless:.1f}"


@pytest.mark.parametrize("horizon", [1, 3, 7, 15])
def test_the_composite_never_loses_badly_to_plain_naive(horizon):
    """The guard that caught the two design mistakes in this module.

    The composite picks a method per series, so it *can* lose to plain naive
    when a challenger wins on rolling error and then fails on the outcome —
    that is honest selection noise and `switch_margin` bounds it. What must not
    happen is losing *materially*: a benchmark that limps makes Phase B3's gate
    meaningless, because LightGBM would clear it without being good.

    The bound is deliberately loose. Tightening it against synthetic random-walk
    data would just tune the module toward "always naive", which is right for a
    random walk and wrong for real mandi prices.
    """
    provider = BaselineProvider()
    series = random_walk(500, seed=33)
    cuts = list(range(200, 500 - horizon + 1, 4))

    truth = [series[c + horizon - 1] for c in cuts]
    composite = [provider.forecast_series(series[:c], [horizon])[horizon].p50 for c in cuts]
    plain = [baselines.naive(series[:c], horizon) for c in cuts]

    assert metrics.mae(truth, composite) <= 1.20 * metrics.mae(truth, plain), (
        f"h={horizon}: composite {metrics.mae(truth, composite):.1f} vs "
        f"naive {metrics.mae(truth, plain):.1f}"
    )


def test_the_bands_are_not_absurdly_wide():
    """The other half of PICP: a band from zero to infinity covers everything."""
    provider = BaselineProvider()
    result = provider.forecast_series(random_walk(400, seed=44), DEFAULT_HORIZONS)
    for horizon, band in result.items():
        assert band.relative_width < 0.60, (horizon, band.relative_width)
