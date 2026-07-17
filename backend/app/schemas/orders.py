from decimal import Decimal

from pydantic import BaseModel


class ShippingAddress(BaseModel):
    name: str | None = None
    address: str | None = None
    landmark: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None


class OrderProduct(BaseModel):
    product_name: str
    sku: str | None = None
    quantity: int
    weight_grams: int | None = None
    price: Decimal


class ShopifyOrder(BaseModel):
    order_id: str
    order_number: str
    shopify_name: str | None = None
    created_date: str
    cancelled_at: str | None = None
    shopify_status: str | None = None
    customer_name: str | None = None
    phone: str | None = None
    email: str | None = None
    shipping_address: ShippingAddress | None = None
    customer_id: str | None = None
    customer_orders_count: int | None = None
    products: list[OrderProduct]
    total_amount: Decimal
    shipping_amount: Decimal | None = None
    payment_status: str | None = None
    fulfillment_status: str | None = None
    tags: list[str]
    latest_call_result: str | None = None
    operational_status: str | None = None
    address_verified: bool = False
    address_verified_at: str | None = None
    address_verified_by: str | None = None
    verified_address_snapshot: dict[str, str | None] | None = None
    corrected_address: dict[str, str | None] | None = None
    courier_sync_status: str | None = None
    courier_sync_error: str | None = None
