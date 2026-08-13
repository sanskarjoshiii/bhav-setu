"""Phase 3 acceptance: one feature function, point-in-time correct.

Run:  make check-phase3
Requires the database from Phase 1 and the data from `make backfill`.

The leakage test is the important one. It is what guarantees the number a judge
sees on stage was produced the same way as the number in the metrics table.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from core.config import settings
from core.db import get_conn
from core.errors import FeatureSetMismatch, InsufficientData
from features import builder
from features.builder import (
    FESTIVAL_HORIZON_DAYS,
    HistoryCache,
    _finalise,
    _in_harvest_season,
    _slice,
    arrival_features,
    build_features,
    calendar_features,
    price_features,
    shock_features,
    weather_features,
)
from features.registry import (
    CATEGORICAL_FEATURES,
    FEATURE_GROUPS,
    FEATURE_NAMES,
    LABEL_COLUMN,
    META_COLUMNS,
)
from ml.dataset import _price_at, load_or_build

pytestmark = pytest.mark.phase3

EXPECTED_FEATURE_COUNT: int = 45
MIN_MATRIX_ROWS: int = 3000


def _price_frame(dates: list[str], modal: list[float],
                 arrivals: list[float] | None = None, **extra: Any) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "mandi_id": 1,
            "obs_date": pd.to_datetime(dates),
            "modal_price": modal,
            "min_price": [m * 0.9 for m in modal],
            "max_price": [m * 1.1 for m in modal],
            "arrival_qtl": arrivals if arrivals is not None else [500.0] * len(modal),
            "is_imputed": False,
        }
    )
    for key, value in extra.items():
        frame[key] = value
    return frame


def _differences(a: dict[str, float], b: dict[str, float]) -> list[str]:
    """Feature names whose values differ, treating NaN == NaN."""
    differing = []
    for name in a:
        x, y = a[name], b[name]
        if math.isnan(x) and math.isnan(y):
            continue
        if x != y:
            differing.append(name)
    return differing


# ══════════════════════════════════════════════════════════════════════════
# registry — no database
# ══════════════════════════════════════════════════════════════════════════

def test_registry_has_no_duplicates_and_a_stable_count() -> None:
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES))
    assert len(FEATURE_NAMES) == EXPECTED_FEATURE_COUNT, (
        f"feature count changed to {len(FEATURE_NAMES)} — every saved model is keyed "
        f"to this list, so retrain after changing it"
    )
    assert sum(len(group) for group in FEATURE_GROUPS.values()) == len(FEATURE_NAMES)


def test_categorical_features_are_real_features() -> None:
    assert set(CATEGORICAL_FEATURES) <= set(FEATURE_NAMES)
    assert not set(META_COLUMNS) & set(FEATURE_NAMES), "a label must never be a feature"
    assert LABEL_COLUMN in META_COLUMNS


def test_finalise_orders_and_kills_infinities() -> None:
    values = {name: 1.0 for name in FEATURE_NAMES}
    values["spread_pct"] = float("inf")
    values["lag_1"] = float("-inf")
    out = _finalise(values)
    assert list(out) == FEATURE_NAMES
    assert math.isnan(out["spread_pct"]) and math.isnan(out["lag_1"])


def test_finalise_rejects_a_feature_set_that_drifted_from_the_registry() -> None:
    with pytest.raises(FeatureSetMismatch):
        _finalise({name: 1.0 for name in FEATURE_NAMES[:-1]})
    with pytest.raises(FeatureSetMismatch):
        _finalise({**{name: 1.0 for name in FEATURE_NAMES}, "made_up": 1.0})


# ══════════════════════════════════════════════════════════════════════════
# point-in-time — no database
# ══════════════════════════════════════════════════════════════════════════

def test_slice_drops_everything_after_as_of() -> None:
    frame = _price_frame(
        [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-01-01", periods=20)],
        [1500.0] * 20,
    )
    cut = _slice(frame, pd.Timestamp("2024-01-10"), label="test")
    assert cut["obs_date"].max() == pd.Timestamp("2024-01-10")
    assert len(cut) == 8


def test_price_features_are_blind_to_rows_after_as_of() -> None:
    """A 6x jump the day after as_of must not move a single feature."""
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-01-01", periods=60)]
    modal = [1500.0] * 40 + [9000.0] * 20
    as_of = pd.Timestamp(dates[39])
    full = _price_frame(dates, modal)

    with_future = price_features(_slice(full, as_of, label="t"), as_of)
    without_future = price_features(_slice(full.iloc[:40], as_of, label="t"), as_of)
    assert not _differences(with_future, without_future)


def test_price_features_compute_the_expected_numbers() -> None:
    # calendar days, so "one day ago" is unambiguous
    dates = [d.strftime("%Y-%m-%d") for d in pd.date_range("2024-03-01", periods=45)]
    modal = [1000.0 * (1.01 ** i) for i in range(45)]
    as_of = pd.Timestamp(dates[-1])
    out = price_features(_price_frame(dates, modal), as_of)

    assert out["lag_1"] == pytest.approx(math.log(1.01), rel=1e-6)
    assert out["lag_3"] == pytest.approx(3 * math.log(1.01), rel=1e-6)
    assert out["days_since_max_90"] == 0.0, "the latest price is the highest"
    assert out["days_since_min_90"] > 0
    assert out["spread_pct"] == pytest.approx(0.2, rel=1e-6)
    assert out["price_vs_ma30"] > 0, "a rising series must sit above its own mean"


def test_arrival_elasticity_is_negative_when_gluts_depress_prices() -> None:
    rng = np.random.default_rng(7)
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-01-01", periods=70)]
    log_arrivals = 6.0 + rng.normal(0, 0.25, size=70)
    arrivals = np.exp(log_arrivals)
    modal = np.exp(8.0 - 0.6 * (log_arrivals - 6.0))     # more arrivals -> lower price
    out = arrival_features(
        _price_frame(dates, list(modal), list(arrivals)), pd.Timestamp(dates[-1])
    )
    assert out["price_arrival_elasticity"] < -0.2


def test_shock_decay_matches_the_formula() -> None:
    as_of = pd.Timestamp("2024-01-31")
    shocks = pd.DataFrame(
        {
            "obs_date": pd.to_datetime(["2024-01-01", "2024-01-21", "2024-02-10"]),
            "direction": [-1, 1, -1],
            "magnitude": [3, 2, 3],
            "decay_days": [45, 30, 45],
        }
    )
    out = shock_features(shocks, as_of)

    expected_bearish = 3 * math.exp(-30 / (45 / 3))
    expected_bullish = 2 * math.exp(-10 / (30 / 3))
    assert out["shock_active_bearish"] == pytest.approx(expected_bearish)
    assert out["shock_active_bullish"] == pytest.approx(expected_bullish)
    assert out["days_since_shock"] == 10.0, "the February event is in the future"


def test_shock_features_are_zero_when_nothing_has_happened() -> None:
    out = shock_features(pd.DataFrame(columns=["obs_date", "direction", "magnitude",
                                               "decay_days"]), pd.Timestamp("2024-01-31"))
    assert out["shock_active_bearish"] == 0.0
    assert out["shock_active_bullish"] == 0.0
    assert math.isnan(out["days_since_shock"])


def test_weather_forecast_feature_ignores_actual_future_rows() -> None:
    """Only `is_forecast` rows may look forward. Real future rain would be leakage."""
    as_of = pd.Timestamp("2024-06-10")
    weather = pd.DataFrame(
        {
            "mandi_id": 1,
            "obs_date": pd.to_datetime(
                ["2024-06-08", "2024-06-09", "2024-06-10", "2024-06-12", "2024-06-13"]
            ),
            "rainfall_mm": [10.0, 5.0, 3.0, 500.0, 40.0],
            "tmax_c": [34.0, 35.0, 36.0, 30.0, 31.0],
            "tmin_c": [24.0, 25.0, 26.0, 22.0, 23.0],
            "is_forecast": [False, False, False, False, True],
        }
    )
    out = weather_features(weather, as_of)
    assert out["rain_7d_sum"] == pytest.approx(18.0), "future actuals must not be summed"
    assert out["rain_forecast_7d"] == pytest.approx(40.0), "only the forecast row counts"
    assert out["tmax_7d_mean"] == pytest.approx(35.0)


def test_unseasonal_rain_flag_respects_the_monsoon() -> None:
    def frame(when: str, mm: float) -> pd.DataFrame:
        return pd.DataFrame(
            {"mandi_id": 1, "obs_date": pd.to_datetime([when]), "rainfall_mm": [mm],
             "tmax_c": [33.0], "tmin_c": [22.0], "is_forecast": [False]}
        )

    assert weather_features(frame("2024-01-15", 90.0),
                            pd.Timestamp("2024-01-15"))["unseasonal_rain_flag"] == 1.0
    assert weather_features(frame("2024-07-15", 90.0),
                            pd.Timestamp("2024-07-15"))["unseasonal_rain_flag"] == 0.0


def test_harvest_season_windows_wrap_across_the_new_year() -> None:
    onion = settings.crops.onion.to_dict()
    assert _in_harvest_season(pd.Timestamp("2024-11-05"), onion) is True   # kharif
    assert _in_harvest_season(pd.Timestamp("2024-04-02"), onion) is True   # rabi
    assert _in_harvest_season(pd.Timestamp("2024-08-01"), onion) is False

    wrapping = {"seasons": {"winter": {"harvest_start": "12-01", "harvest_end": "02-15"}}}
    assert _in_harvest_season(pd.Timestamp("2024-01-10"), wrapping) is True
    assert _in_harvest_season(pd.Timestamp("2024-06-10"), wrapping) is False


def test_days_to_festival_is_capped_not_unbounded() -> None:
    festivals = pd.DataFrame(
        {"obs_date": pd.to_datetime(["2025-11-01"]), "name": ["Diwali"], "demand_effect": [1.0]}
    )
    far = calendar_features(pd.Timestamp("2024-01-01"), festivals, {})
    near = calendar_features(pd.Timestamp("2025-10-22"), festivals, {})
    assert far["days_to_festival"] == float(FESTIVAL_HORIZON_DAYS)
    assert far["festival_demand_effect"] == 0.0
    assert near["days_to_festival"] == 10.0
    assert near["festival_demand_effect"] == 1.0


def test_label_lookup_respects_the_tolerance() -> None:
    index = pd.DatetimeIndex(pd.to_datetime(["2024-01-01", "2024-01-05", "2024-01-20"]))
    values = np.array([1000.0, 1100.0, 1200.0])
    hit = _price_at(index, values, pd.Timestamp("2024-01-06"), 2)
    assert hit is not None and hit[0] == 1100.0
    assert _price_at(index, values, pd.Timestamp("2024-01-10"), 2) is None
    assert _price_at(index, values, pd.Timestamp("2023-12-01"), 2) is None


# ══════════════════════════════════════════════════════════════════════════
# acceptance — these read the real database
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def target() -> dict[str, Any]:
    """The mandi with the densest history, and its last observation date."""
    with get_conn() as conn:
        row = conn.execute(
            text(
                "SELECT mandi_id, commodity_id, max(obs_date) AS last_date, count(*) AS n "
                "FROM price_observations GROUP BY mandi_id, commodity_id "
                "ORDER BY n DESC LIMIT 1"
            )
        ).mappings().first()
    assert row is not None, "price_observations is empty — run make backfill"
    return dict(row)


def test_build_features_returns_the_registry_exactly(target: dict[str, Any]) -> None:
    with get_conn() as conn:
        features = build_features(
            target["last_date"], target["mandi_id"], target["commodity_id"], conn
        )
    assert list(features) == FEATURE_NAMES
    assert len(features) == len(FEATURE_NAMES)
    assert all(isinstance(v, float) for v in features.values())
    assert not any(math.isinf(v) for v in features.values())


def test_features_are_mostly_populated(target: dict[str, Any]) -> None:
    """A row that is 60% NaN means the joins are broken, not that data is scarce."""
    with get_conn() as conn:
        features = build_features(
            target["last_date"], target["mandi_id"], target["commodity_id"], conn
        )
    known = [k for k, v in features.items() if not math.isnan(v)]
    assert len(known) >= 0.7 * len(FEATURE_NAMES), (
        f"only {len(known)}/{len(FEATURE_NAMES)} features resolved: "
        f"missing {sorted(set(FEATURE_NAMES) - set(known))}"
    )


def test_no_leakage_when_future_rows_appear(target: dict[str, Any]) -> None:
    """as_of = D must give the same answer whether or not D+1 exists in the table."""
    as_of = target["last_date"]
    with get_conn() as conn:
        before = build_features(as_of, target["mandi_id"], target["commodity_id"], conn)

    insert = text(
        """
        INSERT INTO price_observations
            (obs_date, mandi_id, commodity_id, variety, grade,
             min_price, max_price, modal_price, arrival_qtl, source)
        VALUES (:d, :m, :c, '', '', 9000, 11000, 10000, 5, 'test_phase3')
        """
    )
    try:
        with get_conn() as conn:
            for offset in (1, 3, 5):
                conn.execute(insert, {"d": as_of + timedelta(days=offset),
                                      "m": target["mandi_id"], "c": target["commodity_id"]})
        with get_conn() as conn:
            planted = conn.execute(
                text("SELECT count(*) FROM price_observations WHERE source = 'test_phase3'")
            ).scalar()
            after = build_features(as_of, target["mandi_id"], target["commodity_id"], conn)
    finally:
        with get_conn() as conn:
            conn.execute(text("DELETE FROM price_observations WHERE source = 'test_phase3'"))

    assert planted == 3, "the leakage test did not actually plant future rows"
    differing = _differences(before, after)
    assert not differing, f"LEAKAGE: these features saw the future: {differing}"


def test_insufficient_data_raises_for_a_mandi_with_no_history(target: dict[str, Any]) -> None:
    with get_conn() as conn:
        with pytest.raises(InsufficientData):
            build_features(date(2005, 1, 1), target["mandi_id"], target["commodity_id"], conn)


def test_unknown_commodity_raises_rather_than_returning_none() -> None:
    with get_conn() as conn:
        with pytest.raises(InsufficientData):
            build_features(date.today(), 1, 999_999, conn)


def test_cached_and_uncached_paths_agree(target: dict[str, Any]) -> None:
    """The training matrix uses a cache; the API does not. They must not diverge."""
    with get_conn() as conn:
        cache = HistoryCache.load(conn, target["commodity_id"])
        cached = build_features(target["last_date"], target["mandi_id"],
                                target["commodity_id"], conn, cache=cache)
        direct = build_features(target["last_date"], target["mandi_id"],
                                target["commodity_id"], conn)
    assert not _differences(cached, direct)


@pytest.fixture(scope="module")
def matrix() -> pd.DataFrame:
    with get_conn() as conn:
        span = conn.execute(
            text("SELECT min(obs_date) AS lo, max(obs_date) AS hi FROM price_observations")
        ).mappings().one()
    assert span["lo"] is not None, "price_observations is empty — run make backfill"
    return load_or_build(span["lo"], span["hi"])


def test_training_matrix_is_big_enough(matrix: pd.DataFrame) -> None:
    assert len(matrix) >= MIN_MATRIX_ROWS, (
        f"only {len(matrix):,} rows; Phase 4 needs at least {MIN_MATRIX_ROWS:,}"
    )


def test_training_matrix_has_no_infinities(matrix: pd.DataFrame) -> None:
    numeric = matrix[FEATURE_NAMES].select_dtypes(include=[np.number])
    assert not np.isinf(numeric.to_numpy(dtype=float)).any()
    assert matrix[LABEL_COLUMN].notna().all()
    assert np.isfinite(matrix[LABEL_COLUMN].to_numpy(dtype=float)).all()


def test_training_matrix_columns_match_the_registry(matrix: pd.DataFrame) -> None:
    assert list(matrix.columns) == [*FEATURE_NAMES, *META_COLUMNS]


def test_labels_are_log_returns_of_the_stored_prices(matrix: pd.DataFrame) -> None:
    sample = matrix.sample(min(200, len(matrix)), random_state=3)
    expected = np.log(sample["price_target"] / sample["price_now"])
    assert np.allclose(sample[LABEL_COLUMN], expected)


def test_every_horizon_is_represented(matrix: pd.DataFrame) -> None:
    assert set(int(h) for h in matrix["horizon"].unique()) == set(settings.app.horizons)
