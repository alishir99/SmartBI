"""Password hashing, token issue/verify, and the login routes."""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error
from fastapi import APIRouter, Depends, HTTPException, Request, status

from . import db, mail, ratelimit
from .config import settings
from .deps import TenantContext, get_current_user
from .i18n import tr
from .models import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    ResetPasswordRequest,
    User,
)

logger = logging.getLogger(__name__)

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



def password_reset_key(password_hash: str) -> str:
    """The signing key for one user's reset tokens, derived from their current password hash.

    This is what makes a reset link single-use without a table, a nonce column or a cleanup
    job: the moment the password changes, the hash changes, this key changes, and every token
    ever minted under the old one stops verifying. Redeeming a link therefore burns it, and
    burns any others outstanding for the same account at the same time.

    The hash is already a salted Argon2id digest, so it is not password-equivalent; running it
    through HMAC with the server secret means a database read alone still cannot mint a token.
    """
    return hmac.new(settings.jwt_secret.encode(), password_hash.encode(),
                    hashlib.sha256).hexdigest()


def create_password_reset_token(user: dict) -> tuple[str, datetime]:
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.password_reset_ttl_minutes)
    payload = {
        "typ": "reset",
        "sub": str(user["user_id"]),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, password_reset_key(user["password_hash"]),
                      algorithm=settings.jwt_algorithm), expires_at


def decode_password_reset_token(token: str, password_hash: str) -> dict:
    """Verify a reset token against the account it claims to be for.

    The signing key depends on the current password hash, so this cannot be checked without
    first reading the user - and the user id is inside the token. `user_id_in_reset_token`
    reads it without trusting it; this call is what makes it trustworthy.
    """
    claims = jwt.decode(token, password_reset_key(password_hash),
                        algorithms=[settings.jwt_algorithm])
    if claims.get("typ") != "reset":
        raise jwt.InvalidTokenError("not a reset token")
    return claims


def user_id_in_reset_token(token: str) -> int | None:
    """The `sub` claim, read WITHOUT verifying the signature.

    Only ever used to look up which user's hash to verify against, and the verification is what
    the outcome depends on. Nothing is trusted here: a forged `sub` finds the wrong account,
    whose key then fails to validate the signature.
    """
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
        return int(claims["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        return None


def create_share_token(*, card_id: str, supplier_id: int, mode: str) -> tuple[str, datetime]:
    """A separate, read-only, expiring token for share links (§10)."""
    expires_at = datetime.now(UTC) + timedelta(hours=settings.share_link_ttl_hours)
    payload = {
        "typ": "share",
        "card_id": card_id,
        # Scope is baked into the token: a "live" re-run can only ever execute against the
        # tenant that shared it, whoever opens the link.
        "supplier_id": supplier_id,
        "mode": mode,
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_at



router = APIRouter(prefix="/api/auth", tags=["auth"])


def _to_user(row: dict) -> User:
    return User(
        user_id=row["user_id"], email=row["email"], display_name=row["display_name"],
        role=row["role"], supplier_id=row["supplier_id"],
        supplier_name=row["supplier_name"],
    )


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request) -> LoginResponse:
    # Throttled before the lookup and before verify_password, per identifier and per IP.
    ip = ratelimit.client_ip(request)
    ratelimit.enforce_login(identifier=body.email, client_ip=ip)

    row = await db.user_by_email(body.email)
    # Same message and code path for "no such user" and "wrong password" - not a
    # registration oracle.
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")

    ratelimit.clear_login(identifier=body.email, client_ip=ip)
    return LoginResponse(access_token=create_access_token(row), user=_to_user(row))


@router.get("/me", response_model=User)
async def me(tenant: TenantContext = Depends(get_current_user)) -> User:
    # Read from the DB, not the token: a role or supplier change takes effect on the next
    # request, not the next login.
    row = await db.user_by_id(tenant.user_id)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Användaren finns inte längre")
    return _to_user(row)




@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(body: ChangePasswordRequest,
                          tenant: TenantContext = Depends(get_current_user)) -> None:
    """Change your own password, proving you know the current one."""
    row = await db.user_by_id(tenant.user_id)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, tr("auth.user_gone"))

    # Rate-limited even authenticated: a wrong-password loop here is the same Argon2
    # memory-amplification cost as the login endpoint, one token further in.
    ratelimit.enforce_login(identifier=f"pwchange:{tenant.user_id}", client_ip="-")
    if not verify_password(body.current_password, row["password_hash"]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, tr("auth.wrong_current_password"))
    ratelimit.clear_login(identifier=f"pwchange:{tenant.user_id}", client_ip="-")

    await db.set_password_hash(tenant.user_id, hash_password(body.new_password))
    # No secrets logged; this exists only so an account takeover leaves a timestamp to
    # find later.
    logger.info("", extra={"event": "auth.password_changed", "user_id": tenant.user_id})


@router.post("/password/forgot", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(body: ForgotPasswordRequest, request: Request) -> dict:
    """Start a reset. Always answers the same way, whether or not the account exists.

    A different response, a different status or a measurably different latency for a known
    address turns this route into a way to enumerate customers - which is a data leak about who
    the retailer's suppliers are, before anyone has logged in. So every branch below ends here
    with the same body, including the ones that failed.
    """
    ip = ratelimit.client_ip(request)
    ratelimit.enforce_password_reset(identifier=body.email, client_ip=ip)

    row = await db.user_by_email(body.email)
    if row is not None:
        token, _expires = create_password_reset_token(row)
        link = f"{settings.public_web_url.rstrip('/')}/#/aterstall/{token}"
        try:
            mail.send(to=row["email"],
                      subject=tr("mail.reset_subject"),
                      body=tr("mail.reset_body", name=row["display_name"], link=link,
                              minutes=settings.password_reset_ttl_minutes))
        except Exception:
            # Swallowed on purpose: surfacing a mail failure here would reveal "does this
            # address exist".
            logger.warning("could not send reset mail", exc_info=True,
                           extra={"event": "auth.reset_mail_failed"})
    else:
        logger.info("", extra={"event": "auth.reset_unknown_email"})

    return {"detail": tr("auth.reset_sent")}


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(body: ResetPasswordRequest, request: Request) -> None:
    """Redeem a reset link.

    The token is signed with a key derived from the account's *current* password hash, so
    setting the password invalidates this link and every other one outstanding for the account
    - single use, with no table and no expiry sweep. See `password_reset_key`.
    """
    ratelimit.enforce_password_reset(identifier="reset-redeem",
                                     client_ip=ratelimit.client_ip(request))

    # user_id isn't trusted here; it only selects whose hash the signature gets checked
    # against, so a forged id just fails that check.
    user_id = user_id_in_reset_token(body.token)
    row = await db.user_by_id(user_id) if user_id is not None else None
    if row is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, tr("auth.reset_invalid"))

    try:
        decode_password_reset_token(body.token, row["password_hash"])
    except jwt.PyJWTError as exc:
        # Same error for expired/used/forged: distinguishing them only helps someone who
        # didn't request the reset.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, tr("auth.reset_invalid")) from exc

    await db.set_password_hash(row["user_id"], hash_password(body.new_password))
    # A reset usually follows a lockout; clear the throttle too so they aren't made to
    # wait through it again.
    ratelimit.clear_login(identifier=row["email"], client_ip=ratelimit.client_ip(request))
    logger.info("", extra={"event": "auth.password_reset", "user_id": row["user_id"]})
