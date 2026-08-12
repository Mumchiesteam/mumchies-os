from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.order_read_model import OrderReadModel

def cache_orders(db: Session, orders: list) -> None:
    if not hasattr(db,"scalars"):return
    ids=[order.order_id for order in orders]
    existing={row.order_id:row for row in db.scalars(select(OrderReadModel).where(OrderReadModel.order_id.in_(ids))).all()} if ids else {}
    now=datetime.now(timezone.utc)
    for order in orders:
        row=existing.get(order.order_id)
        if row is None:
            row=OrderReadModel(order_id=order.order_id,order_number=str(order.order_number).lstrip("#"),updated_at=now);db.add(row)
        row.order_number=str(order.order_number).lstrip("#");row.customer_name=order.customer_name;row.payment_type=order.payment_type;row.order_value=float(order.order_total or order.total_amount);row.products=[{"product_name":item.product_name,"quantity":item.quantity,"price":float(item.price)} for item in order.products];row.updated_at=now
    if orders: db.commit()

def by_order_number(db:Session,numbers:set[str])->dict[str,OrderReadModel]:
    if not numbers:return {}
    rows=db.scalars(select(OrderReadModel).where(OrderReadModel.order_number.in_(numbers))).all()
    return {row.order_number:row for row in rows}

def enrich_ndr_cases(db:Session,cases:list)->None:
    cached=by_order_number(db,{str(case.order_number or case.order_id or "").lstrip("#") for case in cases});changed=False
    for case in cases:
        order=cached.get(str(case.order_number or case.order_id or "").lstrip("#"))
        if order and order.products and case.products!=order.products:case.products=order.products;changed=True
    if changed:db.flush()
