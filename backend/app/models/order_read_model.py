from sqlalchemy import DateTime, Float, JSON, String
from sqlalchemy.orm import mapped_column
from app.db.base import Base

class OrderReadModel(Base):
    __tablename__ = "order_read_models"
    order_id = mapped_column(String(32), primary_key=True)
    order_number = mapped_column(String(64), nullable=False, unique=True, index=True)
    customer_name = mapped_column(String(300), nullable=True)
    payment_type = mapped_column(String(32), nullable=True)
    order_value = mapped_column(Float, nullable=True)
    products = mapped_column(JSON, nullable=True)
    updated_at = mapped_column(DateTime(timezone=True), nullable=False)
