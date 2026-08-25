"""Typed exceptions. Rule 10: errors are loud — never return None on missing data."""

from __future__ import annotations


class BhavSetuError(Exception):
    """Base class for every error this project raises deliberately."""


class ConfigError(BhavSetuError):
    """A YAML file or an environment variable is missing or malformed."""


class InsufficientData(BhavSetuError):
    """Not enough real observations to build features / answer a question.

    The API layer converts this into a clear user-facing message rather than a 500.
    """

    def __init__(self, message: str, *, needed: int | None = None, found: int | None = None) -> None:
        super().__init__(message)
        self.needed = needed
        self.found = found


class IngestionError(BhavSetuError):
    """An upstream source failed or returned something we refuse to store."""


class EntityResolutionError(BhavSetuError):
    """A mandi or commodity name could not be resolved to an id."""


class ModelNotFound(BhavSetuError):
    """No active model version in the registry."""


class LeakageError(BhavSetuError):
    """Point-in-time correctness was violated. This must never be caught and ignored."""


class FeatureSetMismatch(BhavSetuError):
    """The features produced do not match features/registry.py exactly.

    Raised loudly because a model trained on one column order and served on
    another fails silently — it just gets quietly worse.
    """


class ProviderNotAvailable(BhavSetuError):
    """config/model.yaml names a forecast provider that is not built or importable.

    Phase A0 registers 'lightgbm' before it exists on purpose, so that the day
    the model lands the only change is the `provider:` line.
    """


class ForecastContractError(BhavSetuError):
    """A ForecastProvider returned something that violates ml/port.py.

    Unsorted quantiles, a missing horizon, a non-finite price. Loud on purpose:
    every one of these is silent everywhere downstream.
    """
