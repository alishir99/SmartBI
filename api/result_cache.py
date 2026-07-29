"""Where the full result set lives — server-side, and nowhere else.

This is the mechanical core of the grounding claim (§9.1). A tool returns every row; those
rows are stored here under the tool's `query_id`, and the model is handed only a capped
preview plus `row_count`. The chart is later drawn by fetching `/api/result/{query_id}`.

Two consequences worth stating:

- A 1 200-row answer costs the same context tokens as a 10-row one, because the extra rows
  never enter the conversation.
- If the model hallucinates a number in prose, the chart still shows the truth, and the
  validator (agent/validate.py) checks the prose against *these* rows — the full set, not
  the preview the model saw.

In-process and volatile on purpose. It is a cache, not a store: on a miss the frontend
re-asks. A multi-instance deployment would move this to Redis with the same interface and
the same tenant check; nothing else would change.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

# 30 minutes is long enough to page through a chart, save a card and export a CSV, and short
# enough that a result set is not sitting in memory long after the user moved on.
DEFAULT_TTL_SECONDS = 30 * 60
DEFAULT_MAX_ENTRIES = 500

# How many rows the model is allowed to see. Enough to reason about shape, trend and
# outliers; nowhere near enough to recite the data set.
PREVIEW_ROWS = 25


@dataclass
class CachedResult:
    query_id: str
    supplier_id: int
    tool: str
    tool_args: dict[str, Any]
    columns: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)

    def numeric_columns(self) -> list[str]:
        return [c["key"] for c in self.columns if c.get("type") == "number"]

    def preview(self, limit: int = PREVIEW_ROWS) -> dict[str, Any]:
        """What the model gets instead of the data.

        `truncated_for_model` is separate from the tool's own `truncated` flag: one says "the
        database had more rows than you asked for", the other says "you are looking at a
        sample". Conflating them would let the model claim it saw everything.
        """
        rows = self.rows[:limit]
        return {
            "query_id": self.query_id,
            "columns": self.columns,
            "rows": rows,
            "row_count": self.row_count,
            "preview_rows": len(rows),
            "truncated_for_model": self.row_count > len(rows),
            "meta": self.meta,
            "note": (
                f"Detta är en förhandsvisning av {len(rows)} av {self.row_count} rader. "
                "Hela resultatet finns kvar på servern och ritas i diagrammet — referera "
                "till query_id i din ChartSpec istället för att räkna upp värden."
            ),
        }


class ResultCache:
    """query_id → CachedResult, tenant-scoped, TTL'd and size-capped."""

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS,
                 max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[str, CachedResult] = OrderedDict()

    def put(self, result: CachedResult) -> CachedResult:
        self._evict()
        self._entries[result.query_id] = result
        self._entries.move_to_end(result.query_id)
        # Insertion-ordered, so popping from the front drops the oldest entry. A cache full
        # of one tenant's queries can push out another's; the cost of a miss is a re-query,
        # which is the right trade against unbounded memory.
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        return result

    def get(self, query_id: str, supplier_id: int) -> CachedResult | None:
        """Look up within one tenant's scope.

        A hit belonging to another supplier returns `None`, exactly as a genuine miss does,
        so the caller can only ever produce a 404. A 403 here would confirm that the id
        exists — which is itself information about another tenant (contract: /api/result).
        """
        self._evict()
        entry = self._entries.get(query_id)
        if entry is None or entry.supplier_id != supplier_id:
            return None
        return entry

    def _evict(self) -> None:
        cutoff = time.monotonic() - self.ttl_seconds
        for query_id in [k for k, v in self._entries.items() if v.created_at < cutoff]:
            del self._entries[query_id]

    def __len__(self) -> int:
        return len(self._entries)


def from_tool_result(*, supplier_id: int, tool: str, tool_args: dict[str, Any],
                     payload: dict[str, Any]) -> CachedResult:
    """Adapt an MCP tool response into a cache entry.

    Written defensively with `.get()` because the two row-returning tools have slightly
    different envelopes (`query_market_share` carries no `columns` and no `query_id`) and a
    KeyError here would turn a usable answer into a 500.
    """
    meta = payload.get("meta") or {}
    rows = payload.get("rows") or []
    columns = payload.get("columns") or _infer_columns(rows)
    return CachedResult(
        query_id=payload.get("query_id") or f"q_{tool}_{int(time.time() * 1000):x}",
        supplier_id=supplier_id,
        tool=tool,
        tool_args=tool_args,
        columns=columns,
        rows=rows,
        row_count=int(payload.get("row_count", len(rows))),
        truncated=bool(meta.get("truncated", False)),
        meta=meta,
    )


def _infer_columns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Last resort for a tool that returns rows without a column spec.

    Only `query_market_share` needs this today. Types are inferred from the first non-null
    value, which is enough for the chart validator to reject a text column on a numeric axis.
    """
    columns: list[dict[str, Any]] = []
    for key in (rows[0] if rows else {}):
        sample = next((row[key] for row in rows if row.get(key) is not None), None)
        column_type = "number" if isinstance(sample, (int, float)) and not isinstance(
            sample, bool) else "text"
        columns.append({"key": key, "type": column_type, "label": key})
    return columns
