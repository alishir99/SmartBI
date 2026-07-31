"""Password hashing, token issue/verify, and the login routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error
from fastapi import APIRouter, Depends, HTTPException, Request, status

from . import db, ratelimit
from .config import settings
from .deps import TenantContext, get_current_user
from .models import LoginRequest, LoginResponse, User

# OWASP's second recommended Argon2id configuration (19 MiB, t=2, p=1).
_hasher = PasswordHasher(memory_cost=19 * 1024, time_cost=2, parallelism=1)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time by construction. A malformed hash is a failed login, not a 500."""
    try:
        return _hasher.verify(encoded, password)
    except (Argon2Error, ValueError):
        return False


# ------------------------------------------------------------------------------ tokens

def create_access_token(user: dict) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user["user_id"]),
        "supplier_id": user["supplier_id"],
        "role": user["role"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Verify signature and expiry. Raises `jwt.PyJWTError` on anything suspect."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def create_share_token(*, card_id: str, supplier_id: int, mode: str) -> tuple[str, datetime]:
    """A separate, read-only, expiring token for share links (§10)."""
    expires_at = datetime.now(UTC) + timedelta(hours=settings.share_link_ttl_hours)
    payload = {
        "typ": "share",
        "card_id": card_id,
        # The original supplier's scope is baked in, so a "live" re-run can only ever execute
        # against the tenant that shared it, whoever opens the link.
        "supplier_id": supplier_id,
        "mode": mode,
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_at


# ------------------------------------------------------------------------------ routes

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _to_user(row: dict) -> User:
    return User(
        user_id=row["user_id"], email=row["email"], display_name=row["display_name"],
        role=row["role"], supplier_id=row["supplier_id"],
        supplier_name=row["supplier_name"],
    )


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request) -> LoginResponse:
    # Throttled *before* the lookup and before `verify_password`, per identifier and per
    # address.
    ip = ratelimit.client_ip(request)
    ratelimit.enforce_login(identifier=body.email, client_ip=ip)

    row = await db.user_by_email(body.email)
    # One message and one code path for "no such user" and "wrong password", so the endpoint is
    # not a registration oracle.
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Felaktig e-post eller lösenord")

    ratelimit.clear_login(identifier=body.email, client_ip=ip)
    return LoginResponse(access_token=create_access_token(row), user=_to_user(row))


@router.get("/me", response_model=User)
async def me(tenant: TenantContext = Depends(get_current_user)) -> User:
    # Read back from the database rather than from the token: a role or supplier change should
    # take effect on the next request, not on the next login.
    row = await db.user_by_id(tenant.user_id)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Användaren finns inte längre")
    return _to_user(row)
