"""Create or update one login, without touching anything else.

`seed.py` also creates users, but it opens with `TRUNCATE app_user CASCADE` - which is right
for building a demo database from nothing and catastrophic on a live one, because the cascade
takes every saved card and audit row with it. Onboarding a customer is not seeding, so it is
its own script.

    python scripts/add_user.py --email ali@solvigo.se \\
                              --name "Ali Shirzad" \\
                              --supplier "Nordström Audio AB"

The password is prompted for, never passed as an argument: a command line ends up in shell
history, in `ps` output and in CI logs. `--generate` prints one strong password once instead.

This only creates the *login*. What that login can see is decided entirely by the supplier it
points at: `supplier_id` is the value Postgres RLS compares against, so the brands owned by
that supplier (`dim_brand.supplier_id`) are what defines their data. If a brand is attributed
to the wrong supplier, this script cannot help - fix the attribution first.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import secrets
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from console import use_utf8_stdout  # noqa: E402
from seed import connect  # noqa: E402

from api.auth import hash_password  # noqa: E402
from api.config import settings  # noqa: E402

ROLES = ("supplier_viewer", "supplier_admin", "retail_analyst", "system_admin")

# The two roles that read supplier data, and therefore the two that need a supplier.
SUPPLIER_ROLES = ("supplier_viewer", "supplier_admin")


def read_password(generate: bool) -> str:
    """Prompt twice, or mint one. Never taken from argv."""
    if generate:
        # 96 bits of entropy - far past anything a person would choose, still short enough
        # to read down a phone line once.
        password = secrets.token_urlsafe(12)
        print(f"\n  generated password: {password}")
        print("  Give this to the user over a channel that is not this terminal's scrollback,")
        print("  and have them change it after the first login.\n")
        return password

    password = getpass.getpass("  password: ")
    if password != getpass.getpass("  repeat:   "):
        raise SystemExit("passwords did not match")
    if len(password) < settings.password_min_length:
        raise SystemExit(f"password must be at least {settings.password_min_length} characters "
                         f"(PASSWORD_MIN_LENGTH)")
    return password


async def resolve_supplier(connection: asyncpg.Connection, name: str | None,
                           role: str) -> int | None:
    """The supplier this login is scoped to, or None for a role that has no supplier."""
    if role not in SUPPLIER_ROLES:
        if name:
            raise SystemExit(f"role {role!r} is not supplier-scoped; drop --supplier")
        return None

    if not name:
        raise SystemExit(f"role {role!r} needs --supplier")

    supplier_id = await connection.fetchval(
        "SELECT supplier_id FROM dim_supplier WHERE lower(name) = lower($1)", name)
    if supplier_id is None:
        known = await connection.fetch("SELECT name FROM dim_supplier ORDER BY name")
        listed = "\n    ".join(row["name"] for row in known) or "(none - is the database seeded?)"
        raise SystemExit(f"no supplier named {name!r}. Known suppliers:\n    {listed}")

    # An account pointed at a supplier with no brands sees an empty dashboard and looks broken.
    brands = await connection.fetchval(
        "SELECT COUNT(*) FROM dim_brand WHERE supplier_id = $1", supplier_id)
    if not brands:
        print(f"  warning: {name} owns no brands in dim_brand, so this login will see no "
              f"data.\n           Attribute their brands first, then re-run.")
    return int(supplier_id)


async def upsert_user(connection: asyncpg.Connection, *, email: str, name: str,
                      role: str, supplier_id: int | None, password_hash: str) -> str:
    """Insert, or update the existing row for this address. Never deletes anything.

    `ON CONFLICT` rather than delete-then-insert because `user_id` is referenced by
    `saved_card` and `audit_turn`: replacing the row would either fail on the foreign key or,
    with a cascade, silently discard the customer's saved views.
    """
    existed = await connection.fetchval(
        "SELECT user_id FROM app_user WHERE lower(email) = lower($1)", email)
    await connection.execute(
        """
        INSERT INTO app_user (email, password_hash, supplier_id, role, display_name)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (email) DO UPDATE
           SET password_hash = EXCLUDED.password_hash,
               supplier_id   = EXCLUDED.supplier_id,
               role          = EXCLUDED.role,
               display_name  = EXCLUDED.display_name
        """,
        email, password_hash, supplier_id, role, name)
    return "updated" if existed else "created"


async def main() -> None:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True, help="display name, shown in the sidebar")
    parser.add_argument("--supplier", help="dim_supplier.name; required for a supplier role")
    parser.add_argument("--role", default="supplier_admin", choices=ROLES)
    parser.add_argument("--generate", action="store_true",
                        help="mint a strong password and print it instead of prompting")
    args = parser.parse_args()

    email = args.email.strip().lower()
    if "@" not in email:
        raise SystemExit(f"not an email address: {email!r}")

    connection = await connect()
    try:
        supplier_id = await resolve_supplier(connection, args.supplier, args.role)
        password = read_password(args.generate)
        # Hashed with the API's own function, so cost parameters can't drift from what
        # verify_password was tuned for.
        action = await upsert_user(connection, email=email, name=args.name, role=args.role,
                                   supplier_id=supplier_id,
                                   password_hash=hash_password(password))
        scope = args.supplier or "no supplier (not supplier-scoped)"
        print(f"  {action}: {email} → {scope} ({args.role})")
    finally:
        await connection.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
