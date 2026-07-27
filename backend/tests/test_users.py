from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.users import PasswordReset, UserUpdate, list_users, reset_password, update_user
from app.core.auth import hash_password, verify_password
from app.models.user import Base, User


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'users.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def request_for(user: User):
    return SimpleNamespace(state=SimpleNamespace(auth_user=user))


def seed(db):
    owner = User(username="owner", display_name="Owner", password_hash=hash_password("owner-password-123"), role="owner", is_active=True)
    admin = User(username="ajit", display_name="Ajit", password_hash=hash_password("admin-password-123"), role="admin", is_active=True)
    db.add_all([owner, admin])
    db.commit()
    db.refresh(owner)
    db.refresh(admin)
    return owner, admin


def test_owner_can_list_users_without_password_hashes(db):
    owner, _ = seed(db)
    response = list_users(request_for(owner), db)
    assert {user["username"] for user in response} == {"owner", "ajit"}
    assert all("password_hash" not in user for user in response)


def test_non_owner_cannot_manage_users(db):
    _, admin = seed(db)
    with pytest.raises(HTTPException) as error:
        list_users(request_for(admin), db)
    assert error.value.status_code == 403


def test_owner_account_cannot_be_deactivated_or_demoted(db):
    owner, _ = seed(db)
    for update in (UserUpdate(is_active=False), UserUpdate(role="admin")):
        with pytest.raises(HTTPException) as error:
            update_user(owner.id, update, request_for(owner), db)
        assert error.value.status_code == 409


def test_owner_can_change_admin_role_and_reset_password(db):
    owner, admin = seed(db)
    changed = update_user(admin.id, UserUpdate(role="operator", is_active=False), request_for(owner), db)
    assert changed["role"] == "operator" and changed["is_active"] is False
    response = reset_password(admin.id, PasswordReset(password="replacement-pass-123", password_confirmation="replacement-pass-123"), request_for(owner), db)
    assert response == {"status": "password_reset"}
    db.refresh(admin)
    assert admin.is_active is True
    assert verify_password("replacement-pass-123", admin.password_hash)
