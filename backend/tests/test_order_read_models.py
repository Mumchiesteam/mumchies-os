from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.services.order_read_models import cache_orders


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'read-model.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def order(*, customer_name: str = "Customer"):
    return SimpleNamespace(
        order_id="1", order_number="#1001", customer_name=customer_name,
        payment_type="cod", order_total=100, total_amount=100,
        products=[SimpleNamespace(product_name="Makhana", quantity=1, price=100)],
    )


def test_cache_orders_skips_commit_when_cached_order_is_unchanged(db, monkeypatch):
    cache_orders(db, [order()])
    original_commit = db.commit
    commits = 0

    def count_commit():
        nonlocal commits
        commits += 1
        return original_commit()

    monkeypatch.setattr(db, "commit", count_commit)
    cache_orders(db, [order()])

    assert commits == 0


def test_cache_orders_commits_when_order_read_model_data_changes(db, monkeypatch):
    cache_orders(db, [order()])
    original_commit = db.commit
    commits = 0

    def count_commit():
        nonlocal commits
        commits += 1
        return original_commit()

    monkeypatch.setattr(db, "commit", count_commit)
    cache_orders(db, [order(customer_name="Updated customer")])

    assert commits == 1
