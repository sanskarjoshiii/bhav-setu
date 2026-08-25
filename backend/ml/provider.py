"""Phase A0 — which forecaster is live, decided by config alone.

    from ml.provider import get_provider
    band = get_provider().predict_quantiles(commodity_id, mandi_id, as_of)[7]

`config/model.yaml` names the active provider. Swap day is that one line:

    provider: baseline     ->     provider: lightgbm

Providers are resolved lazily from a "module:attribute" string, so importing
this module never imports LightGBM, and the API can start on a machine where
the model artefacts do not exist yet.
"""

from __future__ import annotations

import importlib
import threading
from typing import Callable

from core.config import settings
from core.errors import ConfigError, ProviderNotAvailable
from ml.port import ForecastProvider

_lock = threading.Lock()
_cache: dict[str, ForecastProvider] = {}

#: name -> factory, registered in-process. Tests use this; production uses YAML.
_overrides: dict[str, Callable[[], ForecastProvider]] = {}


def _configured_paths() -> dict[str, str]:
    try:
        paths = settings.model.providers.to_dict()
    except ConfigError as exc:
        raise ConfigError(
            "config/model.yaml has no 'providers' block — Phase A0 adds it"
        ) from exc
    return {str(k): str(v) for k, v in paths.items()}


def active_provider_name() -> str:
    """The provider named in config/model.yaml. Read this for logging, not for branching."""
    return str(settings.model.provider)


def register_provider(name: str, factory: Callable[[], ForecastProvider]) -> None:
    """Register a provider in-process, overriding the YAML path for `name`.

    For tests and for the contract suite. Production code should not call this —
    a provider chosen in Python rather than in YAML is a provider that cannot be
    swapped without a deploy.
    """
    with _lock:
        _overrides[name] = factory
        _cache.pop(name, None)


def _load(name: str) -> ForecastProvider:
    if name in _overrides:
        return _overrides[name]()

    paths = _configured_paths()
    if name not in paths:
        raise ProviderNotAvailable(
            f"unknown forecast provider {name!r}. "
            f"config/model.yaml lists: {sorted(paths)}"
        )
    target = paths[name]
    if ":" not in target:
        raise ConfigError(
            f"provider path for {name!r} must be 'module:attribute', got {target!r}"
        )
    module_name, attribute = target.split(":", 1)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ProviderNotAvailable(
            f"forecast provider {name!r} is configured but not built yet "
            f"({target} — {exc}). Set 'provider:' in config/model.yaml to one that exists."
        ) from exc
    try:
        factory = getattr(module, attribute)
    except AttributeError as exc:
        raise ProviderNotAvailable(
            f"{module_name} has no attribute {attribute!r} for provider {name!r}"
        ) from exc
    return factory()


def get_provider(name: str | None = None) -> ForecastProvider:
    """The active provider, built once per process.

    Providers load model artefacts and warm caches, so they are expensive to
    build and cheap to reuse. They must therefore be stateless per call —
    two requests share one instance.
    """
    resolved = name or active_provider_name()
    cached = _cache.get(resolved)
    if cached is not None:
        return cached
    with _lock:
        cached = _cache.get(resolved)
        if cached is None:
            cached = _load(resolved)
            _cache[resolved] = cached
    return cached


def reset_provider_cache() -> None:
    """Drop cached instances. Tests use this after promoting a new model version."""
    with _lock:
        _cache.clear()
