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
    created_date: str
    customer_name: str | None = None
    phone: str | None = None
    email: str | None = None
    shipping_address: ShippingAddress | None = None
    products: list[OrderProduct]
    total_amount: Decimal
    payment_status: str | None = None
    fulfillment_status: str | None = None
    tags: list[str]
