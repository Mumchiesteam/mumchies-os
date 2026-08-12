from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import mapped_column
from app.db.base import Base


class NDRCase(Base):
    __tablename__ = "ndr_cases"
    id = mapped_column(String(36), primary_key=True)
    awb = mapped_column(String(128), nullable=True, index=True)
    source_identity = mapped_column(String(320), nullable=True, unique=True, index=True)
    order_id = mapped_column(String(64), nullable=True, index=True)
    order_number = mapped_column(String(64), nullable=True, index=True)
    provider = mapped_column(String(32), nullable=False, index=True)
    courier_name = mapped_column(String(128), nullable=True)
    city = mapped_column(String(160), nullable=True)
    customer_name = mapped_column(String(160), nullable=True)
    customer_phone = mapped_column(String(32), nullable=True)
    customer_address = mapped_column(JSON, nullable=True)
    products = mapped_column(JSON, nullable=True)
    cod_amount = mapped_column(Float, nullable=False, default=0)
    shopify_order_url = mapped_column(Text, nullable=True)
    provider_tracking_url = mapped_column(Text, nullable=True)
    source_lifecycle = mapped_column(String(32), nullable=False, default="active", index=True)
    current_status = mapped_column(String(64), nullable=False, default="new", index=True)
    provider_status = mapped_column(String(128), nullable=True)
    failure_reason = mapped_column(Text, nullable=True, index=True)
    recommended_action = mapped_column(Text, nullable=True)
    whatsapp_message = mapped_column(Text, nullable=True)
    whatsapp_url = mapped_column(Text, nullable=True)
    priority = mapped_column(String(16), nullable=False, default="medium", index=True)
    delivery_attempts = mapped_column(Integer, nullable=False, default=1)
    assigned_to_user_id = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    assigned_to_name = mapped_column(String(120), nullable=True)
    first_ndr_at = mapped_column(DateTime(timezone=True), nullable=False)
    last_provider_update_at = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at = mapped_column(DateTime(timezone=True), nullable=False)
    customer_contacted_at = mapped_column(DateTime(timezone=True), nullable=True)
    courier_contacted_at = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_outcome = mapped_column(String(32), nullable=True, index=True)
    resolution_source = mapped_column(String(32), nullable=True, index=True)
    resolved_by_user_id = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_by_name = mapped_column(String(120), nullable=True)
    resolution_note = mapped_column(Text, nullable=True)
    raw_provider_data = mapped_column(JSON, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class NDREvent(Base):
    __tablename__ = "ndr_events"
    id = mapped_column(String(36), primary_key=True)
    case_id = mapped_column(String(36), ForeignKey("ndr_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = mapped_column(String(64), nullable=False, index=True)
    description = mapped_column(Text, nullable=False)
    actor_user_id = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    actor_name = mapped_column(String(120), nullable=True)
    event_data = mapped_column(JSON, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


class NDRSyncRun(Base):
    __tablename__ = "ndr_sync_runs"
    id = mapped_column(String(36), primary_key=True)
    source = mapped_column(String(32), nullable=False, default="all")
    trigger = mapped_column(String(32), nullable=False)
    status = mapped_column(String(32), nullable=False, index=True)
    lock_key = mapped_column(String(32), nullable=True, unique=True)
    started_at = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at = mapped_column(DateTime(timezone=True), nullable=True)
    cases_seen = mapped_column(Integer, nullable=False, default=0)
    cases_created = mapped_column(Integer, nullable=False, default=0)
    cases_updated = mapped_column(Integer, nullable=False, default=0)
    error = mapped_column(Text, nullable=True)
    source_health = mapped_column(JSON, nullable=True)
    actor_user_id = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    actor_name = mapped_column(String(120), nullable=True)


class NDRImportRun(Base):
    __tablename__ = "ndr_import_runs"
    id = mapped_column(String(36), primary_key=True)
    run_id = mapped_column(String(160), nullable=False, unique=True, index=True)
    schema_version = mapped_column(Integer, nullable=False)
    generated_at = mapped_column(DateTime(timezone=True), nullable=False)
    received_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status = mapped_column(String(32), nullable=False, index=True)
    source_health = mapped_column(JSON, nullable=False)
    source_counts = mapped_column(JSON, nullable=False)
    rows_received = mapped_column(Integer, nullable=False, default=0)
    created = mapped_column(Integer, nullable=False, default=0)
    updated = mapped_column(Integer, nullable=False, default=0)
    unchanged = mapped_column(Integer, nullable=False, default=0)
    rejected = mapped_column(Integer, nullable=False, default=0)
    safe_errors = mapped_column(JSON, nullable=True)
