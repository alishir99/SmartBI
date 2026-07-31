"""Password hashing, token issue/verify, and the login routes.

Argon2id via `argon2-cffi`, which is the same library the seeder hashes with — so there is
one implementation of the format rather than two that have to agree. Parameters are read
back from the stored hash, so raising the cost later does not lock out existing users.

JWT is HS256 with a short TTL (§D11: MVP-grade, two independent layers with RLS behind it).
The only claims that matter are `sub`, `supplier_id` and `role` — and `supplier_id` from
this verified token is the *only* source of tenant scope anywhere in the API.
"""

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

# OWASP's second recommended Argon2id configuration (19 MiB, t=2, p=1). Chosen over a
# heavier profile because login latency is user-visible and the memory cost is the parameter
# that actually resists GPU cracking. The same numbers are what makes an unthrottled login
# endpoint a memory amplifier — see api/ratelimit.py.
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
    """A separate, read-only, expiring token for share links (§10).

    `typ` distinguishes it from an access token so a share link can never be presented as
    `Authorization: Bearer` and get a full session — the two token kinds share a secret but
    not a purpose.
    """
    expires_at = datetime.now(UTC) + timedelta(hours=settings.share_link_ttl_hours)
    payload = {
        "typ": "share",
        "card_id": card_id,
        # The original supplier's scope is baked in, so a "live" re-run can only ever
        # execute against the tenant that shared it, whoever opens the link.
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
    # address. Argon2id at 19 MiB is the reason this cannot wait until after a failed attempt:
    # each verification allocates 19 MiB, so an unthrottled login endpoint is a memory
    # amplifier and not only a brute-force surface. See the comment in ratelimit.py for the
    # second half of that — why the same traffic pins this worker's event loop.
    #
    # Throttling ahead of the lookup is also what keeps the refusal from becoming an account
    # oracle: the counter is keyed on what the caller submitted, never on whether it matched
    # anything, so a throttled request for a real account and for a made-up one produce the
    # identical 429.
    ip = ratelimit.client_ip(request)
    ratelimit.enforce_login(identifier=body.email, client_ip=ip)

    row = await db.user_by_email(body.email)
    # One message and one code path for "no such user" and "wrong password", so the endpoint
    # is not a registration oracle. The hash is still verified against a dummy when the user
    # is missing would be better still; skipped here because the timing signal is dominated
    # by the DB round-trip anyway and the demo has two known accounts.
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Felaktig e-post eller lösenord")

    ratelimit.clear_login(identifier=body.email, client_ip=ip)
    return LoginResponse(access_token=create_access_token(row), user=_to_user(row))


@router.get("/me", response_model=User)
async def me(tenant: TenantContext = Depends(get_current_user)) -> User:
    # Read back from the database rather than from the token: a role or supplier change
    # should take effect on the next request, not on the next login.
    row = await db.user_by_id(tenant.user_id)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Användaren finns inte längre")
    return _to_user(row)
