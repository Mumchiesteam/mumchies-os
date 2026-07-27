from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.users import PasswordReset, UserCreate, UserUpdate, create_user, list_users, reset_password, update_user
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


def test_owner_can_create_user_with_hashed_password(db):
    owner, _ = seed(db)
    created = create_user(UserCreate(username=" Rupesh ", display_name="Rupesh", role="admin", password="secure-password-123", password_confirmation="secure-password-123"), request_for(owner), db)
    assert created["username"] == "rupesh" and created["role"] == "admin"
    assert "password" not in created and "password_hash" not in created
    stored = db.query(User).filter_by(username="rupesh").one()
    assert stored.password_hash != "secure-password-123"
    assert verify_password("secure-password-123", stored.password_hash)


def test_duplicate_username_is_rejected_case_insensitively(db):
    owner, _ = seed(db)
    with pytest.raises(HTTPException) as error:
        create_user(UserCreate(username="AJIT", display_name="Another Ajit", role="operator", password="secure-password-123", password_confirmation="secure-password-123"), request_for(owner), db)
    assert error.value.status_code == 409
    assert error.value.detail == "That username is already in use."


@pytest.mark.parametrize("payload, message", [
    ({"username": "bad user", "display_name": "Bad", "role": "admin", "password": "secure-password-123", "password_confirmation": "secure-password-123"}, "Username must use"),
    ({"username": "newuser", "display_name": "   ", "role": "admin", "password": "secure-password-123", "password_confirmation": "secure-password-123"}, "Display name is required."),
    ({"username": "newuser", "display_name": "New User", "role": "owner", "password": "secure-password-123", "password_confirmation": "secure-password-123"}, "Role must be Admin or Operator."),
    ({"username": "newuser", "display_name": "New User", "role": "operator", "password": "secure-password-123", "password_confirmation": "different-password-123"}, "Passwords do not match."),
])
def test_create_user_validation_is_friendly(db, payload, message):
    owner, _ = seed(db)
    with pytest.raises(HTTPException) as error:
        create_user(UserCreate(**payload), request_for(owner), db)
    assert message in error.value.detail


@pytest.mark.parametrize("role", ["admin", "operator"])
def test_non_owner_roles_cannot_create_users(db, role):
    owner, admin = seed(db)
    actor = admin if role == "admin" else User(username="ops", display_name="Ops", password_hash=hash_password("operator-pass-123"), role="operator", is_active=True)
    if role == "operator":
        db.add(actor); db.commit(); db.refresh(actor)
    with pytest.raises(HTTPException) as error:
        create_user(UserCreate(username="blocked", display_name="Blocked", role="operator", password="secure-password-123", password_confirmation="secure-password-123"), request_for(actor), db)
    assert error.value.status_code == 403


def test_owner_can_deactivate_and_reactivate_user(db):
    owner, admin = seed(db)
    assert update_user(admin.id, UserUpdate(is_active=False), request_for(owner), db)["is_active"] is False
    assert update_user(admin.id, UserUpdate(is_active=True), request_for(owner), db)["is_active"] is True


def test_short_create_password_is_rejected_before_handler():
    with pytest.raises(ValidationError) as error:
        UserCreate(username="newuser", display_name="New User", role="operator", password="short", password_confirmation="short")
    assert "at least 12 characters" in str(error.value)


@pytest.mark.parametrize("role", ["admin", "operator"])
def test_non_owner_roles_cannot_update_or_reset_users(db, role):
    owner, admin = seed(db)
    actor = admin if role == "admin" else User(username="ops", display_name="Ops", password_hash=hash_password("operator-pass-123"), role="operator", is_active=True)
    if role == "operator":
        db.add(actor); db.commit(); db.refresh(actor)
    with pytest.raises(HTTPException) as update_error:
        update_user(admin.id, UserUpdate(is_active=False), request_for(actor), db)
    with pytest.raises(HTTPException) as reset_error:
        reset_password(admin.id, PasswordReset(password="replacement-pass-123", password_confirmation="replacement-pass-123"), request_for(actor), db)
    assert update_error.value.status_code == 403
    assert reset_error.value.status_code == 403
