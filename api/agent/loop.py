"""The agent turn: plan+execute → validate → render."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Sequence
from difflib import SequenceMatcher
from typing import Any

from anthropic import AsyncAnthropic

from ..config import settings
from ..i18n import current as current_language
from ..i18n import tr as i18n_tr
from ..mcp_client import McpClient, McpToolError
from ..models import (
    CardEvent,
    ErrorEvent,
    PreviewEvent,
    StatusEvent,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
    UsageEvent,
)
from ..result_cache import CachedResult, ResultCache, from_tool_result
from . import render
from .prompts import regeneration_prompt, system_prompt
from .validate import validate_narrative

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 8

MAX_ROUNDS = 12  # distinct from MAX_TOOL_CALLS: rounds are trips through the loop, not tool calls

ROW_TOOLS = {"query_sales", "query_market_share"}

_CHUNK = 24

_STATUS_KEYS = {
    "get_capabilities": "agent.status.get_capabilities",
    "resolve_entities": "agent.status.resolve_entities",
    "query_sales": "agent.status.query_sales",
    "query_market_share": "agent.status.query_market_share",
}


def _friendly_status(tool_name: str) -> str:
    """The status line shown while a tool runs, in this turn's language."""
    return i18n_tr(_STATUS_KEYS.get(tool_name, "agent.status.default"))


# ponytail: similarity ratio for fuzzy matching, tuned on real cases (0.89 vs 0.35).
# Raise it if genuine typos start reading as misses.
_RESEMBLANCE = 0.6


def resembles_any(asked: str, labels: Sequence[str]) -> bool:
    """Whether any match is plausibly the thing that was asked for.

    An empty match list is the obvious miss, and not the common one: retrieval fuses a lexical
    and a semantic search, so asking after a competitor comes back with the nearest brand the
    supplier *does* own. Treating that as a hit is how "Lumia Nordic finns inte bland dina
    varumärken" reached the card with the name still in it.
    """
    asked = asked.casefold().strip()
    return any(label in asked or asked in label
               or SequenceMatcher(None, asked, label).ratio() >= _RESEMBLANCE
               for label in (raw.casefold().strip() for raw in labels) if label)


def _system() -> list[dict[str, Any]] | str:
    """The system prompt as a cacheable content block, in this turn's language."""
    prompt = system_prompt(current_language())
    if "api.anthropic.com" not in settings.llm_base_url:
        return prompt
    return [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]


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
        yield ErrorEvent(message=i18n_tr("agent.no_api_key"))
        return

    client = _client()
    messages: list[dict[str, Any]] = [
        *({"role": turn["role"], "content": turn["content"]} for turn in history),
        {"role": "user", "content": question},
    ]

    produced: list[CachedResult] = []
    # Labels resolve_entities returned; not rows, so nothing caches them, but the model quotes
    # them in the prose (see mask_entity_names).
    resolved: list[str] = []
    # Names resolve_entities found nothing for; render.scrub_names strips them from the card
    # instead of relying on the prompt not to repeat them.
    unresolved: list[str] = []
    calls = 0
    rounds = 0
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
             "cache_write_tokens": 0, "llm_calls": 0}
    # None when the turn produced no rows - nothing to attribute, and the falsy default avoids
    # a second branch below.
    check = None

    try:
        async with mcp.session(supplier_id) as session:
            tools = await mcp.anthropic_tools(supplier_id)
            yield StatusEvent(message=i18n_tr("agent.thinking"))

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
                    # Out of rounds mid-plan: fall through to validation/rendering, don't raise.
                    logger.warning("agent loop hit MAX_ROUNDS=%d after %d tool call(s)",
                                   MAX_ROUNDS, calls)
                    break

                messages.append({"role": "assistant", "content": response.content})
                tool_results = []

                for use in uses:
                    if calls >= MAX_TOOL_CALLS:
                        # Report the budget to the model instead of cutting the turn off, so it
                        # answers from what it already has rather than failing silently.
                        tool_results.append({
                            "type": "tool_result", "tool_use_id": use.id, "is_error": True,
                            "content": (f"Verktygsbudgeten på {MAX_TOOL_CALLS} anrop är slut. "
                                        "Svara med det du redan hämtat, eller returnera "
                                        "status cannot_answer."),
                        })
                        continue

                    calls += 1
                    args = dict(use.input or {})
                    yield StatusEvent(message=_friendly_status(use.name))
                    yield ToolCallEvent(tool=use.name, args=args)

                    call_started = time.monotonic()
                    try:
                        payload = await mcp.call_on(session, use.name, args)
                    except McpToolError as exc:
                        logger.warning("", extra={
                            "event": "tool.error", "tool": use.name,
                            "arg_keys": sorted(args),
                            "ms": int((time.monotonic() - call_started) * 1000),
                            "error": str(exc)[:300]})
                        # Tool errors are usually spec validation failures whose message names
                        # the allowed values - exactly what the model needs to recover.
                        tool_results.append({
                            "type": "tool_result", "tool_use_id": use.id,
                            "is_error": True, "content": str(exc),
                        })
                        yield ToolResultEvent(tool=use.name, row_count=0)
                        continue

                    content = payload
                    if use.name == "resolve_entities":
                        matches = payload.get("matches") or []
                        labels = [str(m["label"]) for m in matches if m.get("label")]
                        resolved += labels
                        asked = args.get("text")
                        if isinstance(asked, str) and not resembles_any(asked, labels):
                            unresolved.append(asked)
                    if use.name in ROW_TOOLS:
                        cached = cache.put(from_tool_result(
                            supplier_id=supplier_id, tool=use.name,
                            tool_args=args, payload=payload))
                        produced.append(cached)
                        # THE grounding step: the model sees a preview, never the full row set.
                        content = cached.preview()

                    tool_results.append({
                        "type": "tool_result", "tool_use_id": use.id,
                        "content": _dumps(content),
                    })
                    logger.info("", extra={
                        "event": "tool.call", "tool": use.name,
                        **({"tool_args": args} if settings.log_sensitive
                           else {"arg_keys": sorted(args)}),
                        "ms": int((time.monotonic() - call_started) * 1000),
                        "row_count": int(payload.get("row_count", 0) or 0),
                        "source": (payload.get("meta") or {}).get("source"),
                        "query_id": cached.query_id if use.name in ROW_TOOLS else None})
                    yield ToolResultEvent(
                        tool=use.name,
                        # None (not 0) for tools with no row concept - a successful lookup would
                        # otherwise read as "0 rader", same as one that found nothing.
                        row_count=(int(payload.get("row_count", 0) or 0)
                                   if use.name in ROW_TOOLS else None))

                    if use.name in ROW_TOOLS and cached.rows:
                        # Chart is ready before the prose is; turn latency is 26s mean/54s p95,
                        # so this preview beats a status line for the whole wait.
                        yield PreviewEvent(card=render.build_card(
                            result=cached, narrative="", envelope={}, produced=produced,
                            unresolved=unresolved))

                messages.append({"role": "user", "content": tool_results})
                # Fetch is over; status must stop claiming "fetching" since composing is where
                # most of a 40s turn goes.
                yield StatusEvent(message=i18n_tr("agent.composing"))

            narrative, envelope = render.split_answer(_text_of(response))
            status = str(envelope.get("status") or "ok")
            result = _result_for(envelope, produced)

            # Gated on tool data existing, not the model's status field. "explain" is the
            # exception: it runs against zero rows, so it can't state figures from memory.
            if produced or status == "explain":
                yield StatusEvent(message=i18n_tr("agent.checking_numbers"))
                check = validate_narrative(narrative, produced, resolved)

                if not check.ok:
                    logger.warning("numeric validation failed", extra={
                        "event": "validate.rejected",
                        "reasons": sorted({v.reason for v in check.violations}),
                        "rejected": len(check.violations),
                        "checked": check.checked,
                        "attributed": len(check.attributions),
                        # Literals are real tenant figures; gated behind log_sensitive, not
                        # logged by default.
                        **({"literals": [v.literal for v in check.violations]}
                           if settings.log_sensitive else {})})
                    yield StatusEvent(message=i18n_tr("agent.rewriting"))
                    messages.append({"role": "assistant", "content": _text_of(response)})
                    messages.append({"role": "user",
                                     "content": regeneration_prompt(check.violations)})
                    # `tools=tools` is load-bearing here, not copy-paste.
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

            # check.attributions says which query licensed each surviving figure, so the card
            # attributes each number individually instead of pointing them all at the chart.
            card = render.build_card(result=result, narrative=narrative,
                                     envelope=envelope, status=status,
                                     produced=produced,
                                     attributions=check.attributions if check else [],
                                     unresolved=unresolved)

            if card.narrative:
                for start in range(0, len(card.narrative), _CHUNK):
                    yield TokenEvent(text=card.narrative[start:start + _CHUNK])

            yield CardEvent(card=card)

    except Exception as exc:  # noqa: BLE001 - the SSE stream needs one terminal event
        logger.exception("agent turn failed")
        yield ErrorEvent(message=i18n_tr("agent.error", error=exc))
    finally:
        # In `finally`: a turn that dies partway still spent real money, and a cost cap fed
        # only by successful turns has a hole in it.
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
