"""Request-scoped dependencies — above all, where tenant scope enters the process."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

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


class ScopedTenant(TenantContext):
    """A `TenantContext` past the None check, so callers stop writing `int(...)` round a value the
    dependency already guaranteed."""

    supplier_id: int


async def get_supplier_scope(
    tenant: TenantContext = Depends(get_current_user),
) -> ScopedTenant:
    """For the data endpoints: refuse rather than guess when there is no supplier scope."""
    if tenant.supplier_id is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Kontot är inte kopplat till en leverantör. Leverantörsdata kräver ett "
            "leverantörskonto.",
        )
    return cast(ScopedTenant, tenant)


def get_mcp(request: Request) -> McpClient:
    return request.app.state.mcp


def get_cache(request: Request) -> ResultCache:
    return request.app.state.cache
