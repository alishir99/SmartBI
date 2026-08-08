"""The API's own database connection - deliberately *not* the MCP server's."""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

from .config import settings

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.dsn, min_size=1, max_size=10)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("connection pool not initialised")
    return _pool



USER_SELECT = """
SELECT u.user_id, u.email, u.password_hash, u.role, u.display_name,
       u.supplier_id, s.name AS supplier_name
  FROM app_user u
  LEFT JOIN dim_supplier s ON s.supplier_id = u.supplier_id
"""


async def user_by_email(email: str) -> dict[str, Any] | None:
    row = await pool().fetchrow(f"{USER_SELECT} WHERE lower(u.email) = lower($1)", email)
    return dict(row) if row else None


async def user_by_id(user_id: int) -> dict[str, Any] | None:
    row = await pool().fetchrow(f"{USER_SELECT} WHERE u.user_id = $1", user_id)
    return dict(row) if row else None


async def set_password_hash(user_id: int, password_hash: str) -> bool:
    """Store a new hash. False when the user vanished between the check and the write."""
    result = await pool().execute(
        "UPDATE app_user SET password_hash = $2 WHERE user_id = $1", user_id, password_hash)
    return result.endswith(" 1")



async def record_turn(
    *,
    user_id: int,
    supplier_id: int | None,
    question: str,
    tool_calls: list[dict[str, Any]],
    row_counts: dict[str, Any],
    latency_ms: int,
    input_tokens: int | None,
    output_tokens: int | None,
    status: str,
) -> None:
    """Log one agent turn (§11.2)."""
    try:
        await pool().execute(
            """
            INSERT INTO audit_turn (user_id, supplier_id, question, tool_calls, row_counts,
                                    latency_ms, input_tokens, output_tokens, status)
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8, $9)
            """,
            user_id, supplier_id, question,
            json.dumps(tool_calls, default=str), json.dumps(row_counts, default=str),
            latency_ms, input_tokens, output_tokens, status,
        )
    except Exception:  # noqa: BLE001 - a logging failure must not fail the turn it's logging
        log.exception("kunde inte skriva audit_turn")


async def tokens_used_since(supplier_id: int, window_hours: int) -> int:
    """What one tenant has spent on the agent in the trailing window (api/ratelimit.py)."""
    row = await pool().fetchrow(
        """
        SELECT COALESCE(SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)), 0) AS used
          FROM audit_turn
         WHERE supplier_id = $1
           AND occurred_at >= now() - make_interval(hours => $2)
        """,
        supplier_id, window_hours,
    )
    return int(row["used"]) if row else 0



async def insert_card(*, user_id: int, supplier_id: int, title: str,
                      chart_spec: dict[str, Any], tool_name: str,
                      tool_args: dict[str, Any]) -> int:
    row = await pool().fetchrow(
        """
        INSERT INTO saved_card (user_id, supplier_id, title, chart_spec, tool_name, tool_args)
        VALUES ($1, $2, $3, $4::jsonb, $5, $6::jsonb)
        RETURNING card_id
        """,
        user_id, supplier_id, title,
        json.dumps(chart_spec, default=str), tool_name, json.dumps(tool_args, default=str),
    )
    return int(row["card_id"])


async def supplier_name(supplier_id: int) -> str | None:
    """Who a shared link was created by - the reader has no session to infer it from."""
    return await pool().fetchval(
        "SELECT name FROM dim_supplier WHERE supplier_id = $1", supplier_id)


async def count_cards(supplier_id: int) -> int:
    return int(await pool().fetchval(
        "SELECT count(*) FROM saved_card WHERE supplier_id = $1", supplier_id))


async def list_cards(supplier_id: int, limit: int) -> list[dict[str, Any]]:
    # LIMIT lives in SQL, not the route: every row here costs an MCP round-trip on refresh
    # (see routes/cards.py).
    rows = await pool().fetch(
        "SELECT card_id, title, chart_spec, tool_name, tool_args FROM saved_card "
        "WHERE supplier_id = $1 ORDER BY created_at DESC LIMIT $2",
        supplier_id, limit,
    )
    return [_decode_card(dict(row)) for row in rows]


async def get_card(card_id: int, supplier_id: int) -> dict[str, Any] | None:
    row = await pool().fetchrow(
        "SELECT card_id, title, chart_spec, tool_name, tool_args FROM saved_card "
        "WHERE card_id = $1 AND supplier_id = $2",
        card_id, supplier_id,
    )
    return _decode_card(dict(row)) if row else None


async def delete_card(card_id: int, supplier_id: int) -> bool:
    # Supplier check is baked into the DELETE itself, not a prior check-then-act: no window
    # to race, and no way to learn another supplier's card_id exists.
    result = await pool().execute(
        "DELETE FROM saved_card WHERE card_id = $1 AND supplier_id = $2",
        card_id, supplier_id,
    )
    return result.endswith(" 1")


def _decode_card(row: dict[str, Any]) -> dict[str, Any]:
    # asyncpg returns JSONB as text unless a codec is registered; decode here so routes don't
    # have to.
    for key in ("chart_spec", "tool_args"):
        if isinstance(row.get(key), str):
            row[key] = json.loads(row[key])
    return row
