from sqlalchemy import DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlalchemy.orm import mapped_column

from app.db.base import Base


class GstReportSnapshot(Base):
    __tablename__ = "gst_report_snapshots"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    month = mapped_column(String(7), nullable=False, unique=True, index=True)
    finalised_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    methodology_version = mapped_column(String(64), nullable=False)
    delivered_order_count = mapped_column(Integer, nullable=False)
    taxable_value = mapped_column(Numeric(16, 2), nullable=False)
    cgst = mapped_column(Numeric(16, 2), nullable=False)
    sgst = mapped_column(Numeric(16, 2), nullable=False)
    igst = mapped_column(Numeric(16, 2), nullable=False)
    total_gst = mapped_column(Numeric(16, 2), nullable=False)
    gross_sales = mapped_column(Numeric(16, 2), nullable=False)
    snapshot = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    csv_content = mapped_column(Text, nullable=False)
    checksum = mapped_column(String(64), nullable=False, unique=True)

