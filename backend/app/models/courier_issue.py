from sqlalchemy import Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import mapped_column

from app.db.base import Base


class CourierIssue(Base):
    __tablename__ = "courier_issues"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    awb = mapped_column(String(128), nullable=False, index=True)
    date_raised = mapped_column(Date, nullable=False, index=True)
    raised_by = mapped_column(String(120), nullable=False, index=True)
    courier = mapped_column(String(120), nullable=False, index=True)
    issue_type = mapped_column(String(64), nullable=False, index=True)
    notes = mapped_column(Text, nullable=True)
    status = mapped_column(String(16), nullable=False, default="open", index=True)
    closure_date = mapped_column(Date, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
