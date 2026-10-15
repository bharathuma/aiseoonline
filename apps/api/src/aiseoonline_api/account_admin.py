"""Provision a local or production account without public self-registration.

Use an operator console over an authenticated secure shell. Never put passwords
or database connection strings on command lines.
"""

import argparse
import getpass

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiseoonline_api.accounts import _email, password_hash
from aiseoonline_api.config import Settings
from aiseoonline_api.db.models import User
from aiseoonline_api.db.session import create_database_engine


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision a password account")
    parser.add_argument("--email", required=True, help="Email verified by the operator")
    args = parser.parse_args()
    password = getpass.getpass("Account password (not echoed): ")
    confirmation = getpass.getpass("Repeat account password: ")
    if password != confirmation:
        raise SystemExit("Passwords did not match.")
    try:
        encoded = password_hash(password)
        email = _email(args.email)
    except ValueError as exc:
        raise SystemExit("Invalid account email or password length.") from exc
    settings = Settings()
    engine = create_database_engine(settings)
    try:
        with Session(engine) as session, session.begin():
            if session.scalar(select(User.id).where(User.email == email)) is not None:
                raise SystemExit("Account already exists; no changes made.")
            session.add(User(email=email, password_hash=encoded))
        print("Account provisioned. No password was written to command output.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
