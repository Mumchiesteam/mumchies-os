from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import mapped_column

from app.db.base import Base


class CourierFinancialCase(Base):
    __tablename__ = "courier_financial_cases"
    __table_args__ = (UniqueConstraint("provider", "awb", name="uq_financial_case_provider_awb"),)
    id = mapped_column(String(36), primary_key=True)
    provider = mapped_column(String(32), nullable=False, index=True)
    awb = mapped_column(String(128), nullable=False, index=True)
    order_id = mapped_column(String(64), nullable=True, index=True)
    order_number = mapped_column(String(64), nullable=True, index=True)
    courier_name = mapped_column(String(128), nullable=True)
    shipment_status = mapped_column(String(64), nullable=True)
    booked_at = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at = mapped_column(DateTime(timezone=True), nullable=True)
    rto_at = mapped_column(DateTime(timezone=True), nullable=True)
    expected_cod = mapped_column(Float, nullable=True)
    expected_freight = mapped_column(Float, nullable=True)
    declared_weight_g = mapped_column(Float, nullable=True)
    declared_dimensions = mapped_column(JSON, nullable=True)
    remitted_cod = mapped_column(Float, nullable=True)
    actual_freight = mapped_column(Float, nullable=True)
    weight_excess_charge = mapped_column(Float, nullable=True)
    other_debits = mapped_column(Float, nullable=True)
    credits_refunds = mapped_column(Float, nullable=True)
    net_variance = mapped_column(Float, nullable=True)
    primary_issue_type = mapped_column(String(64), nullable=True, index=True)
    issue_summary = mapped_column(Text, nullable=True)
    amount_at_risk = mapped_column(Float, nullable=False, default=0)
    action_deadline = mapped_column(DateTime(timezone=True), nullable=True)
    age_days = mapped_column(Integer, nullable=False, default=0)
    priority = mapped_column(String(16), nullable=True, index=True)
    os_status = mapped_column(String(32), nullable=False, default="Needs Action", index=True)
    assigned_to_user_id = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    assigned_to_name = mapped_column(String(120), nullable=True)
    action_note = mapped_column(Text, nullable=True)
    last_action_at = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CourierFinancialDocument(Base):
    __tablename__ = "courier_financial_documents"
    id = mapped_column(String(36), primary_key=True)
    provider = mapped_column(String(32), nullable=False, index=True)
    document_type = mapped_column(String(64), nullable=False, index=True)
    filename = mapped_column(String(512), nullable=False)
    period = mapped_column(String(128), nullable=True)
    checksum = mapped_column(String(64), nullable=False, unique=True, index=True)
    parser_version = mapped_column(String(32), nullable=False)
    source_metadata = mapped_column(JSON, nullable=True)
    imported_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CourierFinancialLedgerEntry(Base):
    __tablename__ = "courier_financial_ledger_entries"
    __table_args__ = (UniqueConstraint("document_id", "source_row_hash", name="uq_financial_document_row"),)
    id = mapped_column(String(36), primary_key=True)
    document_id = mapped_column(String(36), ForeignKey("courier_financial_documents.id"), nullable=False, index=True)
    provider = mapped_column(String(32), nullable=False, index=True)
    awb = mapped_column(String(128), nullable=True, index=True)
    component = mapped_column(String(64), nullable=False, index=True)
    debit = mapped_column(Float, nullable=False, default=0)
    credit = mapped_column(Float, nullable=False, default=0)
    net_amount = mapped_column(Float, nullable=True)
    tax_amount = mapped_column(Float, nullable=True)
    gross_amount = mapped_column(Float, nullable=True)
    provider_reference_id = mapped_column(String(160), nullable=True, index=True)
    invoice_or_remittance_id = mapped_column(String(160), nullable=True, index=True)
    occurred_at = mapped_column(DateTime(timezone=True), nullable=True)
    remarks = mapped_column(Text, nullable=True)
    source_row_number = mapped_column(Integer, nullable=False)
    source_row_hash = mapped_column(String(64), nullable=False)
    raw_row = mapped_column(JSON, nullable=False)
    imported_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CourierSettlement(Base):
    __tablename__ = "courier_settlements"
    __table_args__ = (UniqueConstraint("provider", "settlement_id", name="uq_courier_settlement"),)
    id = mapped_column(String(36), primary_key=True)
    provider = mapped_column(String(32), nullable=False, index=True)
    settlement_id = mapped_column(String(160), nullable=False, index=True)
    processed_at = mapped_column(DateTime(timezone=True), nullable=True)
    bank_reference = mapped_column(String(160), nullable=True)
    status = mapped_column(String(64), nullable=True)
    gross_amount = mapped_column(Float, nullable=True)
    deductions = mapped_column(Float, nullable=True)
    net_paid = mapped_column(Float, nullable=True)
    allocations = mapped_column(JSON, nullable=True)
    document_id = mapped_column(String(36), ForeignKey("courier_financial_documents.id"), nullable=True)


class CourierFinancialAction(Base):
    __tablename__ = "courier_financial_actions"
    id = mapped_column(String(36), primary_key=True)
    case_id = mapped_column(String(36), ForeignKey("courier_financial_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    action = mapped_column(String(64), nullable=False)
    note = mapped_column(Text, nullable=True)
    actor_user_id = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    actor_name = mapped_column(String(120), nullable=True)
    created_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CourierFinancialUnmatchedRow(Base):
    __tablename__ = "courier_financial_unmatched_rows"
    id = mapped_column(String(36), primary_key=True)
    document_id = mapped_column(String(36), ForeignKey("courier_financial_documents.id"), nullable=False, index=True)
    provider = mapped_column(String(32), nullable=False, index=True)
    awb_or_reference = mapped_column(String(160), nullable=True)
    amount = mapped_column(Float, nullable=True)
    reason = mapped_column(String(256), nullable=False)
    source_row_number = mapped_column(Integer, nullable=False)
    source_row_hash = mapped_column(String(64), nullable=False)
    raw_row = mapped_column(JSON, nullable=False)
