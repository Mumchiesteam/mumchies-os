from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    username = mapped_column(String(64), unique=True, index=True, nullable=False)
    display_name = mapped_column(String(120), nullable=False)
    password_hash = mapped_column(String(255), nullable=False)
    role = mapped_column(String(20), nullable=False)
    is_active = mapped_column(Boolean, nullable=False, default=True)
    created_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    last_login_at = mapped_column(DateTime(timezone=True), nullable=True)
