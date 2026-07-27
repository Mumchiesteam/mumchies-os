from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.core.identity import require_owner
from app.core.users import ROLES
from app.db.session import get_db
from app.models.user import User

router = APIRouter(prefix="/users", tags=["users"])


class UserUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=12)
    password_confirmation: str = Field(min_length=12)


def _public(user: User) -> dict[str, str | int | bool | None]:
    def stamp(value: datetime | None) -> str | None:
        return value.isoformat() if value else None
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role, "is_active": user.is_active, "created_at": stamp(user.created_at), "updated_at": stamp(user.updated_at), "last_login_at": stamp(user.last_login_at)}


@router.get("")
def list_users(request: Request, db: Session = Depends(get_db)) -> list[dict[str, object]]:
    require_owner(request)
    return [_public(user) for user in db.scalars(select(User).order_by(User.username)).all()]


@router.put("/{user_id}")
def update_user(user_id: int, payload: UserUpdate, request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    owner = require_owner(request)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if payload.role is not None:
        if payload.role not in ROLES:
            raise HTTPException(status_code=422, detail="Invalid role.")
        if user.role == "owner" and payload.role != "owner":
            raise HTTPException(status_code=409, detail="The owner role cannot be removed.")
        user.role = payload.role
    if payload.is_active is not None:
        if user.role == "owner" and not payload.is_active:
            raise HTTPException(status_code=409, detail="The owner account cannot be deactivated.")
        if user.id == owner.id and not payload.is_active:
            raise HTTPException(status_code=409, detail="You cannot deactivate your own account.")
        user.is_active = payload.is_active
    db.commit()
    db.refresh(user)
    return _public(user)


@router.post("/{user_id}/reset-password")
def reset_password(user_id: int, payload: PasswordReset, request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    require_owner(request)
    if payload.password != payload.password_confirmation:
        raise HTTPException(status_code=422, detail="Passwords do not match.")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    user.password_hash = hash_password(payload.password)
    user.is_active = True
    db.commit()
    return {"status": "password_reset"}
