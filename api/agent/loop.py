"""The agent turn: plan+execute → validate → render."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from anthropic import AsyncAnthropic

from ..config import settings
from ..mcp_client import McpClient, McpToolError
from ..models import (
    CardEvent,
    ErrorEvent,
    StatusEvent,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
    UsageEvent,
)
from ..result_cache import CachedResult, ResultCache, from_tool_result
from . import render
from .prompts import SYSTEM, regeneration_prompt
from .validate import validate_narrative

logger = logging.getLogger(__name__)

# Hard ceiling on tool calls per turn.
MAX_TOOL_CALLS = 8

# Hard ceiling on trips round the loop, which is a different thing from the tool budget and the
# reason the comment above was not true on its own.
MAX_ROUNDS = 12

# Tools whose results hold rows worth caching and charting.
ROW_TOOLS = {"query_sales", "query_market_share"}

# Size of the replayed narrative chunks, in characters.
_CHUNK = 24

_FRIENDLY_STATUS = {
    "get_capabilities": "Kontrollerar vad datan kan svara på…",
    "resolve_entities": "Slår upp vad du menar…",
    "query_sales": "Hämtar försäljningssiffror…",
    "query_market_share": "Beräknar marknadsandel…",
}


def _system() -> list[dict[str, Any]] | str:
    """The system prompt as a cacheable content block."""
    if "api.anthropic.com" not in settings.llm_base_url:
        return SYSTEM
    return [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]


def _add_usage(total: dict[str, int], response: Any) -> None:
    """Accumulate one response's usage."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    total["llm_calls"] += 1
    for field, key in (("input_tokens", "input_tokens"),
                       ("output_tokens", "output_tokens"),
                       ("cache_read_input_tokens", "cache_read_tokens"),
                       ("cache_creation_input_tokens", "cache_write_tokens")):
        value = getattr(usage, field, None)
        if isinstance(value, int):
            total[key] += value


def _client() -> AsyncAnthropic:
    """The only place the provider is named. Swapping to real Claude is these two settings."""
    return AsyncAnthropic(api_key=settings.llm_api_key, base_url=settings.llm_base_url,
                          timeout=settings.llm_timeout_seconds)


def _text_of(response: Any) -> str:
    return "".join(block.text for block in response.content
                   if getattr(block, "type", None) == "text")


def _tool_uses(response: Any) -> list[Any]:
    return [block for block in response.content
            if getattr(block, "type", None) == "tool_use"]


async def run_turn(*, question: str, history: list[dict[str, str]], supplier_id: int,
                   mcp: McpClient, cache: ResultCache) -> AsyncIterator[Any]:
    """Drive one question to an AnswerCard, yielding SSE event models as it goes."""
    if not settings.llm_api_key:
        yield ErrorEvent(message="LLM_API_KEY är inte satt — agenten kan inte köra.")
        return

    client = _client()
    messages: list[dict[str, Any]] = [
        *({"role": turn["role"], "content": turn["content"]} for turn in history),
        {"role": "user", "content": question},
    ]

    # Every result this turn produced, in order.
    produced: list[CachedResult] = []
    # Labels resolve_entities handed back. They are not rows, so nothing caches them, but the
    # model quotes them in the prose and Swedish SKUs carry model numbers — see
    # mask_entity_names.
    resolved: list[str] = []
    calls = 0
    rounds = 0
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
             "cache_write_tokens": 0, "llm_calls": 0}
    # Stays None when the turn produced no rows: there is then nothing to attribute, and a falsy
    # default keeps the card-building call below from needing a second branch.
    check = None

    try:
        async with mcp.session(supplier_id) as session:
            tools = await mcp.anthropic_tools(supplier_id)
            yield StatusEvent(message="Tänker…")

            while True:
                rounds += 1
                response = await client.messages.create(
                    model=settings.llm_model,
                    max_tokens=settings.llm_max_tokens,
                    system=_system(),
                    tools=tools,
                    messages=messages,
                )
                _add_usage(usage, response)

                uses = _tool_uses(response)
                if response.stop_reason != "tool_use" or not uses:
                    break

                if rounds >= MAX_ROUNDS:
                    # Out of rounds mid-plan: keep whatever was produced and fall through to
                    # validation and rendering rather than raising.
                    logger.warning("agent loop hit MAX_ROUNDS=%d after %d tool call(s)",
                                   MAX_ROUNDS, calls)
                    break

                messages.append({"role": "assistant", "content": response.content})
                tool_results = []

                for use in uses:
                    if calls >= MAX_TOOL_CALLS:
                        # Report the budget to the model rather than cutting the turn off, so it
                        # answers from what it already has instead of failing silently.
                        tool_results.append({
                            "type": "tool_result", "tool_use_id": use.id, "is_error": True,
                            "content": (f"Verktygsbudgeten på {MAX_TOOL_CALLS} anrop är slut. "
                                        "Svara med det du redan hämtat, eller returnera "
                                        "status cannot_answer."),
                        })
                        continue

                    calls += 1
                    args = dict(use.input or {})
                    yield StatusEvent(message=_FRIENDLY_STATUS.get(use.name, "Hämtar data…"))
                    yield ToolCallEvent(tool=use.name, args=args)

                    call_started = time.monotonic()
                    try:
                        payload = await mcp.call_on(session, use.name, args)
                    except McpToolError as exc:
                        logger.warning("", extra={
                            "event": "tool.error", "tool": use.name, "tool_args": args,
                            "ms": int((time.monotonic() - call_started) * 1000),
                            "error": str(exc)[:300]})
                        # A tool error is usually a spec validation failure, and the message
                        # names the allowed values — exactly what the model needs to recover.
                        tool_results.append({
                            "type": "tool_result", "tool_use_id": use.id,
                            "is_error": True, "content": str(exc),
                        })
                        yield ToolResultEvent(tool=use.name, row_count=0)
                        continue

                    content = payload
                    if use.name == "resolve_entities":
                        resolved += [str(m.get("label")) for m in payload.get("matches") or []
                                     if m.get("label")]
                    if use.name in ROW_TOOLS:
                        cached = cache.put(from_tool_result(
                            supplier_id=supplier_id, tool=use.name,
                            tool_args=args, payload=payload))
                        produced.append(cached)
                        # THE grounding step: the model receives a 25-row preview, never the
                        # full set.
                        content = cached.preview()

                    tool_results.append({
                        "type": "tool_result", "tool_use_id": use.id,
                        "content": _dumps(content),
                    })
                    logger.info("", extra={
                        "event": "tool.call", "tool": use.name, "tool_args": args,
                        "ms": int((time.monotonic() - call_started) * 1000),
                        "row_count": int(payload.get("row_count", 0) or 0),
                        "source": (payload.get("meta") or {}).get("source"),
                        "query_id": cached.query_id if use.name in ROW_TOOLS else None})
                    yield ToolResultEvent(
                        tool=use.name,
                        row_count=int(payload.get("row_count", 0) or 0))

                messages.append({"role": "user", "content": tool_results})

            # ---------------------------------------------------------------- validate
            narrative, envelope = render.split_answer(_text_of(response))
            status = str(envelope.get("status") or "ok")
            result = _result_for(envelope, produced)

            # Validation is gated on tool data existing, not on the model's own status field.
            if produced:
                yield StatusEvent(message="Kontrollerar siffrorna mot datan…")
                check = validate_narrative(narrative, produced, resolved)

                if not check.ok:
                    logger.warning("numeric validation failed", extra={
                        "event": "validate.rejected",
                        "reasons": sorted({v.reason for v in check.violations}),
                        "literals": [v.literal for v in check.violations],
                        "checked": check.checked,
                        "attributed": len(check.attributions)})
                    yield StatusEvent(message="Skriver om svaret…")
                    messages.append({"role": "assistant", "content": _text_of(response)})
                    messages.append({"role": "user",
                                     "content": regeneration_prompt(check.violations)})
                    # `tools=tools` is load-bearing, not copy-paste.
                    response = await client.messages.create(
                        model=settings.llm_model,
                        max_tokens=settings.llm_max_tokens,
                        system=_system(),
                        tools=tools,
                        messages=messages,
                    )
                    _add_usage(usage, response)
                    narrative, retry_envelope = render.split_answer(_text_of(response))
                    envelope = {**envelope, **retry_envelope}
                    result = _result_for(envelope, produced)

                    # One retry only.
                    check = validate_narrative(narrative, produced, resolved)
                    if not check.ok:
                        status = "validation_failed"

            # `check.attributions` says which query licensed each figure that survived, so the
            # card can attribute every number in the prose instead of pointing all of them at
            # the chart's query.
            card = render.build_card(result=result, narrative=narrative,
                                     envelope=envelope, status=status,
                                     produced=produced,
                                     attributions=check.attributions if check else [])

            if card.narrative:
                for start in range(0, len(card.narrative), _CHUNK):
                    yield TokenEvent(text=card.narrative[start:start + _CHUNK])

            yield CardEvent(card=card)

    except Exception as exc:  # noqa: BLE001 — the SSE stream needs one terminal event
        logger.exception("agent turn failed")
        yield ErrorEvent(message=f"Något gick fel i agenten: {exc}")
    finally:
        # In `finally` because a turn that died partway still spent real money, and a cost cap
        # fed only by successful turns is a cap with a hole in it.
        yield UsageEvent(**usage)


def _result_for(envelope: dict[str, Any],
                produced: list[CachedResult]) -> CachedResult | None:
    """Which cached result this card is about."""
    query_id = envelope.get("query_id")
    if query_id:
        for result in produced:
            if result.query_id == query_id:
                return result
    return produced[-1] if produced else None


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)
