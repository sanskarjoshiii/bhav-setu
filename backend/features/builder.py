"""Phase 3.2 — build_features(): the one function training and serving both call.

There is no second version. If serving needs something different, this changes.

Point-in-time correctness is enforced in exactly one place — `_slice()` — which
every group function is fed from, and which raises `LeakageError` if a row newer
than `as_of` ever reaches a feature window.

The single documented exception is `rain_forecast_7d`: weather rows flagged
`is_forecast` deliberately look forward, because a 7-day rain forecast genuinely
was available on the day. Nothing else may.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from core.config import settings
from core.errors import FeatureSetMismatch, InsufficientData, LeakageError
from features.registry import (
    ARRIVAL_LAGS,
    ARRIVAL_MA_WINDOW,
    CATEGORICAL_FEATURES,
    EXTREME_WINDOW,
    FEATURE_NAMES,
    FORECAST_WINDOW,
    IMPUTED_SHARE_WINDOW,
    MA_REFERENCE_WINDOW,
    PRICE_LAGS,
    RAIN_WINDOWS,
    ROLL_MEAN_WINDOWS,
    ROLL_STD_WINDOWS,
    TMAX_WINDOW,
)

_F = settings.app.features
MIN_OBSERVATIONS: int = int(_F.min_observations)
NEIGHBOUR_K: int = int(_F.neighbour_k)
NEIGHBOUR_STALENESS_DAYS: int = int(_F.neighbour_staleness_days)
ELASTICITY_WINDOW: int = int(_F.elasticity_window)
MOMENTUM_WINDOW: int = int(_F.momentum_window)
SEASONAL_WEEK_HALFWIDTH: int = int(_F.seasonal_week_halfwidth)
FESTIVAL_HORIZON_DAYS: int = int(_F.festival_horizon_days)
LIQUIDITY_WINDOW_DAYS: int = int(_F.liquidity_window_days)
DATA_QUALITY_WINDOW_DAYS: int = int(_F.data_quality_window_days)
UNSEASONAL_RAIN_MM_7D: float = float(_F.unseasonal_rain_mm_7d)
MONSOON_MONTHS: frozenset[int] = frozenset(int(m) for m in _F.monsoon_months)
LOOKBACK_DAYS: int = int(settings.app.history_lookback_days)


# ══════════════════════════════════════════════════════════════════════════
# loading
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class HistoryCache:
    """Every series for one commodity, loaded once and sliced per as_of date.

    The training matrix asks for ~4,000 feature rows over the same five series;
    re-querying per row would take minutes. The cache holds the *full* history —
    slicing to `obs_date <= as_of` is `_slice()`'s job and happens on every read,
    so cached and uncached calls follow identical code.
    """

    commodity_id: int
    prices: dict[int, pd.DataFrame]
    weather: dict[int, pd.DataFrame]
    festivals: pd.DataFrame
    shocks: pd.DataFrame
    commodity: dict[str, Any]
    mandi_ids: list[int]

    @classmethod
    def load(cls, conn: Connection, commodity_id: int) -> "HistoryCache":
        commodity = conn.execute(
            text(
                "SELECT id, name, perishability_class, shelf_life_days "
                "FROM commodities WHERE id = :c"
            ),
            {"c": commodity_id},
        ).mappings().first()
        if commodity is None:
            raise InsufficientData(f"commodity {commodity_id} does not exist")

        prices = _frame(
            conn,
            "SELECT mandi_id, obs_date, modal_price, min_price, max_price, "
            "       arrival_qtl, is_imputed "
            "FROM price_observations WHERE commodity_id = :c ORDER BY obs_date",
            {"c": commodity_id},
            numeric=("modal_price", "min_price", "max_price", "arrival_qtl"),
        )
        weather = _frame(
            conn,
            "SELECT mandi_id, obs_date, rainfall_mm, tmax_c, tmin_c, is_forecast "
            "FROM weather_daily ORDER BY obs_date",
            {},
            numeric=("rainfall_mm", "tmax_c", "tmin_c"),
        )
        festivals = _frame(
            conn,
            "SELECT fest_date AS obs_date, name, "
            "       coalesce((demand_effect->>'vegetable')::float, 0) AS demand_effect "
            "FROM festivals ORDER BY fest_date",
            {},
            numeric=("demand_effect",),
        )
        shocks = _frame(
            conn,
            "SELECT event_date AS obs_date, direction, magnitude, decay_days "
            "FROM shock_events WHERE commodity_id = :c ORDER BY event_date",
            {"c": commodity_id},
            numeric=("direction", "magnitude", "decay_days"),
        )
        mandi_ids = list(
            conn.execute(text("SELECT id FROM mandis WHERE active ORDER BY id")).scalars().all()
        )

        return cls(
            commodity_id=commodity_id,
            prices={mid: g.reset_index(drop=True) for mid, g in prices.groupby("mandi_id")}
            if not prices.empty
            else {},
            weather={mid: g.reset_index(drop=True) for mid, g in weather.groupby("mandi_id")}
            if not weather.empty
            else {},
            festivals=festivals,
            shocks=shocks,
            commodity=dict(commodity),
            mandi_ids=[int(m) for m in mandi_ids],
        )

    def price_series(self, mandi_id: int) -> pd.DataFrame:
        return self.prices.get(int(mandi_id), _empty_price_frame())

    def weather_series(self, mandi_id: int) -> pd.DataFrame:
        return self.weather.get(int(mandi_id), _empty_weather_frame())


def _frame(conn: Connection, sql: str, params: Mapping[str, Any],
           numeric: Iterable[str] = ()) -> pd.DataFrame:
    rows = [dict(r) for r in conn.execute(text(sql), dict(params)).mappings()]
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["obs_date"] = pd.to_datetime(frame["obs_date"])
    for column in numeric:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _empty_price_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["mandi_id", "obs_date", "modal_price", "min_price",
                 "max_price", "arrival_qtl", "is_imputed"]
    )


def _empty_weather_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["mandi_id", "obs_date", "rainfall_mm", "tmax_c", "tmin_c", "is_forecast"]
    )


# ══════════════════════════════════════════════════════════════════════════
# point-in-time gate — the only place a series is cut
# ══════════════════════════════════════════════════════════════════════════

def _dates(frame: pd.DataFrame) -> np.ndarray:
    return frame["obs_date"].to_numpy(dtype="datetime64[ns]")


def _sorted_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    """The frame in date order plus its date array. Sorts only if it has to."""
    dates = _dates(frame)
    if dates.size > 1 and not bool(np.all(dates[:-1] <= dates[1:])):
        frame = frame.sort_values("obs_date").reset_index(drop=True)
        dates = _dates(frame)
    return frame, dates


def _slice(frame: pd.DataFrame, as_of: pd.Timestamp, *, label: str) -> pd.DataFrame:
    """Rows at or before as_of, in date order. Raises LeakageError if that fails.

    PLAN 3.3 asks for an assert; this raises instead, because `python -O` strips
    asserts and a silent leak is the one bug that would invalidate every number
    we show a judge.

    The cut is a contiguous positional slice found by binary search — Phase 7
    runs this hundreds of thousands of times and a boolean mask rebuilds the
    whole frame every call.
    """
    if frame.empty:
        return frame
    frame, dates = _sorted_frame(frame)
    edge = np.datetime64(as_of, "ns")
    end = int(np.searchsorted(dates, edge, side="right"))
    if end and dates[end - 1] > edge:
        raise LeakageError(f"LEAKAGE: future data in feature window ({label}, as_of={as_of.date()})")
    return frame.iloc[:end]


def _at(values: pd.Series, index: pd.DatetimeIndex, when: pd.Timestamp) -> float:
    """Last value at or before `when`; NaN if the series starts later.

    A binary search on the already-sorted index — `_slice()` guarantees the sort.
    Phase 7 calls this hundreds of thousands of times, so it must not rebuild a
    Series per lookup.
    """
    if len(values) == 0:
        return float("nan")
    position = int(index.searchsorted(when, side="right")) - 1
    if position < 0:
        return float("nan")
    value = float(np.asarray(values, dtype=float)[position])
    return value if np.isfinite(value) else float("nan")


def _window_start(dates: np.ndarray, as_of: pd.Timestamp, days: int) -> int:
    """First position inside the trailing `days`-day window ending at as_of."""
    cutoff = np.datetime64(as_of - pd.Timedelta(days=days), "ns")
    return int(np.searchsorted(dates, cutoff, side="right"))


def _window(frame: pd.DataFrame, as_of: pd.Timestamp, days: int) -> pd.DataFrame:
    """The trailing `days`-day calendar window ending on as_of, inclusive.

    Callers always pass a frame that has already been through `_slice()`, so the
    window is the tail of the frame and a positional slice is enough.
    """
    if frame.empty:
        return frame
    return frame.iloc[_window_start(_dates(frame), as_of, days):]


# ══════════════════════════════════════════════════════════════════════════
# A. price history
# ══════════════════════════════════════════════════════════════════════════

def price_features(series: pd.DataFrame, as_of: pd.Timestamp) -> dict[str, float]:
    out: dict[str, float] = {}
    dates = _dates(series)
    index = pd.DatetimeIndex(dates)
    log_price = np.log(series["modal_price"].astype(float))

    now = _at(log_price, index, as_of)
    for k in PRICE_LAGS:
        then = _at(log_price, index, as_of - pd.Timedelta(days=k))
        out[f"lag_{k}"] = now - then

    for w in ROLL_MEAN_WINDOWS:
        window = _window(series, as_of, w)
        out[f"roll_mean_{w}"] = (
            float(np.log(window["modal_price"].astype(float)).mean()) if len(window) else float("nan")
        )

    # Volatility, not the level: "prices have been swinging a lot this month" is
    # the standard deviation of daily log-returns, which is what Phase 4's
    # explanation template for roll_std_30 promises the farmer.
    returns = log_price.diff()
    for w in ROLL_STD_WINDOWS:
        sample = returns.iloc[_window_start(dates, as_of, w):]
        out[f"roll_std_{w}"] = float(sample.std()) if sample.notna().sum() >= 2 else float("nan")

    out["price_vs_ma30"] = now - out[f"roll_mean_{MA_REFERENCE_WINDOW}"]

    extremes = _window(series, as_of, EXTREME_WINDOW)
    if len(extremes):
        max_date = extremes.loc[extremes["modal_price"].idxmax(), "obs_date"]
        min_date = extremes.loc[extremes["modal_price"].idxmin(), "obs_date"]
        out[f"days_since_max_{EXTREME_WINDOW}"] = float((as_of - max_date).days)
        out[f"days_since_min_{EXTREME_WINDOW}"] = float((as_of - min_date).days)
    else:
        out[f"days_since_max_{EXTREME_WINDOW}"] = float("nan")
        out[f"days_since_min_{EXTREME_WINDOW}"] = float("nan")

    lo = series["min_price"].iat[-1]
    hi = series["max_price"].iat[-1]
    modal = series["modal_price"].iat[-1]
    out["spread_pct"] = (
        float((hi - lo) / modal) if pd.notna(lo) and pd.notna(hi) and modal else float("nan")
    )
    return out


# ══════════════════════════════════════════════════════════════════════════
# B. arrivals
# ══════════════════════════════════════════════════════════════════════════

def arrival_features(series: pd.DataFrame, as_of: pd.Timestamp) -> dict[str, float]:
    out: dict[str, float] = {}
    arrivals = pd.to_numeric(series["arrival_qtl"], errors="coerce")
    positive = series[arrivals > 0].copy()
    positive["log_arr"] = np.log(pd.to_numeric(positive["arrival_qtl"], errors="coerce"))

    if positive.empty:
        return {name: float("nan") for name in
                (*(f"arr_lag_{k}" for k in ARRIVAL_LAGS), "arr_vs_ma30",
                 "arr_zscore_seasonal", "arr_momentum", "price_arrival_elasticity")}

    index = pd.DatetimeIndex(positive["obs_date"])
    log_arr = positive["log_arr"]
    now = _at(log_arr, index, as_of)

    for k in ARRIVAL_LAGS:
        out[f"arr_lag_{k}"] = now - _at(log_arr, index, as_of - pd.Timedelta(days=k))

    ma_window = _window(positive, as_of, ARRIVAL_MA_WINDOW)
    out["arr_vs_ma30"] = (
        now - float(ma_window["log_arr"].mean()) if len(ma_window) else float("nan")
    )

    # Same week-of-year in every past year: is this a heavy arrival week or not?
    week = as_of.isocalendar().week
    weeks = positive["obs_date"].dt.isocalendar().week.astype(int)
    offset = (weeks - week).abs()
    seasonal = positive[(offset <= SEASONAL_WEEK_HALFWIDTH) | (offset >= 52 - SEASONAL_WEEK_HALFWIDTH)]
    if len(seasonal) >= 5:
        mean, std = float(seasonal["log_arr"].mean()), float(seasonal["log_arr"].std())
        out["arr_zscore_seasonal"] = (now - mean) / std if std and np.isfinite(std) else float("nan")
    else:
        out["arr_zscore_seasonal"] = float("nan")

    momentum = positive.tail(MOMENTUM_WINDOW)
    if len(momentum) >= 3:
        x = np.arange(len(momentum), dtype=float)
        out["arr_momentum"] = float(np.polyfit(x, momentum["log_arr"].to_numpy(dtype=float), 1)[0])
    else:
        out["arr_momentum"] = float("nan")

    out["price_arrival_elasticity"] = _elasticity(positive, as_of)
    return out


def _elasticity(positive: pd.DataFrame, as_of: pd.Timestamp) -> float:
    """Rolling OLS slope of Δlog price on Δlog arrivals — the demand curve, locally.

    A strongly negative value means this market punishes heavy arrivals, which is
    exactly when holding a lot back pays.
    """
    window = positive.tail(ELASTICITY_WINDOW)
    if len(window) < 10:
        return float("nan")
    d_price = np.log(window["modal_price"].astype(float)).diff()
    d_arr = window["log_arr"].diff()
    both = pd.concat([d_price, d_arr], axis=1).dropna()
    if len(both) < 10:
        return float("nan")
    x = both.iloc[:, 1].to_numpy(dtype=float)
    y = both.iloc[:, 0].to_numpy(dtype=float)
    variance = float(np.var(x))
    if variance <= 0 or not np.isfinite(variance):
        return float("nan")
    return float(np.cov(x, y, bias=True)[0, 1] / variance)


# ══════════════════════════════════════════════════════════════════════════
# C. cross-mandi
# ══════════════════════════════════════════════════════════════════════════

def cross_mandi_features(cache: HistoryCache, mandi_id: int, as_of: pd.Timestamp,
                         own_modal: float) -> dict[str, float]:
    neighbour_prices: list[float] = []
    neighbour_arr_changes: list[float] = []

    others = [m for m in cache.mandi_ids if int(m) != int(mandi_id)][:NEIGHBOUR_K]
    for other in others:
        series = _slice(cache.price_series(other), as_of, label=f"neighbour {other}")
        if series.empty:
            continue
        if (as_of - series["obs_date"].iat[-1]).days > NEIGHBOUR_STALENESS_DAYS:
            continue          # a stale neighbour is noise, not a signal
        neighbour_prices.append(float(series["modal_price"].iat[-1]))

        arrivals = pd.to_numeric(series["arrival_qtl"], errors="coerce")
        positive = series[arrivals > 0]
        if len(positive) >= 2:
            index = pd.DatetimeIndex(_dates(positive))
            log_arr = np.log(pd.to_numeric(positive["arrival_qtl"], errors="coerce"))
            change = _at(log_arr, index, as_of) - _at(log_arr, index, as_of - pd.Timedelta(days=7))
            if np.isfinite(change):
                neighbour_arr_changes.append(change)

    if not neighbour_prices:
        return {"nbr_price_mean_k4": float("nan"),
                "price_vs_nbr": float("nan"),
                "nbr_arr_change": float("nan")}

    mean_price = float(np.mean(neighbour_prices))
    return {
        "nbr_price_mean_k4": mean_price,
        "price_vs_nbr": float(np.log(own_modal / mean_price))
        if own_modal > 0 and mean_price > 0 else float("nan"),
        "nbr_arr_change": float(np.mean(neighbour_arr_changes))
        if neighbour_arr_changes else float("nan"),
    }


# ══════════════════════════════════════════════════════════════════════════
# D. calendar
# ══════════════════════════════════════════════════════════════════════════

def calendar_features(as_of: pd.Timestamp, festivals: pd.DataFrame,
                      crop: Mapping[str, Any]) -> dict[str, float]:
    """Festivals and harvest windows are published years ahead — no leakage here."""
    out: dict[str, float] = {
        "dow": float(as_of.weekday()),
        "month": float(as_of.month),
        "week_of_year": float(as_of.isocalendar().week),
    }

    if not festivals.empty:
        start = int(np.searchsorted(_dates(festivals), np.datetime64(as_of, "ns"), side="left"))
        upcoming = festivals.iloc[start:]
    else:
        upcoming = festivals
    if not upcoming.empty:
        days = int((upcoming["obs_date"].iat[0] - as_of).days)
        within = days <= FESTIVAL_HORIZON_DAYS
        out["days_to_festival"] = float(min(days, FESTIVAL_HORIZON_DAYS))
        out["festival_demand_effect"] = (
            float(upcoming["demand_effect"].iat[0]) if within else 0.0
        )
    else:
        out["days_to_festival"] = float(FESTIVAL_HORIZON_DAYS)
        out["festival_demand_effect"] = 0.0

    out["harvest_season_flag"] = float(_in_harvest_season(as_of, crop))
    return out


def _in_harvest_season(as_of: pd.Timestamp, crop: Mapping[str, Any]) -> bool:
    """config/crops.yaml windows are MM-DD, so they wrap across the new year."""
    seasons = crop.get("seasons") or {}
    seasons = seasons.to_dict() if hasattr(seasons, "to_dict") else dict(seasons)
    stamp = (as_of.month, as_of.day)
    for window in seasons.values():
        spec = window.to_dict() if hasattr(window, "to_dict") else dict(window)
        start = tuple(int(p) for p in str(spec["harvest_start"]).split("-"))
        end = tuple(int(p) for p in str(spec["harvest_end"]).split("-"))
        inside = start <= stamp <= end if start <= end else (stamp >= start or stamp <= end)
        if inside:
            return True
    return False


# ══════════════════════════════════════════════════════════════════════════
# E. weather
# ══════════════════════════════════════════════════════════════════════════

def weather_features(weather: pd.DataFrame, as_of: pd.Timestamp) -> dict[str, float]:
    out: dict[str, float] = {}
    if weather.empty:
        return {name: float("nan") for name in
                (*(f"rain_{w}d_sum" for w in RAIN_WINDOWS),
                 f"rain_forecast_{FORECAST_WINDOW}d", f"tmax_{TMAX_WINDOW}d_mean")} | {
            "unseasonal_rain_flag": float("nan")
        }

    is_forecast = weather["is_forecast"].astype(bool)
    actual = _slice(weather[~is_forecast], as_of, label="weather")

    for w in RAIN_WINDOWS:
        window = _window(actual, as_of, w)
        out[f"rain_{w}d_sum"] = float(window["rainfall_mm"].sum()) if len(window) else float("nan")

    tmax_window = _window(actual, as_of, TMAX_WINDOW)
    out[f"tmax_{TMAX_WINDOW}d_mean"] = (
        float(tmax_window["tmax_c"].mean()) if len(tmax_window) else float("nan")
    )

    # The one legitimate forward-looking feature: a 7-day rain forecast really was
    # on the table that morning. Historical dates have no stored forecast, so this
    # is NaN when training on the past — LightGBM handles that natively.
    horizon = weather[
        is_forecast
        & (weather["obs_date"] > as_of)
        & (weather["obs_date"] <= as_of + pd.Timedelta(days=FORECAST_WINDOW))
    ]
    out[f"rain_forecast_{FORECAST_WINDOW}d"] = (
        float(horizon["rainfall_mm"].sum()) if len(horizon) else float("nan")
    )

    rain_7d = out.get(f"rain_{RAIN_WINDOWS[0]}d_sum", float("nan"))
    out["unseasonal_rain_flag"] = (
        float(rain_7d > UNSEASONAL_RAIN_MM_7D and as_of.month not in MONSOON_MONTHS)
        if np.isfinite(rain_7d) else float("nan")
    )
    return out


# ══════════════════════════════════════════════════════════════════════════
# F. shock
# ══════════════════════════════════════════════════════════════════════════

def shock_features(shocks: pd.DataFrame, as_of: pd.Timestamp) -> dict[str, float]:
    """Decayed sums:  Σ magnitude × exp(−(as_of − event_date) / τ),  τ = decay_days/3."""
    past = _slice(shocks, as_of, label="shocks")
    if past.empty:
        return {"shock_active_bearish": 0.0,
                "shock_active_bullish": 0.0,
                "days_since_shock": float("nan")}

    age_days = (as_of - past["obs_date"]).dt.days.astype(float)
    tau = past["decay_days"].astype(float) / 3.0
    weight = past["magnitude"].astype(float) * np.exp(-age_days / tau.replace(0.0, np.nan))
    direction = past["direction"].astype(float)

    return {
        "shock_active_bearish": float(weight[direction < 0].sum()),
        "shock_active_bullish": float(weight[direction > 0].sum()),
        "days_since_shock": float(age_days.min()),
    }


# ══════════════════════════════════════════════════════════════════════════
# G + H. entity and guards
# ══════════════════════════════════════════════════════════════════════════

def entity_features(series: pd.DataFrame, as_of: pd.Timestamp, mandi_id: int,
                    commodity_id: int, commodity: Mapping[str, Any]) -> dict[str, float]:
    liquidity_window = _window(series, as_of, LIQUIDITY_WINDOW_DAYS)
    quality_window = _window(series, as_of, DATA_QUALITY_WINDOW_DAYS)
    arrivals = pd.to_numeric(liquidity_window["arrival_qtl"], errors="coerce").dropna()
    perishability = commodity.get("perishability_class")

    return {
        "mandi_id": float(mandi_id),
        "commodity_id": float(commodity_id),
        "perishability_class": float(perishability) if perishability is not None else float("nan"),
        "mandi_liquidity": float(arrivals.mean()) if len(arrivals) else float("nan"),
        "mandi_data_quality": float(1.0 - quality_window["is_imputed"].astype(bool).mean())
        if len(quality_window) else float("nan"),
    }


def guard_features(series: pd.DataFrame, as_of: pd.Timestamp) -> dict[str, float]:
    """How stale and how patched is the evidence behind this row?"""
    recent = _window(series, as_of, IMPUTED_SHARE_WINDOW)
    return {
        "days_since_observation": float((as_of - series["obs_date"].iat[-1]).days),
        "imputed_share_14d": float(recent["is_imputed"].astype(bool).mean())
        if len(recent) else float("nan"),
    }


# ══════════════════════════════════════════════════════════════════════════
# the public entry point
# ══════════════════════════════════════════════════════════════════════════

def build_features(as_of: date, mandi_id: int, commodity_id: int,
                   conn: Connection, cache: HistoryCache | None = None) -> dict[str, float]:
    """Point-in-time correct. Uses ONLY rows with obs_date <= as_of.

    Used by training, backtesting AND serving. There is no other version.
    Raises InsufficientData if fewer than 60 real observations in the lookback.
    """
    stamp = pd.Timestamp(as_of)
    cache = cache or HistoryCache.load(conn, commodity_id)

    full = cache.price_series(mandi_id)
    series = _slice(full, stamp, label=f"prices mandi={mandi_id}")
    lookback = _window(series, stamp, LOOKBACK_DAYS)
    real_rows = int((~lookback["is_imputed"].astype(bool)).sum()) if len(lookback) else 0
    if real_rows < MIN_OBSERVATIONS:
        raise InsufficientData(
            f"mandi {mandi_id} / commodity {commodity_id} has {real_rows} real observations "
            f"in the {LOOKBACK_DAYS}-day window before {stamp.date()}; "
            f"{MIN_OBSERVATIONS} are required",
            needed=MIN_OBSERVATIONS,
            found=real_rows,
        )

    own_modal = float(series["modal_price"].iat[-1])
    crop = _crop_config(cache.commodity.get("name", ""))

    values: dict[str, float] = {}
    values.update(price_features(series, stamp))
    values.update(arrival_features(series, stamp))
    values.update(cross_mandi_features(cache, mandi_id, stamp, own_modal))
    values.update(calendar_features(stamp, cache.festivals, crop))
    values.update(weather_features(cache.weather_series(mandi_id), stamp))
    values.update(shock_features(cache.shocks, stamp))
    values.update(entity_features(series, stamp, mandi_id, commodity_id, cache.commodity))
    values.update(guard_features(series, stamp))

    return _finalise(values)


def _finalise(values: dict[str, float]) -> dict[str, float]:
    """Exactly FEATURE_NAMES, in order, finite-or-NaN. Never ±inf.

    An infinity would survive training and then blow up a prediction in front of
    a judge; NaN is a value LightGBM understands.
    """
    missing = [name for name in FEATURE_NAMES if name not in values]
    extra = [name for name in values if name not in FEATURE_NAMES]
    if missing or extra:
        raise FeatureSetMismatch(
            f"feature set does not match the registry — missing={missing} unexpected={extra}"
        )
    ordered: dict[str, float] = {}
    for name in FEATURE_NAMES:
        value = float(values[name])
        ordered[name] = float("nan") if not np.isfinite(value) else value
    return ordered


def _crop_config(commodity_name: str) -> Mapping[str, Any]:
    crops = settings.crops.to_dict()
    for key, spec in crops.items():
        if key.lower() == str(commodity_name).lower():
            return spec.to_dict() if hasattr(spec, "to_dict") else dict(spec)
    return {}


def current_price(as_of: date, mandi_id: int, commodity_id: int, conn: Connection,
                  cache: HistoryCache | None = None) -> float:
    """Latest modal price at or before as_of. Phase 4 inverts log-returns with it."""
    stamp = pd.Timestamp(as_of)
    cache = cache or HistoryCache.load(conn, commodity_id)
    series = _slice(cache.price_series(mandi_id), stamp, label=f"prices mandi={mandi_id}")
    if series.empty:
        raise InsufficientData(
            f"no price for mandi {mandi_id} / commodity {commodity_id} on or before {stamp.date()}"
        )
    return float(series["modal_price"].iat[-1])


def feature_frame(rows: list[dict[str, float]]) -> pd.DataFrame:
    """Feature dicts -> a DataFrame with registry column order and categorical dtypes."""
    frame = pd.DataFrame(rows, columns=FEATURE_NAMES)
    for column in CATEGORICAL_FEATURES:
        frame[column] = frame[column].astype("category")
    return frame
