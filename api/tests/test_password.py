"""Password change and reset - the properties that matter if they break silently."""

from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

from api import auth, db, mail, ratelimit
from api.config import settings
from api.main import app


@pytest.fixture(autouse=True)
def _clear_throttles():
    """Each test starts with its full allowance; the reset window is only 3 per identifier."""
    for window in (ratelimit.reset_by_identifier, ratelimit.reset_by_ip,
                   ratelimit.login_by_identifier, ratelimit.login_by_ip):
        window._hits.clear()
    yield


@pytest.fixture
def account(monkeypatch):
    """One user in a fake database, plus whatever mail the flow tried to send.

    The store is a dict rather than Postgres because none of this is about SQL: it is about
    which token verifies against which hash, and that is decided in api/auth.py.
    """
    state = {
        "user_id": 7,
        "email": "ali@solvigo.se",
        "display_name": "Ali Shirzad",
        "role": "supplier_admin",
        "supplier_id": 1,
        "supplier_name": "Nordström Audio AB",
        "password_hash": auth.hash_password("original-password"),
    }
    sent: list[dict] = []

    async def user_by_email(email: str):
        return dict(state) if email.lower() == state["email"] else None

    async def user_by_id(user_id: int):
        return dict(state) if user_id == state["user_id"] else None

    async def set_password_hash(user_id: int, password_hash: str) -> bool:
        state["password_hash"] = password_hash
        return True

    monkeypatch.setattr(db, "user_by_email", user_by_email)
    monkeypatch.setattr(db, "user_by_id", user_by_id)
    monkeypatch.setattr(db, "set_password_hash", set_password_hash)
    monkeypatch.setattr(mail, "send", lambda **kwargs: sent.append(kwargs))

    state["sent"] = sent
    return state


@pytest.fixture
def client():
    # No lifespan: it opens a Postgres pool, and every DB call here is patched.
    return TestClient(app)


def link_token(sent: list[dict]) -> str:
    """The token out of the reset mail, the way the recipient would get it."""
    assert sent, "no mail was sent"
    body = sent[-1]["body"]
    return body.split("/#/aterstall/")[1].split()[0]


def token_for(account: dict) -> str:
    return auth.create_password_reset_token(account)[0]


def bearer(account: dict) -> dict:
    return {"Authorization": f"Bearer {auth.create_access_token(account)}"}



def test_a_reset_token_verifies_against_the_hash_it_was_minted_for(account):
    token = token_for(account)
    claims = auth.decode_password_reset_token(token, account["password_hash"])
    assert claims["sub"] == "7"


def test_redeeming_a_reset_link_burns_it(account):
    """The property the whole design turns on.

    The token is signed with a key derived from the current password hash, so setting a new
    password changes the key and every token minted under the old one stops verifying. No
    table, no nonce column, no expiry sweep - and no way to replay a link out of an inbox.
    """
    token = token_for(account)
    old_hash = account["password_hash"]
    account["password_hash"] = auth.hash_password("something-else")

    auth.decode_password_reset_token(token, old_hash)  # still valid against the old hash
    with pytest.raises(jwt.PyJWTError):
        auth.decode_password_reset_token(token, account["password_hash"])


def test_one_users_token_does_not_verify_against_another(account):
    other = auth.hash_password("a-different-users-password")
    with pytest.raises(jwt.PyJWTError):
        auth.decode_password_reset_token(token_for(account), other)


def test_an_access_token_is_not_accepted_as_a_reset_token(account):
    """Both are JWTs. Only one of them may set a password."""
    access = auth.create_access_token(account)
    with pytest.raises(jwt.PyJWTError):
        auth.decode_password_reset_token(access, account["password_hash"])


def test_the_user_id_is_read_without_being_trusted(account):
    assert auth.user_id_in_reset_token(token_for(account)) == 7
    assert auth.user_id_in_reset_token("not-a-jwt") is None
    # Forged sub, signed with an attacker's own key: it parses fine - it only decides whose
    # hash the signature is checked against, which is what fails below.
    forged = jwt.encode({"typ": "reset", "sub": "7"}, "attacker-key", algorithm="HS256")
    assert auth.user_id_in_reset_token(forged) == 7
    with pytest.raises(jwt.PyJWTError):
        auth.decode_password_reset_token(forged, account["password_hash"])



def test_forgot_answers_identically_for_known_and_unknown_addresses(account, client):
    """This route must not become a way to enumerate a retailer's suppliers."""
    known = client.post("/api/auth/password/forgot", json={"email": account["email"]})
    unknown = client.post("/api/auth/password/forgot", json={"email": "nobody@example.com"})

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    # And the difference that does exist is invisible: one mail, not two.
    assert len(account["sent"]) == 1


def test_a_mail_failure_does_not_change_the_answer(account, client, monkeypatch):
    """Otherwise "does this address exist" is answerable by breaking the mail server."""
    def explode(**_kwargs):
        raise RuntimeError("smtp is down")

    monkeypatch.setattr(mail, "send", explode)
    response = client.post("/api/auth/password/forgot", json={"email": account["email"]})
    assert response.status_code == 202


def test_forgot_is_throttled_per_address(account, client):
    """An unthrottled reset endpoint is a way to mailbomb a real person."""
    for _ in range(3):
        assert client.post("/api/auth/password/forgot",
                           json={"email": account["email"]}).status_code == 202
    assert client.post("/api/auth/password/forgot",
                       json={"email": account["email"]}).status_code == 429



def test_a_reset_link_sets_the_password_and_cannot_be_replayed(account, client):
    client.post("/api/auth/password/forgot", json={"email": account["email"]})
    token = link_token(account["sent"])

    assert client.post("/api/auth/password/reset",
                       json={"token": token, "new_password": "brand-new-password"}
                       ).status_code == 204
    assert auth.verify_password("brand-new-password", account["password_hash"])

    # The same link again, which is what an attacker with inbox access would try.
    replay = client.post("/api/auth/password/reset",
                         json={"token": token, "new_password": "attacker-password"})
    assert replay.status_code == 400
    assert auth.verify_password("brand-new-password", account["password_hash"])


def test_a_reset_rejects_a_password_under_the_minimum(account, client):
    client.post("/api/auth/password/forgot", json={"email": account["email"]})
    token = link_token(account["sent"])
    response = client.post("/api/auth/password/reset",
                           json={"token": token, "new_password": "short"})
    assert response.status_code == 422
    assert auth.verify_password("original-password", account["password_hash"])


def test_a_garbage_token_is_a_400_not_a_500(account, client):
    assert client.post("/api/auth/password/reset",
                       json={"token": "nonsense", "new_password": "long-enough-password"}
                       ).status_code == 400



def test_changing_a_password_requires_the_current_one(account, client):
    """A borrowed session must not become permanent account takeover."""
    response = client.post("/api/auth/password", headers=bearer(account),
                           json={"current_password": "wrong", "new_password": "a-new-password"})
    assert response.status_code == 403
    assert auth.verify_password("original-password", account["password_hash"])


def test_changing_a_password_works_with_the_current_one(account, client):
    response = client.post(
        "/api/auth/password", headers=bearer(account),
        json={"current_password": "original-password", "new_password": "a-new-password"})
    assert response.status_code == 204
    assert auth.verify_password("a-new-password", account["password_hash"])


def test_changing_a_password_needs_a_session(account, client):
    assert client.post("/api/auth/password",
                       json={"current_password": "original-password",
                             "new_password": "a-new-password"}).status_code == 401


def test_a_change_invalidates_outstanding_reset_links(account, client):
    """Someone who changes their password should not leave a live reset link behind them."""
    client.post("/api/auth/password/forgot", json={"email": account["email"]})
    token = link_token(account["sent"])

    client.post("/api/auth/password", headers=bearer(account),
                json={"current_password": "original-password", "new_password": "a-new-password"})

    assert client.post("/api/auth/password/reset",
                       json={"token": token, "new_password": "attacker-password"}
                       ).status_code == 400



@pytest.mark.parametrize("password, ok", [
    ("a" * (settings.password_min_length - 1), False),
    ("a" * settings.password_min_length, True),
    ("a" * 201, False),  # unbounded input is unbounded Argon2 work per request
])
def test_the_length_policy_is_enforced_at_the_boundary(password, ok):
    from pydantic import ValidationError

    from api.models import NewPassword

    if ok:
        assert NewPassword(new_password=password).new_password == password
    else:
        with pytest.raises(ValidationError):
            NewPassword(new_password=password)
