"""The logging layer, including the way it once broke a turn.

`logging` owns a set of attribute names on every LogRecord, and passing one through `extra=`
raises KeyError. Inside an agent turn that lands in the broad handler and becomes an error
event — a logging call destroying the answer it was added to describe, and only once a
handler is attached at the right level, so it passed in isolation and failed in the suite.
"""

from __future__ import annotations

import json
import logging

from api import logs


def emit(**extra) -> dict:
    """Format one record through JsonFormatter and read the object back."""
    record = logging.LogRecord("api", logging.INFO, __file__, 1, "hello", None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return json.loads(logs.JsonFormatter().format(record))


def test_the_payload_is_one_json_object_per_line():
    out = logs.JsonFormatter().format(
        logging.LogRecord("api", logging.INFO, __file__, 1, "hello", None, None))
    assert "\n" not in out
    assert json.loads(out)["msg"] == "hello"


def test_custom_fields_reach_the_payload():
    payload = emit(event="tool.call", tool="query_sales", row_count=12)
    assert payload["event"] == "tool.call"
    assert payload["tool"] == "query_sales"
    assert payload["row_count"] == 12


def test_a_reserved_name_is_renamed_rather_than_raising():
    """The regression. `args`, `module`, `name` and friends belong to LogRecord."""
    extra = logs.safe_extra("tool.call", tool="query_sales", args={"limit": 10})
    assert "args" not in extra
    assert extra["args_"] == {"limit": 10}
    assert extra["tool"] == "query_sales"
    # And the result is actually usable, which is the whole point.
    logging.getLogger("api.test").info("", extra=extra)


def test_safe_extra_leaves_event_alone():
    assert logs.safe_extra("turn.start")["event"] == "turn.start"


def test_bound_context_appears_on_every_record(monkeypatch):
    monkeypatch.setattr(logs, "_context", logs.ContextVar("t", default=None))
    logs.bind(turn_id="abc123", supplier_id=1)
    payload = emit(event="turn.end")
    assert payload["turn_id"] == "abc123"
    assert payload["supplier_id"] == 1


def test_binding_none_does_not_create_a_null_field(monkeypatch):
    """A card with no query_id should leave the field out rather than log `null` — an absent
    key filters differently from a present empty one."""
    monkeypatch.setattr(logs, "_context", logs.ContextVar("t", default=None))
    logs.bind(turn_id="abc", supplier_id=None)
    assert "supplier_id" not in emit()


def test_timed_records_duration_on_success(caplog):
    with caplog.at_level(logging.INFO), logs.timed("mcp.call", tool="query_sales"):
        pass
    record = caplog.records[-1]
    assert record.event == "mcp.call"
    assert record.ms >= 0


def test_timed_records_the_failure_and_re_raises(caplog):
    """A four-second failure and a four-second success are different facts."""
    try:
        with caplog.at_level(logging.WARNING), logs.timed("mcp.call", tool="query_sales"):
            raise ValueError("boom")
    except ValueError:
        pass
    else:
        raise AssertionError("timed swallowed the exception")

    record = caplog.records[-1]
    assert record.event == "mcp.call.failed"
    assert record.error_type == "ValueError"


def test_the_text_formatter_stays_readable():
    logging.getLogger()  # no handlers needed; the formatter is pure
    record = logging.LogRecord("api", logging.INFO, __file__, 1, "ready", None, None)
    record.event = "startup"
    line = logs.TextFormatter().format(record)
    assert "startup" in line and "ready" in line and "\n" not in line
