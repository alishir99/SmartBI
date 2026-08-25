"""Where tenant scope comes from - and, more importantly, where it does not."""

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError

from .config import settings

HEADER_SUPPLIER = "x-smartbi-supplier-id"
HEADER_TOKEN = "x-smartbi-internal-token"


@dataclass(frozen=True)
class TenantContext:
    supplier_id: int


def tenant_from(ctx: Context) -> TenantContext:
    """Read and verify the scope headers, or refuse to run the tool."""
    request = getattr(ctx.request_context, "request", None)
    if request is None:
        # stdio transport, or a call that arrived without transport metadata.
        raise ToolError("saknar tenant-kontext: anropet måste gå via HTTP-transporten")

    headers = request.headers
    if headers.get(HEADER_TOKEN) != settings.internal_token:
        raise ToolError("ogiltigt internt token")

    raw = headers.get(HEADER_SUPPLIER)
    if not raw:
        raise ToolError(f"saknar {HEADER_SUPPLIER}")
    try:
        supplier_id = int(raw)
    except ValueError as exc:
        raise ToolError(f"ogiltigt {HEADER_SUPPLIER}") from exc

    return TenantContext(supplier_id=supplier_id)
