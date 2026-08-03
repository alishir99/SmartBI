"""The API's own database connection — deliberately *not* the MCP server's."""

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


# ------------------------------------------------------------------------------ users

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


# ------------------------------------------------------------------------------ audit

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
    except Exception:                                    # noqa: BLE001 — see docstring
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


# ------------------------------------------------------------------------ saved cards

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


async def count_cards(supplier_id: int) -> int:
    return int(await pool().fetchval(
        "SELECT count(*) FROM saved_card WHERE supplier_id = $1", supplier_id))


async def list_cards(supplier_id: int, limit: int) -> list[dict[str, Any]]:
    # The LIMIT is in the SQL rather than in the route because every one of these rows costs an
    # MCP round-trip when the caller refreshes it — see the note in routes/cards.py.
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
    # The supplier predicate is in the DELETE itself rather than checked first, so there is no
    # window between "may I?" and "do it", and no way to learn that someone else's card_id
    # exists.
    result = await pool().execute(
        "DELETE FROM saved_card WHERE card_id = $1 AND supplier_id = $2",
        card_id, supplier_id,
    )
    return result.endswith(" 1")


def _decode_card(row: dict[str, Any]) -> dict[str, Any]:
    # asyncpg hands JSONB back as text unless a codec is registered; decoding here keeps that
    # detail out of the routes.
    for key in ("chart_spec", "tool_args"):
        if isinstance(row.get(key), str):
            row[key] = json.loads(row[key])
    return row
