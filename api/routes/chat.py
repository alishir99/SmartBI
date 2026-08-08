"""POST /api/chat - one agent turn, streamed as SSE."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from .. import db, i18n, logs, ratelimit
from ..agent.loop import run_turn
from ..deps import ScopedTenant, get_cache, get_mcp, get_supplier_scope
from ..mcp_client import McpClient
from ..models import CardEvent, ChatRequest, ErrorEvent, ToolCallEvent, UsageEvent
from ..result_cache import ResultCache

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat(body: ChatRequest,
               tenant: ScopedTenant = Depends(get_supplier_scope),
               mcp: McpClient = Depends(get_mcp),
               cache: ResultCache = Depends(get_cache)) -> StreamingResponse:
    # Both refusals happen before the stream starts, so they're a plain 429 with a Swedish
    # `detail` (rendered verbatim by the frontend), not an error frame buried in a 200 stream.
    ratelimit.enforce_chat_turn(tenant.user_id)
    await ratelimit.enforce_tenant_budget(tenant.supplier_id)

    return StreamingResponse(
        _stream(body, tenant, mcp, cache),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Without this, nginx and most managed proxies buffer the whole response, hiding
            # the stream from the user.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _stream(body: ChatRequest, tenant: ScopedTenant, mcp: McpClient,
                  cache: ResultCache) -> AsyncIterator[str]:
    logs.bind(turn_id=logs.new_turn_id(), supplier_id=tenant.supplier_id,
              user_id=tenant.user_id)
    # Re-set here, not inherited: middleware ran in the request task, but this generator is
    # consumed in a different task, so the language has to be set where the answer is written.
    i18n.use(body.lang)
    logger.info("", extra={"event": "turn.start", "history_turns": len(body.history),
                           **logs.redacted(body.question, "question")})
    started = time.monotonic()
    tool_calls: list[dict] = []
    status = "error"
    card = None
    usage: UsageEvent | None = None

    try:
        async for event in run_turn(
            question=body.question,
            history=[turn.model_dump() for turn in body.history],
            supplier_id=tenant.supplier_id,
            mcp=mcp,
            cache=cache,
        ):
            if isinstance(event, UsageEvent):
                # Server-side bookkeeping only.
                usage = event
                continue

            if isinstance(event, ToolCallEvent):
                tool_calls.append({"tool": event.tool, "args": event.args})
            elif isinstance(event, CardEvent):
                card, status = event.card, event.card.status
            elif isinstance(event, ErrorEvent):
                status = "error"

            # by_alias is load-bearing: TimeWindow's field is `from_` (from is a keyword);
            # without it the wire sends from_ while every other AnswerCard producer sends from.
            yield f"data: {event.model_dump_json(by_alias=True)}\n\n"
    except Exception as exc:  # noqa: BLE001 - the client is waiting on this stream
        logger.exception("chat stream failed")
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
    finally:
        # Audit after the fact; a logging failure must never break a delivered answer.
        try:
            await db.record_turn(
                user_id=tenant.user_id,
                supplier_id=tenant.supplier_id,
                question=body.question,
                tool_calls=tool_calls,
                row_counts={"queries": len(tool_calls),
                            "query_id": card.query_id if card else None,
                            # Cache hits are the difference between ~$0.17 and ~$0.04 a question,
                            # so the split is kept next to the totals rather than folded away.
                            **({"llm_calls": usage.llm_calls,
                                "cache_read_tokens": usage.cache_read_tokens,
                                "cache_write_tokens": usage.cache_write_tokens}
                               if usage else {})},
                latency_ms=int((time.monotonic() - started) * 1000),
                # Null, not zero, when the loop reported nothing: a zero would read as "this
                # turn was free" in any cost rollup - a worse lie than a gap.
                input_tokens=usage.input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                status=status,
            )
            logger.info("", extra={
                "event": "turn.end", "status": status,
                "ms": int((time.monotonic() - started) * 1000),
                "tools": [c["tool"] for c in tool_calls],
                "query_id": card.query_id if card else None,
                "narrative_chars": len(card.narrative) if card else 0,
                "input_tokens": usage.input_tokens if usage else None,
                "output_tokens": usage.output_tokens if usage else None,
                "llm_calls": usage.llm_calls if usage else None})
        except Exception:
            logger.warning("could not write audit row", exc_info=True)
