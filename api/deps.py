"""Request-scoped dependencies — above all, where tenant scope enters the process.

`TenantContext` is constructed in exactly one place, from a verified JWT, and nowhere else.
No route reads `supplier_id` from a body, a query string or a header, and no tool schema
contains it (§6.3). If you are reviewing this codebase for tenant leaks, this file and
mcp_client.py are the two you need to read.
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .mcp_client import McpClient
from .result_cache import ResultCache

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class TenantContext:
    supplier_id: int | None
    user_id: int
    role: str


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> TenantContext:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Saknar Authorization-header")

    # Imported here rather than at module scope: auth.py imports this module for
    # get_current_user, so a top-level import would be circular.
    from .auth import decode_access_token

    try:
        claims = decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Ogiltig eller utgången token") from exc

    if claims.get("typ") is not None:
        # Share tokens are signed with the same secret but are not sessions (§10).
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token kan inte användas för inloggning")

    supplier_id = claims.get("supplier_id")
    return TenantContext(
        supplier_id=int(supplier_id) if supplier_id is not None else None,
        user_id=int(claims["sub"]),
        role=str(claims.get("role", "supplier_viewer")),
    )


async def get_supplier_scope(
    tenant: TenantContext = Depends(get_current_user),
) -> TenantContext:
    """For the data endpoints: refuse rather than guess when there is no supplier scope.

    `retail_analyst` and `system_admin` have `supplier_id IS NULL`. Cross-supplier access is
    a real product need but it is a *different* scoping model, and defaulting to "any
    supplier" or "supplier 1" to keep the endpoint working is precisely the bug this whole
    design exists to make impossible.
    """
    if tenant.supplier_id is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Kontot är inte kopplat till en leverantör. Leverantörsdata kräver ett "
            "leverantörskonto.",
        )
    return tenant


def get_mcp(request: Request) -> McpClient:
    return request.app.state.mcp


def get_cache(request: Request) -> ResultCache:
    return request.app.state.cache
