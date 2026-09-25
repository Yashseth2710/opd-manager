"""Makes a platform administrator, from the server's command line.

    python -m app.platform_admin --email ops@example.org --first Asha --last Rao

The password is asked for twice at the prompt, or read from
PLATFORM_ADMIN_PASSWORD where nobody is there to type it. There is no route
in the application that can make one of these accounts, on purpose: whoever
can run this already holds the database.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import getpass
import os
import sys

from pydantic import EmailStr, TypeAdapter, ValidationError

from app.core.security import hash_password, password_problem
from app.db.session import get_factory
from app.models import User
from app.repositories.users import UserRepository

_EMAIL = TypeAdapter(EmailStr)


def _password(email: str, name: str) -> str:
    supplied = os.environ.get("PLATFORM_ADMIN_PASSWORD")
    if supplied:
        chosen = supplied
    else:
        chosen = getpass.getpass("Password: ")
        if getpass.getpass("Same again: ") != chosen:
            raise SystemExit("The two passwords are different.")
    problem = password_problem(chosen, email=email, name=name)
    if problem:
        raise SystemExit(problem)
    return chosen


async def create(email: str, first_name: str, last_name: str) -> None:
    async with get_factory()() as session:
        # Refused outright if the address is in use anywhere, a clinic
        # included, so signing in never has to choose between the platform
        # and somebody's clinic.
        if await UserRepository(session).accounts_for_email(email):
            raise SystemExit(f"{email} already has an account. Use another address.")
        password = _password(email, f"{first_name}{last_name}")
        session.add(
            User(
                organization_id=None,
                email=email,
                password_hash=hash_password(password),
                first_name=first_name,
                last_name=last_name,
                status="active",
                email_verified_at=dt.datetime.now(dt.UTC),
            )
        )
        await session.commit()
    print(f"{first_name} {last_name} <{email}> can now sign in to the platform.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Make a platform administrator.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--first", required=True, dest="first_name")
    parser.add_argument("--last", required=True, dest="last_name")
    args = parser.parse_args(argv)

    try:
        email = str(_EMAIL.validate_python(args.email.strip())).lower()
    except ValidationError:
        raise SystemExit("That is not an email address.") from None
    first = args.first_name.strip()[:80]
    last = args.last_name.strip()[:80]
    if not first or not last:
        raise SystemExit("Give a first and a last name.")
    asyncio.run(create(email, first, last))


if __name__ == "__main__":
    main(sys.argv[1:])
