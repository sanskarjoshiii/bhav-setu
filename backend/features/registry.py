"""Phase 3.1 — the single source of truth for feature names and their order.

Everything downstream imports from here: the builder, the training matrix, the
LightGBM booster, SHAP, and the explanation templates. If a feature name appears
anywhere else as a bare string literal, that is a bug — the model would silently
train on one column order and serve on another.

Window sizes baked into a name (roll_mean_7, days_since_max_90) are constants
here, not YAML: renaming the window without renaming the feature would make every
saved model quietly wrong.
"""

from __future__ import annotations

# ── A. Price history ──────────────────────────────────────────────────────
PRICE_LAGS: tuple[int, ...] = (1, 3, 7, 14, 30)
ROLL_MEAN_WINDOWS: tuple[int, ...] = (7, 14, 30)
ROLL_STD_WINDOWS: tuple[int, ...] = (7, 30)
EXTREME_WINDOW: int = 90
MA_REFERENCE_WINDOW: int = 30

PRICE_FEATURES: tuple[str, ...] = (
    *(f"lag_{k}" for k in PRICE_LAGS),
    *(f"roll_mean_{w}" for w in ROLL_MEAN_WINDOWS),
    *(f"roll_std_{w}" for w in ROLL_STD_WINDOWS),
    "price_vs_ma30",
    f"days_since_max_{EXTREME_WINDOW}",
    f"days_since_min_{EXTREME_WINDOW}",
    "spread_pct",
)

# ── B. Arrivals — the leading indicator other teams ignore ────────────────
ARRIVAL_LAGS: tuple[int, ...] = (1, 3, 7)
ARRIVAL_MA_WINDOW: int = 30

ARRIVAL_FEATURES: tuple[str, ...] = (
    *(f"arr_lag_{k}" for k in ARRIVAL_LAGS),
    "arr_vs_ma30",
    "arr_zscore_seasonal",
    "arr_momentum",
    "price_arrival_elasticity",
)

# ── C. Cross-mandi ────────────────────────────────────────────────────────
CROSS_MANDI_FEATURES: tuple[str, ...] = (
    "nbr_price_mean_k4",
    "price_vs_nbr",
    "nbr_arr_change",
)

# ── D. Calendar ───────────────────────────────────────────────────────────
CALENDAR_FEATURES: tuple[str, ...] = (
    "dow",
    "month",
    "week_of_year",
    "days_to_festival",
    "festival_demand_effect",
    "harvest_season_flag",
)

# ── E. Weather ────────────────────────────────────────────────────────────
RAIN_WINDOWS: tuple[int, ...] = (7, 30)
FORECAST_WINDOW: int = 7
TMAX_WINDOW: int = 7

WEATHER_FEATURES: tuple[str, ...] = (
    *(f"rain_{w}d_sum" for w in RAIN_WINDOWS),
    f"rain_forecast_{FORECAST_WINDOW}d",
    f"tmax_{TMAX_WINDOW}d_mean",
    "unseasonal_rain_flag",
)

# ── F. Shock ──────────────────────────────────────────────────────────────
SHOCK_FEATURES: tuple[str, ...] = (
    "shock_active_bearish",
    "shock_active_bullish",
    "days_since_shock",
)

# ── G. Entity ─────────────────────────────────────────────────────────────
ENTITY_FEATURES: tuple[str, ...] = (
    "mandi_id",
    "commodity_id",
    "perishability_class",
    "mandi_liquidity",
    "mandi_data_quality",
)

# ── H. Guards — how much should we trust this row at all ──────────────────
GUARD_FEATURES: tuple[str, ...] = (
    "days_since_observation",
    "imputed_share_14d",
)
IMPUTED_SHARE_WINDOW: int = 14

FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "price": PRICE_FEATURES,
    "arrivals": ARRIVAL_FEATURES,
    "cross_mandi": CROSS_MANDI_FEATURES,
    "calendar": CALENDAR_FEATURES,
    "weather": WEATHER_FEATURES,
    "shock": SHOCK_FEATURES,
    "entity": ENTITY_FEATURES,
    "guards": GUARD_FEATURES,
}

FEATURE_NAMES: list[str] = [name for group in FEATURE_GROUPS.values() for name in group]

CATEGORICAL_FEATURES: list[str] = ["mandi_id", "commodity_id", "dow", "month"]

# Columns the training matrix carries alongside the features. They identify and
# label a row; they are never fed to the model.
LABEL_COLUMN: str = "y"
META_COLUMNS: list[str] = [
    "as_of",
    "horizon",
    "target_date",
    "price_now",
    "price_target",
    LABEL_COLUMN,
]

if len(set(FEATURE_NAMES)) != len(FEATURE_NAMES):
    duplicates = sorted({n for n in FEATURE_NAMES if FEATURE_NAMES.count(n) > 1})
    raise ValueError(f"duplicate feature name(s) in the registry: {duplicates}")

if not set(CATEGORICAL_FEATURES) <= set(FEATURE_NAMES):
    unknown = sorted(set(CATEGORICAL_FEATURES) - set(FEATURE_NAMES))
    raise ValueError(f"CATEGORICAL_FEATURES not in FEATURE_NAMES: {unknown}")
