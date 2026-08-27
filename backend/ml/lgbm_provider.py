"""Phase B2 — the trained model, wrapped so it satisfies `ForecastProvider`.

This file is the entire swap. Everything downstream — the decision engine, the
API, the website, the WhatsApp agent — reaches a forecast through
`get_provider()`, so promoting the model means editing one line in
config/model.yaml and restarting. Nothing here may be imported by a router or by
the agent; if it is, Phase A0 was violated and swap day becomes a refactor.

Three rules, all of them enforced by tests written back in Phase A0 —
`tests/test_phaseA0_port.py --provider lightgbm` runs the *same file* that
passed for the baseline, unmodified:

  1. **Sort before returning.** p10, p50 and p90 are three independently fitted
     boosters. They cross — routinely, on ordinary rows. An unsorted band does
     not raise; it silently inverts the decision engine's downside term, and the
     recommendation flips from "hold" to "sell now" for the wrong reason.

  2. **One feature path.** The row is built by `build_serving_row()`, the same
     entry point `dataset.py` trains through, and the manifest's recorded column
     order is checked against the live registry before anything is predicted. A
     model served on a drifted column order does not crash — it just gets
     quietly, unfixably worse, which is the failure mode you find in production
     and never in tests.

  3. **Refuse, do not extrapolate.** An unknown crop, or one with too little
     history, raises `InsufficientData`. Returning a confident number for a crop
     we know nothing about is the one failure a judge will find on stage.

The model predicts a **log return**, not a price. `_to_price()` is where that is
undone, and it is the only place the conversion happens.
"""

from __future__ import annotations

import math
import threading
from datetime import date
from pathlib import Path
from typing import Sequence

import numpy as np

from core import logging as log
from core.config import settings
from core.db import get_conn
from core.errors import ForecastContractError, InsufficientData, ModelNotFound
from features.registry import FEATURE_NAMES
from ml import registry
from ml.port import (
    DEFAULT_HORIZONS,
    Forecast,
    Quantiles,
    build_serving_row,
    to_price,
    validate_forecast,
)

#: Which trained version to serve. `active` follows `model_registry.is_active`,
#: so a promotion takes effect on restart without a config edit.
VERSION_SETTING: str = str(settings.model.get("serve_version", "active"))

class LgbmProvider:
    """The trained quantile model, behind the port.

    Boosters are loaded once and cached — reloading 12 files per request would
    dominate the latency budget the API has to hit.
    """

    #: The key this provider is registered under in config/model.yaml. The
    #: contract suite requires it, and the accuracy page prints it next to the
    #: version so a viewer can tell a baseline number from a model number.
    name = "lightgbm"

    def __init__(self, version: str | None = None) -> None:
        self._lock = threading.Lock()
        self._boosters: dict[tuple[int, str], object] = {}
        self._manifest: registry.Manifest | None = None
        self._version: str | None = version

    # ── loading ───────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_version() -> str:
        """Which version to serve. Reads `model_registry`, so never at import time."""
        if VERSION_SETTING != "active":
            return VERSION_SETTING
        row = registry.active()
        if not row:
            raise ModelNotFound(
                "no active model in model_registry. Train and promote one:\n"
                "  python scripts/train.py --from 2022-01-01 --promote"
            )
        return str(row["version"])

    @property
    def version(self) -> str:
        """Resolved on first use, not in `__init__`.

        Constructing a provider must stay cheap and side-effect free. The API
        builds one through `get_provider()` while wiring up its routes, and a
        constructor that opened a database connection there would make startup
        depend on Postgres being reachable before the first request is served.
        """
        if self._version is None:
            self._version = self._resolve_version()
        return self._version

    def _load(self) -> None:
        """Load the 12 boosters and check the manifest against the live registry."""
        if self._boosters:
            return
        with self._lock:
            if self._boosters:               # another thread won the race
                return

            import lightgbm as lgb          # local: keeps LightGBM off the API import path

            manifest = registry.load_manifest(self.version)

            # Rule 2. Column order is a contract, and this is where it is checked.
            if list(manifest.feature_names) != list(FEATURE_NAMES):
                raise ForecastContractError(
                    f"model {self.version} was trained on a different feature order "
                    f"than features/registry.py now defines "
                    f"({len(manifest.feature_names)} vs {len(FEATURE_NAMES)} columns). "
                    f"Retrain, or restore the registry — do not serve this."
                )

            directory = registry.version_dir(self.version)
            loaded: dict[tuple[int, str], object] = {}
            for horizon in manifest.horizons:
                for key in manifest.quantiles:
                    path = directory / registry.booster_name(horizon, key)
                    if not path.exists():
                        raise ModelNotFound(f"missing booster {path}")
                    loaded[(int(horizon), key)] = lgb.Booster(model_file=str(path))

            self._manifest = manifest
            self._boosters = loaded
            log.info("lgbm_provider_loaded", version=self.version,
                     boosters=len(loaded), horizons=manifest.horizons)

    # ── prediction ────────────────────────────────────────────────────────

    def _to_price(self, price_now: float, log_return: float) -> float:
        """Undo the training label, through the same helper the trainer scores with."""
        price = to_price(price_now, log_return)
        if not math.isfinite(price):
            raise InsufficientData("model returned a non-finite prediction")
        return price

    def predict_quantiles(
        self,
        commodity_id: int,
        mandi_id: int,
        as_of: date,
        horizons: Sequence[int] = DEFAULT_HORIZONS,
    ) -> Forecast:
        self._load()
        assert self._manifest is not None
        wanted = [int(h) for h in horizons]

        missing = [h for h in wanted if (h, next(iter(self._manifest.quantiles)))
                   not in self._boosters]
        if missing:
            raise InsufficientData(
                f"model {self.version} was not trained for horizon(s) {missing}; "
                f"it has {self._manifest.horizons}"
            )

        # Rule 3 — build_serving_row raises InsufficientData for a crop with too
        # little history, and we let it through rather than predicting anyway.
        with get_conn() as conn:
            row = build_serving_row(as_of, mandi_id, commodity_id, conn)
            price_now = _current_price(conn, as_of, mandi_id, commodity_id)

        vector = row.vector.reshape(1, -1)
        result: dict[int, Quantiles] = {}
        for horizon in wanted:
            prices: list[float] = []
            for key in self._manifest.quantiles:
                booster = self._boosters[(horizon, key)]
                prediction = float(np.asarray(booster.predict(vector)).ravel()[0])
                prices.append(self._to_price(price_now, prediction))
            # Rule 1 — sort. Quantiles.of does it, but doing it here as well
            # makes the intent impossible to remove by accident.
            low, mid, high = sorted(prices)
            result[horizon] = Quantiles.of(low, mid, high)

        return validate_forecast(result, wanted)


def _current_price(conn, as_of: date, mandi_id: int, commodity_id: int) -> float:
    """Today's modal price — the anchor a log return is applied to."""
    from features.builder import current_price

    return float(current_price(as_of, mandi_id, commodity_id, conn))


def build() -> LgbmProvider:
    """Factory referenced by `config/model.yaml → providers.lightgbm`."""
    return LgbmProvider()
