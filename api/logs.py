"""Structured logging: one JSON object per event, correlated by turn.

Why this exists in the shape it does. `audit_turn` already records what a user asked and what
came back - that is the business record, and it is queryable. What was missing is the
*operational* record: which tool ran with which arguments, why the validator rejected a
figure, how long each leg took. Without it the only way to answer "what went wrong at 20:41"
is `docker logs | grep`, which loses the correlation between lines and cannot be aggregated.

Three decisions worth understanding:

**JSON, not formatted strings.** `logger.warning("validation failed: %s", violations)` reads
fine and is useless in aggregate - you cannot ask "how often does the direction check fire"
without parsing prose back out. Every event here carries typed fields instead.

**Context travels implicitly.** `turn_id`, `supplier_id` and `user_id` are set once per
request in a `ContextVar` and attached to every record emitted underneath it, including from
modules that know nothing about logging. Threading a correlation id through every call
signature is the alternative, and it is the reason correlation ids usually get dropped.

**Tenant data never reaches the log.** This is a multi-tenant product whose whole claim is
that one supplier cannot see another's numbers; a log file that quotes result rows would be
that leak with extra steps. Row *counts*, column *names* and tool *arguments* are recorded -
arguments are ids and dates the caller already supplied - but never the rows themselves. The
question text is recorded because `audit_turn` already stores it deliberately (§11.2) and
debugging a bad answer without knowing what was asked is guesswork.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

from .config import settings

__all__ = ["ContextVar", "JsonFormatter", "TextFormatter", "bind", "configure",
           "Path", "fingerprint", "new_turn_id", "redacted", "safe_extra", "timed"]

# No mutable default: every reader goes through `_ctx()`, so the empty case is a fresh
# dict rather than one shared across every request that never bound anything.
_context: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)


def _ctx() -> dict[str, Any]:
    return _context.get() or {}

# Attributes `logging` puts on every record. Anything else a caller passed via `extra=` is
# ours and belongs in the JSON payload.
_STANDARD = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "asctime", "message", "taskName"}


class JsonFormatter(logging.Formatter):
    """One line, one object. Ordered so a human tailing the file can still read it."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": getattr(record, "event", record.name),
            "msg": record.getMessage(),
            **_ctx(),
            **{k: v for k, v in record.__dict__.items() if k not in _STANDARD},
        }
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable, for a local run. Same fields, laid out for eyes rather than tools."""

    def format(self, record: logging.LogRecord) -> str:
        extra = {**_ctx(),
                 **{k: v for k, v in record.__dict__.items() if k not in _STANDARD}}
        extra.pop("event", None)
        tail = "  ".join(f"{k}={v}" for k, v in extra.items())
        stamp = datetime.fromtimestamp(record.created, UTC).strftime("%H:%M:%S")
        line = (f"{stamp} {record.levelname:<7} "
                f"{getattr(record, 'event', record.name):<22} {record.getMessage()}")
        if tail:
            line += f"   {tail}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def configure() -> None:
    """Install handlers. Idempotent, so an autoreload does not stack them."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = JsonFormatter() if settings.log_format == "json" else TextFormatter()

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)

    if settings.log_file:
        # Midnight UTC, not local: a container's timezone is not a fact anyone should have to
        # know to read a filename, and a DST shift would otherwise produce a 23-hour file.
        path = Path(settings.log_file)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            rotating = TimedRotatingFileHandler(
                path, when="midnight", utc=True,
                backupCount=settings.log_retention_days, encoding="utf-8")
        except OSError as exc:
            # A second copy of what stdout already carries is not worth the process. The
            # container runs unprivileged and `logs/` is a bind mount, so the file can be
            # unwritable for reasons that have nothing to do with the API being healthy -
            # and an API that refuses to start because it cannot write a duplicate log is
            # an outage caused by its own bookkeeping.
            root.warning("file logging disabled: %s", exc, extra={
                "event": "log.file_unavailable", "path": str(path)})
        else:
            # Default naming gives `api.jsonl.2026-07-31`, which no tool recognises as JSON
            # and which sorts oddly. `api-2026-07-31.jsonl` keeps the suffix where it belongs.
            rotating.namer = lambda name: str(
                path.with_name(f"{path.stem}-{name.rsplit('.', 1)[-1]}{path.suffix}"))
            rotating.setFormatter(JsonFormatter())  # the file is always machine-readable
            root.addHandler(rotating)

    root.setLevel(settings.log_level.upper())
    # These two narrate every request and every connection at INFO and drown the events
    # that matter. Their warnings still come through.
    for noisy in ("httpx", "httpcore", "asyncio", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


#: Names `logging` already owns on a LogRecord. Passing one via `extra=` raises KeyError,
#: which inside an agent turn is caught by the broad handler and silently becomes an error
#: event - a logging call taking down the answer it was there to describe. `event` is ours by
#: convention and deliberately allowed.
RESERVED = _STANDARD - {"event"}


def safe_extra(event: str, **fields: Any) -> dict[str, Any]:
    """Build an `extra=` payload, renaming anything that would collide with LogRecord."""
    out: dict[str, Any] = {"event": event}
    for key, value in fields.items():
        out[f"{key}_" if key in RESERVED else key] = value
    return out


def fingerprint(text: str) -> str:
    """A stable short hash of free text, for correlating without storing it.

    Enough to answer "is this the same question as the one that failed an hour ago" and to
    join a log line to its `audit_turn` row, without putting the text itself somewhere it
    outlives its retention policy.
    """
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def redacted(text: str | None, field: str = "text") -> dict[str, Any]:
    """Free text as loggable metadata: length and fingerprint, or the text itself when
    `log_sensitive` is on."""
    if text is None:
        return {}
    if settings.log_sensitive:
        return {field: text}
    return {f"{field}_chars": len(text), f"{field}_sha": fingerprint(text)}


def bind(**fields: Any) -> None:
    """Add fields to every record emitted from here on in this request."""
    _context.set({**_ctx(), **{k: v for k, v in fields.items() if v is not None}})


def new_turn_id() -> str:
    return uuid.uuid4().hex[:12]


class timed:
    """Log one event with its duration, and log it even when the body raises.

        with timed("mcp.call", tool="query_sales"):
            ...

    A failure that takes four seconds and a success that takes four seconds are different
    facts, and only recording the happy path hides the one worth finding.
    """

    def __init__(self, event: str, logger: logging.Logger | None = None, **fields: Any):
        self.event = event
        self.logger = logger or logging.getLogger("api")
        self.fields = fields

    def __enter__(self) -> timed:
        self.started = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        ms = int((time.monotonic() - self.started) * 1000)
        if exc is None:
            self.logger.info("", extra={"event": self.event, "ms": ms, **self.fields})
        else:
            self.logger.warning("", extra={"event": f"{self.event}.failed", "ms": ms,
                                           "error_type": type(exc).__name__,
                                           "error": str(exc)[:500], **self.fields})
