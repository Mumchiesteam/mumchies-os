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


class ExternalTracking(BaseModel):
    """Shipment/fulfilment detected from Shopify's own fulfillments data - i.e. booked outside
    Mumchies OS. tracking_url is Shopify's own value when provided; otherwise a safe template
    URL for a small set of known/confident providers, or None (never a guessed URL)."""

    provider: str | None = None
    awb: str | None = None
    status: str | None = None
    tracking_url: str | None = None


class ShopifyOrder(BaseModel):
    order_id: str
    shopify_graphql_id: str | None = None
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
    order_total: Decimal = Decimal("0")
    paid_amount: Decimal = Decimal("0")
    outstanding_amount: Decimal = Decimal("0")
    cod_collectable_amount: Decimal = Decimal("0")
    payment_type: str = "prepaid"
    payment_gateway_names: list[str] = []
    transaction_summary: list[dict[str, str | Decimal | None]] = []
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
    address_sync_results: dict[str, str | dict[str, str | None]] | None = None
    package_details: dict[str, float | str | None] | None = None
    selected_courier: dict[str, str | float | None] | None = None
    shipment: dict[str, str | float | None] | None = None
    first_action_at: str | None = None
    human_action_count: int = 0
    call_attempt_count: int = 0
    external_tracking: ExternalTracking | None = None
