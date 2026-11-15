"""``make create-user EMAIL= ROLE= PLAN=``: a demo or staff user with a manual plan (task 2.1).

Development and staging only: it refuses unless ``APP_ENV`` is ``development`` or ``staging``
(fail closed; customers sign up and pay, staff are created through the admin app). The
password comes from ``CREATE_USER_PASSWORD`` or is generated and shown once; only its Argon2id
hash is stored. A paid plan gets an active ``source='manual'`` subscription; the default plan
needs none.
"""

from __future__ import annotations

import os
import secrets
import sys

from argon2 import PasswordHasher
from sqlalchemy import Connection, create_engine
from sqlalchemy.exc import SQLAlchemyError

from tradelens.modules.accounts.public import AccountError, create_account, validate_account
from tradelens.modules.billing.public import create_manual_subscription, plan_is_default

EXIT_OK, EXIT_FAILED = 0, 1
ARG_COUNT = 3
CONNECT_TIMEOUT_SECONDS = 5
GENERATED_PASSWORD_BYTES = 12
ALLOWED_ENVS = ("development", "staging")
USAGE = "usage: python -m tradelens.cli create-user EMAIL ROLE PLAN\n"


def hash_password(password: str) -> str:
    """Argon2id hash with the library's current defaults (verified by the API in task 2.4)."""
    return PasswordHasher().hash(password)


def create_user(conn: Connection, email: str, role: str, plan: str, password_hash: str) -> str:
    """Create the user and, for a non-default plan, its manual subscription.

    Args:
        conn: Connection inside the caller's transaction.
        email: E-mail address.
        role: ``customer``, ``support`` or ``admin``.
        plan: Plan code (must exist in ``plans``).
        password_hash: Argon2id hash.

    Returns:
        The new user's UUID.

    Raises:
        ValueError: On an unknown plan, a bad e-mail or role, or an e-mail in use.
    """
    is_default = plan_is_default(conn, plan)  # raises for an unknown plan before any insert
    user_id = create_account(conn, email, role, password_hash)
    if not is_default:
        create_manual_subscription(conn, user_id, plan)
    return user_id


def main(argv: list[str]) -> int:
    """Create one user in the database named by DATABASE_MIGRATION_URL.

    Args:
        argv: ``[EMAIL, ROLE, PLAN]``.

    Returns:
        0 on success, 1 on any refusal or failure.
    """
    app_env = os.environ.get("APP_ENV", "")
    if app_env not in ALLOWED_ENVS:  # fail closed: unset or unknown counts as production
        got = app_env or "unset"
        sys.stderr.write("create-user: refused unless APP_ENV is development or staging"
                         f" (got {got}; production customers sign up)\n")  # fmt: skip
        return EXIT_FAILED
    if len(argv) != ARG_COUNT:
        sys.stderr.write(USAGE)
        return EXIT_FAILED
    email, role, plan = argv
    try:
        validate_account(email, role)  # cheap checks before touching the database
    except AccountError as exc:
        sys.stderr.write(f"create-user: {exc}\n")
        return EXIT_FAILED
    url = os.environ.get("DATABASE_MIGRATION_URL")
    if not url:
        sys.stderr.write("create-user: set DATABASE_MIGRATION_URL\n")
        return EXIT_FAILED
    given = os.environ.get("CREATE_USER_PASSWORD", "")
    password = given or secrets.token_urlsafe(GENERATED_PASSWORD_BYTES)
    engine = create_engine(url, connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS})
    try:
        with engine.begin() as conn:
            user_id = create_user(conn, email, role, plan, hash_password(password))
    except (SQLAlchemyError, ValueError) as exc:
        sys.stderr.write(f"create-user: failed ({type(exc).__name__}): {exc}\n")
        return EXIT_FAILED
    finally:
        engine.dispose()
    sys.stdout.write(f"create-user: {email} ({role}, plan {plan}) id {user_id}\n")
    if not given:
        sys.stdout.write(f"create-user: generated password (shown once): {password}\n")
    return EXIT_OK
