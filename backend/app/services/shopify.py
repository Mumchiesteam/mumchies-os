"""Read-only Shopify Admin API access used by Mumchies OS."""

from typing import Any

import httpx

from app.core.config import settings
from app.schemas.orders import OrderProduct, ShippingAddress, ShopifyOrder


class ShopifyConfigurationError(RuntimeError):
    """Raised when Shopify credentials have not been configured."""


class ShopifyService:
    """Small reusable, GET-only wrapper around the Shopify Admin API."""

    def __init__(self, store: str | None = None, access_token: str | None = None, api_version: str | None = None) -> None:
        self.store = (store or settings.shopify_store or "").removeprefix("https://").removesuffix("/")
        self.access_token = access_token or settings.shopify_access_token
        self.api_version = api_version or settings.shopify_api_version

    def _validate_configuration(self) -> None:
        if not all((self.store, self.access_token, self.api_version)):
            raise ShopifyConfigurationError("SHOPIFY_STORE, SHOPIFY_ACCESS_TOKEN, and SHOPIFY_API_VERSION must be configured.")

    async def get_latest_orders(self, limit: int = 100) -> list[ShopifyOrder]:
        """Fetch and normalize up to 100 recent orders. This method never writes to Shopify."""
        self._validate_configuration()
        fields = "id,order_number,created_at,customer,email,phone,shipping_address,line_items,total_price,financial_status,fulfillment_status,tags"
        url = f"https://{self.store}/admin/api/{self.api_version}/orders.json"
        params = {"status": "any", "limit": min(limit, 100), "order": "created_at desc", "fields": fields}
        headers = {"X-Shopify-Access-Token": self.access_token or ""}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
        return [self._to_order(order) for order in response.json().get("orders", [])]

    @staticmethod
    def _to_order(order: dict[str, Any]) -> ShopifyOrder:
        customer = order.get("customer") or {}
        address = order.get("shipping_address") or {}
        full_name = " ".join(part for part in [customer.get("first_name"), customer.get("last_name")] if part) or address.get("name")
        return ShopifyOrder(
            order_id=str(order["id"]),
            order_number=str(order.get("order_number", order["id"])),
            created_date=order["created_at"],
            customer_name=full_name,
            phone=order.get("phone") or customer.get("phone") or address.get("phone"),
            email=order.get("email") or customer.get("email"),
            shipping_address=ShippingAddress(name=address.get("name"), address=" ".join(filter(None, [address.get("address1"), address.get("address2")])) or None, landmark=None, city=address.get("city"), state=address.get("province"), pincode=address.get("zip")) if address else None,
            products=[OrderProduct(product_name=item.get("title", "Untitled product"), sku=item.get("sku"), quantity=item.get("quantity", 0), weight_grams=item.get("grams"), price=item.get("price", 0)) for item in order.get("line_items", [])],
            total_amount=order.get("total_price", 0),
            payment_status=order.get("financial_status"),
            fulfillment_status=order.get("fulfillment_status"),
            tags=[tag.strip() for tag in order.get("tags", "").split(",") if tag.strip()],
        )
