"""The agent turn: plan+execute → validate → render.

An explicit `while stop_reason == "tool_use"` loop rather than the SDK's Tool Runner, because
the Tool Runner rides on `anthropic-beta` headers that the DeepSeek endpoint rejects (D2).
The loop is short enough that writing it out costs little and makes the tool-call budget and
the validation stage obvious.

**One deliberate deviation from API_CONTRACT.md, and it is a correctness decision:** `token`
events are emitted only *after* numeric validation has passed. Streaming the prose while it is
being generated would put unverified numbers on screen — and since the validator's whole job
is to suppress prose containing numbers that are not in the data, showing it first and
retracting it later would defeat the guarantee. Tool-call events stream live, which is the
part that actually communicates progress; the narrative is replayed in chunks once it is
known to be true.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from anthropic import AsyncAnthropic

from ..config import settings
from ..mcp_client import McpClient, McpToolError
from ..models import (
    AnswerCard,
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

# Hard ceiling on tool calls per turn. Bounds cost and latency, and stops a confused model
# looping on resolve_entities forever. Eight is comfortably above what any golden question
# needs (the deepest is capabilities → resolve → query).
MAX_TOOL_CALLS = 8

# Hard ceiling on trips round the loop, which is a different thing from the tool budget and
# the reason the comment above was not true on its own. Once `calls` hits MAX_TOOL_CALLS the
# budget branch reports the exhaustion to the model and moves on *without* incrementing
# anything — so a model that keeps emitting tool_use (entirely plausible after eight
# "budget is spent" errors) drove the loop forever, at one full LLM round trip per pass. The
# tool budget bounds the work; this bounds the conversation. Comfortably above the deepest
# legitimate turn, which is three passes, plus room for the model to recover from a spec
# error or two.
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
    """The system prompt as a cacheable content block.

    `system=SYSTEM` as a plain string was structurally *ready* for caching and never
    actually requested it: `cache_control` attaches to content blocks, and a bare string is
    not one. So the ~1 900-token prefix was re-read at full price on every call, several
    times per turn.

    Gated on the provider because it is only meaningful to Anthropic. The demo runs against
    DeepSeek's Anthropic-compatible endpoint, which does its own automatic context caching
    and has no use for the hint; sending it there would be an untested field on a
    third-party API for no gain. Pointing `llm_base_url` at api.anthropic.com — the swap
    decision D1 already describes — turns it on.
    """
    if "api.anthropic.com" not in settings.llm_base_url:
        return SYSTEM
    return [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]


def _add_usage(total: dict[str, int], response: Any) -> None:
    """Accumulate one response's usage. `audit_turn` has had input_tokens/output_tokens
    columns since the first schema and they were written NULL, because nothing collected
    what the SDK hands back on every single call. This is what the per-tenant cost cap
    needs, and it costs one function."""
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
    """Drive one question to an AnswerCard, yielding SSE event models as it goes.

    The last event to reach the wire is always a CardEvent or an ErrorEvent, so the frontend
    has exactly one terminal state to handle. A `UsageEvent` follows it for the caller's own
    bookkeeping; routes/chat.py records it and does not forward it.
    """
    if not settings.llm_api_key:
        yield ErrorEvent(message="LLM_API_KEY är inte satt — agenten kan inte köra.")
        return

    client = _client()
    messages: list[dict[str, Any]] = [
        *({"role": turn["role"], "content": turn["content"]} for turn in history),
        {"role": "user", "content": question},
    ]

    # Every result this turn produced, in order. The validator checks the prose against all of
    # them, because a legitimate answer may quote a number from an earlier query in the turn.
    produced: list[CachedResult] = []
    calls = 0
    rounds = 0
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
             "cache_write_tokens": 0, "llm_calls": 0}

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
                    # validation and rendering rather than raising. The turn still ends in a
                    # card, and if nothing was produced the model's own text stands — which
                    # is the same shape as any other answer that reached no tool.
                    logger.warning("agent loop hit MAX_ROUNDS=%d after %d tool call(s)",
                                   MAX_ROUNDS, calls)
                    break

                messages.append({"role": "assistant", "content": response.content})
                tool_results = []

                for use in uses:
                    if calls >= MAX_TOOL_CALLS:
                        # Report the budget to the model rather than cutting the turn off, so
                        # it answers from what it already has instead of failing silently.
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

                    try:
                        payload = await mcp.call_on(session, use.name, args)
                    except McpToolError as exc:
                        # A tool error is usually a spec validation failure, and the message
                        # names the allowed values — exactly what the model needs to recover.
                        tool_results.append({
                            "type": "tool_result", "tool_use_id": use.id,
                            "is_error": True, "content": str(exc),
                        })
                        yield ToolResultEvent(tool=use.name, row_count=0)
                        continue

                    content = payload
                    if use.name in ROW_TOOLS:
                        cached = cache.put(from_tool_result(
                            supplier_id=supplier_id, tool=use.name,
                            tool_args=args, payload=payload))
                        produced.append(cached)
                        # THE grounding step: the model receives a 25-row preview, never the
                        # full set. The chart is drawn later from the cache, so the values on
                        # screen provably never passed through the model.
                        content = cached.preview()

                    tool_results.append({
                        "type": "tool_result", "tool_use_id": use.id,
                        "content": _dumps(content),
                    })
                    yield ToolResultEvent(
                        tool=use.name,
                        row_count=int(payload.get("row_count", 0) or 0))

                messages.append({"role": "user", "content": tool_results})

            # ---------------------------------------------------------------- validate
            narrative, envelope = render.split_answer(_text_of(response))
            status = str(envelope.get("status") or "ok")
            result = _result_for(envelope, produced)

            # Validation is gated on tool data existing, not on the model's own status
            # field. Gating on `status == "ok"` made the check opt-out through a value the
            # model writes itself: a narrative emitted under `clarify` still reaches the
            # user with its figures intact (build_card only suppresses prose for
            # `validation_failed`), and `clarify` is exactly what the model reaches for
            # when entity resolution is fuzzy — the moment it is most likely improvising.
            # If there are rows to check the prose against, we check it.
            if produced:
                yield StatusEvent(message="Kontrollerar siffrorna mot datan…")
                check = validate_narrative(narrative, produced)

                if not check.ok:
                    logger.warning("numeric validation failed: %s", check.violations)
                    yield StatusEvent(message="Skriver om svaret…")
                    messages.append({"role": "assistant", "content": _text_of(response)})
                    messages.append({"role": "user",
                                     "content": regeneration_prompt(check.violations)})
                    # `tools=tools` is load-bearing, not copy-paste. `messages` at this point
                    # still holds the tool_use blocks from the planning phase, and a request
                    # carrying tool_use without a `tools` declaration is a 400 on
                    # api.anthropic.com. The broad `except` below would have turned that into
                    # a turn-level error — so the user would lose a perfectly good, fully
                    # grounded chart because the *prose* failed validation. That is the exact
                    # inverse of what this retry exists to guarantee.
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

                    # One retry only. A second failure means the model cannot state this
                    # answer truthfully, so we keep the chart and drop the prose.
                    if not validate_narrative(narrative, produced).ok:
                        status = "validation_failed"

            card = render.build_card(result=result, narrative=narrative,
                                     envelope=envelope, status=status)

            if card.narrative:
                for start in range(0, len(card.narrative), _CHUNK):
                    yield TokenEvent(text=card.narrative[start:start + _CHUNK])

            yield CardEvent(card=card)

    except Exception as exc:  # noqa: BLE001 — the SSE stream needs one terminal event
        logger.exception("agent turn failed")
        yield ErrorEvent(message=f"Något gick fel i agenten: {exc}")
    finally:
        # In `finally` because a turn that died partway still spent real money, and a cost
        # cap fed only by successful turns is a cap with a hole in it.
        yield UsageEvent(**usage)


def _result_for(envelope: dict[str, Any],
                produced: list[CachedResult]) -> CachedResult | None:
    """Which cached result this card is about.

    Honour the model's `query_id` when it names one we actually produced; otherwise fall back
    to the most recent. Never trust an id we did not mint — that is how a card could end up
    pointing at another tenant's cache entry.
    """
    query_id = envelope.get("query_id")
    if query_id:
        for result in produced:
            if result.query_id == query_id:
                return result
    return produced[-1] if produced else None


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


async def run_turn_to_card(*, question: str, supplier_id: int, mcp: McpClient,
                           cache: ResultCache,
                           history: list[dict[str, str]] | None = None) -> AnswerCard:
    """Non-streaming convenience wrapper, used by tests and the eval harness."""
    card: AnswerCard | None = None
    error: str | None = None
    async for event in run_turn(question=question, history=history or [],
                                supplier_id=supplier_id, mcp=mcp, cache=cache):
        if isinstance(event, CardEvent):
            card = event.card
        elif isinstance(event, ErrorEvent):
            error = event.message
    if card is None:
        return AnswerCard(status="cannot_answer",
                          narrative=error or "Inget svar producerades.")
    return card
