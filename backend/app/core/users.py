from __future__ import annotations

import getpass
import sys

from sqlalchemy import select

from app.core.auth import hash_password
from app.db.session import SessionLocal
from app.models.user import User

ROLES = {"owner", "admin", "operator"}


def normalize_username(value: str) -> str:
    username = value.strip().casefold()
    if not username or len(username) > 64 or not all(character.isalnum() or character in "._-" for character in username):
        raise ValueError("Username must use 1-64 letters, numbers, dots, underscores, or hyphens.")
    return username


def _prompt_password() -> str:
    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise ValueError("Passwords do not match.")
    return hash_password(password)


def _main() -> int:
    command = sys.argv[1] if len(sys.argv) == 2 else ""
    if command not in {"create-user", "reset-user"}:
        print("Usage: python -m app.core.users {create-user|reset-user}", file=sys.stderr)
        return 2
    try:
        username = normalize_username(input("Username: "))
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.username == username))
            if command == "reset-user":
                if user is None:
                    raise ValueError("User does not exist.")
                user.password_hash = _prompt_password()
                user.is_active = True
                db.commit()
                print(f"Password reset for {username}.")
                return 0
            if user is not None:
                raise ValueError("User already exists; use reset-user.")
            display_name = input("Display name: ").strip()
            role = input("Role (owner/admin/operator): ").strip().casefold()
            if not display_name:
                raise ValueError("Display name is required.")
            if role not in ROLES:
                raise ValueError("Role must be owner, admin, or operator.")
            db.add(User(username=username, display_name=display_name, role=role, password_hash=_prompt_password(), is_active=True))
            db.commit()
            print(f"Created {username} as {role}.")
            return 0
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
