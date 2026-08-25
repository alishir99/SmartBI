"""The MCP client - and the exact point where tenant scope leaves this process."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult

from .config import settings

log = logging.getLogger(__name__)

HEADER_SUPPLIER = "x-smartbi-supplier-id"
HEADER_TOKEN = "x-smartbi-internal-token"


class McpToolError(RuntimeError):
    """A tool refused the call - bad spec, unknown measure, missing scope."""


def to_anthropic_tool(descriptor: dict[str, Any]) -> dict[str, Any]:
    """MCP `{name, description, inputSchema}` → Anthropic `{name, description, input_schema}`. The
    whole adapter is this rename (§6.4)."""
    return {
        "name": descriptor["name"],
        "description": descriptor.get("description") or "",
        "input_schema": descriptor.get("inputSchema") or {"type": "object", "properties": {}},
    }


def parse_tool_result(result: CallToolResult) -> dict[str, Any]:
    """Unwrap a CallToolResult into the dict the tool returned."""
    if result.isError:
        raise McpToolError(_result_text(result) or "verktyget misslyckades")

    structured = result.structuredContent
    if isinstance(structured, dict):
        # FastMCP wraps a non-dict return as {"result": ...}; a dict return comes through as itself.
        if set(structured) == {"result"} and isinstance(structured["result"], dict):
            return structured["result"]
        return structured

    text = _result_text(result)
    if not text:
        raise McpToolError("tomt svar från verktyget")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpToolError(f"kunde inte tolka verktygssvaret: {text[:200]}") from exc
    return payload if isinstance(payload, dict) else {"result": payload}


def _result_text(result: CallToolResult) -> str:
    return "\n".join(
        block.text for block in result.content if getattr(block, "type", None) == "text"
    )


class McpClient:
    """Holds the endpoint and the internal token; opens tenant-scoped sessions on demand."""

    def __init__(self, url: str | None = None, internal_token: str | None = None) -> None:
        self.url = url or settings.mcp_url
        self.internal_token = internal_token or settings.internal_token
        # Tool descriptors are identical for every tenant, so fetched once and cached for the
        # process lifetime. ponytail: no invalidation, so a schema change needs a restart.
        self._tools: list[dict[str, Any]] | None = None

    def _headers(self, supplier_id: int) -> dict[str, str]:
        return {
            HEADER_SUPPLIER: str(int(supplier_id)),
            HEADER_TOKEN: self.internal_token,
        }

    @asynccontextmanager
    async def session(self, supplier_id: int) -> AsyncIterator[ClientSession]:
        """One MCP session, scoped to one supplier, for the length of one request."""
        timeout = timedelta(seconds=settings.mcp_timeout_seconds)
        async with streamablehttp_client(
            self.url, headers=self._headers(supplier_id), timeout=timeout
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    async def call(self, supplier_id: int, tool: str,
                   args: dict[str, Any] | None = None) -> dict[str, Any]:
        """One-shot call. Used by the deterministic paths (dashboard, saved cards)."""
        async with self.session(supplier_id) as session:
            return await self.call_on(session, tool, args)

    async def call_on(self, session: ClientSession, tool: str,
                      args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call on an already-open session - the agent loop makes several per turn."""
        result = await session.call_tool(tool, args or {})
        return parse_tool_result(result)

    async def list_tools(self, supplier_id: int) -> list[dict[str, Any]]:
        if self._tools is None:
            async with self.session(supplier_id) as session:
                listing = await session.list_tools()
            self._tools = [
                {"name": tool.name, "description": tool.description,
                 "inputSchema": tool.inputSchema}
                for tool in listing.tools
            ]
        return self._tools

    async def anthropic_tools(self, supplier_id: int) -> list[dict[str, Any]]:
        return [to_anthropic_tool(tool) for tool in await self.list_tools(supplier_id)]
