"""One-line structured logging. Rule 11: every external call is logged as a single line."""

from __future__ import annotations

import json
import sys
import time
from typing import Any


def configure_stdout_utf8() -> None:
    """Windows consoles default to cp1252, which cannot print ₹, ✅ or Marathi.

    Call once at the top of any entry point that prints user-facing text.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _emit(level: str, event: str, fields: dict[str, Any]) -> None:
    payload: dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "level": level,
        "event": event,
    }
    payload.update(fields)
    line = " ".join(f"{k}={_fmt(v)}" for k, v in payload.items())
    stream = sys.stderr if level in ("WARN", "ERROR") else sys.stdout
    print(line, file=stream, flush=True)


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    text = str(value)
    return f'"{text}"' if " " in text else text


def info(event: str, **fields: Any) -> None:
    _emit("INFO", event, fields)


def warn(event: str, **fields: Any) -> None:
    _emit("WARN", event, fields)


def error(event: str, **fields: Any) -> None:
    _emit("ERROR", event, fields)


def external_call(url: str, status: int | str, rows: int | None = None, **fields: Any) -> None:
    """Rule 11: log every external call with URL, status and row count."""
    _emit("INFO", "external_call", {"url": url, "status": status, "rows": rows, **fields})
