"""The MCP server - the only path to the data."""

from __future__ import annotations

import logging

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import db
from .config import settings
from .semantic.compiler import SpecError
from .tenant import tenant_from
from .tools import capabilities as capabilities_tool
from .tools import market_share as market_share_tool
from .tools import resolve as resolve_tool
from .tools import sales as sales_tool
from .tools.schemas import (
    CompareTo,
    DimensionKey,
    EntityKind,
    Filters,
    Having,
    MeasureKey,
    OrderBy,
    TimeRange,
    TopNPer,
)

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
Semantiskt lager för försäljningsdata i svensk detaljhandel.

Arbetsordning:
1. get_capabilities - vad som finns, vilka enheter, vilken period datan täcker.
2. resolve_entities - översätt fritext till ID innan du filtrerar på namn.
3. query_sales - mät och gruppera. Använd compare_to istället för två anrop och subtraktion.
4. query_market_share - egen andel och placering i kategorin. Aldrig namngivna konkurrenter.

Leverantörsomfång sätts av transporten, inte av dig. Det finns ingen parameter för att välja
leverantör, och det är avsiktligt.
"""

mcp = FastMCP(
    name="solvigo-insights",
    instructions=INSTRUCTIONS,
    host=settings.mcp_host,
    port=settings.mcp_port,
    # Stateless: every call carries its own tenant headers, so no session affinity is needed and
    # the service scales horizontally without sticky routing.
    stateless_http=True,
    json_response=True,
)


def _spec_error(exc: SpecError) -> ToolError:
    """Turn a validation failure into a message the model can act on."""
    return ToolError(f"Ogiltig förfrågan: {exc}")


@mcp.tool(
    description="Vad som går att fråga om: mått, dimensioner, filter med tillåtna värden, "
                "vilken period datan täcker, enheter, och vad leverantören får se om andra. "
                "Anropa detta först om du är osäker på om något är möjligt.")
async def get_capabilities(ctx: Context) -> dict:
    tenant = tenant_from(ctx)
    return await capabilities_tool.get_capabilities(tenant)


@mcp.tool(
    description="Översätt fritext till kanoniska ID. Anropa alltid detta innan du filtrerar "
                "på ett namn. Returnerar kandidater med poäng - om flera kandidater är "
                "rimliga, fråga användaren istället för att välja själv. Tom lista betyder "
                "att entiteten inte finns; hitta då inte på ett ID.")
async def resolve_entities(ctx: Context, text: str,
                           kinds: list[EntityKind] | None = None,
                           limit: int = 8) -> dict:
    tenant = tenant_from(ctx)
    return await resolve_tool.resolve_entities(tenant, text, list(kinds) if kinds else None, limit)


@mcp.tool(
    description="Hämta försäljningssiffror: välj mått, gruppera på dimensioner, filtrera, "
                "och jämför mot föregående period eller samma period förra året. Alla belopp "
                "i SEK exkl. moms. Använd compare_to hellre än två separata anrop - låt "
                "databasen räkna, räkna aldrig själv.")
async def query_sales(ctx: Context,
                      measures: list[MeasureKey],
                      dimensions: list[DimensionKey] | None = None,
                      filters: Filters | None = None,
                      time_range: TimeRange | None = None,
                      compare_to: CompareTo | None = None,
                      order_by: OrderBy | None = None,
                      percent_of_total: bool = False,
                      having: Having | None = None,
                      top_n_per: TopNPer | None = None,
                      limit: int = 500) -> dict:
    tenant = tenant_from(ctx)
    spec = {
        "measures": list(measures),
        "dimensions": list(dimensions or []),
        "filters": filters.model_dump(exclude_none=True) if filters else {},
        "time_range": _time_range(time_range),
        "compare_to": compare_to,
        "order_by": order_by.model_dump(exclude_none=True) if order_by else None,
        "percent_of_total": percent_of_total,
        "having": having.model_dump(exclude_none=True) if having else None,
        "top_n_per": top_n_per.model_dump(exclude_none=True) if top_n_per else None,
        "limit": limit,
    }
    try:
        return await sales_tool.query_sales(tenant, spec)
    except SpecError as exc:
        raise _spec_error(exc) from exc


@mcp.tool(
    description="Egen marknadsandel och placering per underkategori: egen försäljning, "
                "kategorins totala försäljning, andel i procent, placering och antal "
                "varumärken. Konkurrenter namnges aldrig och itemiseras aldrig. Tunna urval "
                "utelämnas helt (k-anonymitet) och returnerar då suppressed=true med skäl. "
                "Med compare_to följer 'share_pct_compare' och 'share_pct_delta_pe' med - "
                "förändringen i procentenheter, inte i procent av en procent.")
async def query_market_share(ctx: Context,
                             category_ids: list[int] | None = None,
                             region: list[str] | None = None,
                             time_range: TimeRange | None = None,
                             compare_to: CompareTo | None = None) -> dict:
    tenant = tenant_from(ctx)
    spec = {
        "category_ids": category_ids,
        "region": region,
        "time_range": _time_range(time_range),
        "compare_to": compare_to,
    }
    try:
        return await market_share_tool.query_market_share(tenant, spec)
    except SpecError as exc:
        raise _spec_error(exc) from exc


def _time_range(time_range: TimeRange | None) -> dict:
    """Flatten the schema's `from`/`to`/`relative` into what the compiler expects."""
    if time_range is None:
        return {}
    if time_range.relative:
        return {"relative": time_range.relative}
    return {"from": time_range.from_date, "to": time_range.to}


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    """Liveness plus a real readiness signal: can we reach the warehouse and does it hold data? A
    health check that only proves the process is running is worth very little."""
    try:
        coverage_from, coverage_to = await db.coverage()
    except Exception as exc:  # noqa: BLE001 - the endpoint's job is to report, not to raise
        return JSONResponse({"status": "degraded", "error": str(exc)}, status_code=503)
    return JSONResponse({
        "status": "ok",
        "coverage": {"from": coverage_from.isoformat(), "to": coverage_to.isoformat()},
        "tools": ["get_capabilities", "resolve_entities", "query_sales",
                  "query_market_share"],
    })


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Before the pool, before the port.
    settings.assert_secrets_rotated()

    async def run() -> None:
        await db.init_pool()
        try:
            await mcp.run_streamable_http_async()
        finally:
            await db.close_pool()

    import anyio
    anyio.run(run)


if __name__ == "__main__":
    main()
