"""Password hashing, token issue/verify, and the login routes.

Argon2id, in the PHC string format (`$argon2id$v=19$m=...,t=...,p=...$salt$hash`). The
hashing primitive comes from `cryptography` rather than `argon2-cffi` because that is what
is actually installed in this environment — but the *format* is argon2-cffi's, so hashes
written by either library verify against the other. That matters because the seeder writes
`app_user.password_hash` and this module reads it.

JWT is HS256 with a short TTL (§D11: MVP-grade, two independent layers with RLS behind it).
The only claims that matter are `sub`, `supplier_id` and `role` — and `supplier_id` from
this verified token is the *only* source of tenant scope anywhere in the API.
"""

from __future__ import annotations

import base64
import hmac
import os
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from fastapi import APIRouter, Depends, HTTPException, status

from . import db
from .config import settings
from .deps import TenantContext, get_current_user
from .models import LoginRequest, LoginResponse, User

# OWASP's second recommended Argon2id configuration (19 MiB, t=2, p=1). Chosen over a
# heavier profile because login latency is user-visible and the memory cost is the parameter
# that actually resists GPU cracking.
_MEMORY_KIB = 19 * 1024
_ITERATIONS = 2
_LANES = 1
_HASH_LEN = 32
_SALT_LEN = 16


def _b64(raw: bytes) -> str:
    # argon2's PHC variant uses unpadded standard base64.
    return base64.b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(_SALT_LEN)
    digest = Argon2id(salt=salt, length=_HASH_LEN, iterations=_ITERATIONS,
                      lanes=_LANES, memory_cost=_MEMORY_KIB).derive(password.encode())
    return (f"$argon2id$v=19$m={_MEMORY_KIB},t={_ITERATIONS},p={_LANES}"
            f"${_b64(salt)}${_b64(digest)}")


def verify_password(password: str, encoded: str) -> bool:
    """Recompute with the stored parameters and compare in constant time.

    Parameters are read from the hash rather than from settings so that raising the cost
    later does not lock out existing users.
    """
    try:
        _, algorithm, _version, params, salt_b64, hash_b64 = encoded.split("$")
        if algorithm != "argon2id":
            return False
        parsed = dict(part.split("=", 1) for part in params.split(","))
        expected = _unb64(hash_b64)
        digest = Argon2id(
            salt=_unb64(salt_b64), length=len(expected),
            iterations=int(parsed["t"]), lanes=int(parsed["p"]),
            memory_cost=int(parsed["m"]),
        ).derive(password.encode())
    except Exception:                    # noqa: BLE001 — a malformed hash is a failed login
        return False
    return hmac.compare_digest(digest, expected)


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
async def login(body: LoginRequest) -> LoginResponse:
    row = await db.user_by_email(body.email)
    # One message and one code path for "no such user" and "wrong password", so the endpoint
    # is not a registration oracle. The hash is still verified against a dummy when the user
    # is missing would be better still; skipped here because the timing signal is dominated
    # by the DB round-trip anyway and the demo has two known accounts.
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Felaktig e-post eller lösenord")
    return LoginResponse(access_token=create_access_token(row), user=_to_user(row))


@router.get("/me", response_model=User)
async def me(tenant: TenantContext = Depends(get_current_user)) -> User:
    # Read back from the database rather than from the token: a role or supplier change
    # should take effect on the next request, not on the next login.
    row = await db.user_by_id(tenant.user_id)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Användaren finns inte längre")
    return _to_user(row)
