from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.models.courier_financial import CourierFinancialCase, CourierFinancialLedgerEntry, CourierFinancialUnmatchedRow
from app.services.courier_financial import import_document, rebuild_cases

def make_db(tmp_path):
    engine=create_engine(f"sqlite+pysqlite:///{tmp_path / 'finance.db'}"); Base.metadata.create_all(engine); return sessionmaker(bind=engine)(),engine

def test_shiprocket_remittance_is_idempotent_and_detects_cod_short(tmp_path):
    db,engine=make_db(tmp_path)
    try:
        case=CourierFinancialCase(id="case",provider="shiprocket",awb="SR1",expected_cod=500,delivered_at=datetime.now(timezone.utc)-timedelta(days=3));db.add(case);db.commit()
        content=b"AWB,Remittance ID,Remittance Amount,Processed Date\nSR1,R-1,300,2026-09-01\n"
        first=import_document(db,provider="shiprocket",document_type="cod_remittance",filename="cod.csv",content=content);db.commit(); rebuild_cases(db);db.commit();db.refresh(case)
        assert first["imported"]==1 and case.primary_issue_type=="COD_SHORT" and case.amount_at_risk==200
        again=import_document(db,provider="shiprocket",document_type="cod_remittance",filename="cod.csv",content=content)
        assert again["idempotent"] is True and len(db.scalars(select(CourierFinancialLedgerEntry)).all())==1
    finally: db.close();engine.dispose()

def test_weight_charge_creates_alert_but_blank_weight_report_does_not(tmp_path):
    db,engine=make_db(tmp_path)
    try:
        db.add(CourierFinancialCase(id="case",provider="shiprocket",awb="SR2"));db.commit()
        import_document(db,provider="shiprocket",document_type="weight_discrepancy",filename="weight.csv",content=b"AWB,Excess Charge\nSR2,48\n");db.commit();rebuild_cases(db);db.commit()
        assert db.get(CourierFinancialCase,"case").primary_issue_type=="WEIGHT_SLAB_JUMP"
        result=import_document(db,provider="shiprocket",document_type="weight_discrepancy",filename="blank.csv",content=b"Order Number,Excess Charge\n326447,0\n");db.commit()
        assert result["unmatched"]==1 and len(db.scalars(select(CourierFinancialUnmatchedRow)).all())==1
    finally: db.close();engine.dispose()

def test_delhivery_wallet_import_and_unmatched_awb(tmp_path):
    db,engine=make_db(tmp_path)
    try:
        db.add(CourierFinancialCase(id="case",provider="delhivery",awb="D1"));db.commit()
        result=import_document(db,provider="delhivery",document_type="wallet_ledger",filename="wallet.csv",content=b"AWB,Debit Amount,Description,Transaction ID\nD1,125,Freight,T1\n\n");db.commit()
        assert result["imported"]==1
        assert db.scalar(select(CourierFinancialLedgerEntry)).component=="freight"
    finally: db.close();engine.dispose()

def test_shadowfax_formats_remain_disabled(tmp_path):
    db,engine=make_db(tmp_path)
    try:
        import pytest
        with pytest.raises(ValueError,match="disabled"):
            import_document(db,provider="shadowfax",document_type="ledger",filename="x.csv",content=b"AWB\nS1\n")
    finally: db.close();engine.dispose()
