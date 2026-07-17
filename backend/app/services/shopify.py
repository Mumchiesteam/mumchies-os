"""Read-only Shopify Admin API access used by Mumchies OS."""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.orders import OrderProduct, ShippingAddress, ShopifyOrder


class ShopifyConfigurationError(RuntimeError):
    """Raised when Shopify credentials have not been configured."""


class ShopifyService:
    """Small reusable, GET-only wrapper around the Shopify Admin API."""

    _token_cache: dict[str, Any] | None = None
    _token_lock = asyncio.Lock()

    def __init__(
        self,
        store: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        api_version: str | None = None,
    ) -> None:
        self.store = (store or settings.shopify_store or "").removeprefix("https://").removesuffix("/")
        self.client_id = client_id or settings.shopify_client_id
        self.client_secret = client_secret or settings.shopify_client_secret
        self.api_version = api_version or settings.shopify_api_version

    def _validate_configuration(self) -> None:
        if not all((self.store, self.client_id, self.client_secret, self.api_version)):
            raise ShopifyConfigurationError(
                "SHOPIFY_STORE, SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET, and SHOPIFY_API_VERSION must be configured."
            )

    async def _get_access_token(self) -> str:
        self._validate_configuration()

        cached = self._token_cache
        now = time.time()
        if cached and cached["expires_at"] > now:
            return cached["access_token"]

        async with self._token_lock:
            cached = self._token_cache
            now = time.time()
            if cached and cached["expires_at"] > now:
                return cached["access_token"]

            url = f"https://{self.store}/admin/oauth/access_token"
            data = {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(url, data=data)
                response.raise_for_status()

            payload = response.json()
            access_token = payload.get("access_token")
            if not access_token:
                raise ShopifyConfigurationError("Shopify did not return an access token.")

            expires_in = int(payload.get("expires_in") or 0)
            cache_ttl = max(expires_in - 60, 60)
            self._token_cache = {
                "access_token": access_token,
                "expires_at": time.time() + cache_ttl,
            }
            return access_token

    async def get_latest_orders(self, limit: int | None = None) -> list[ShopifyOrder]:
        """Fetch and normalize recent Shopify orders with cursor pagination. This method never writes to Shopify."""
        access_token = await self._get_access_token()
        fields = "id,name,status,order_number,created_at,customer,email,phone,shipping_address,line_items,shipping_lines,total_price,financial_status,fulfillment_status,cancelled_at,tags"
        url = f"https://{self.store}/admin/api/{self.api_version}/orders.json"
        headers = {"X-Shopify-Access-Token": access_token}
        orders: list[ShopifyOrder] = []
        next_url: str | None = url
        params: dict[str, str] | None = {"status": "any", "limit": "250", "order": "created_at desc", "fields": fields}
        seen_urls: set[str] = set()
        async with httpx.AsyncClient(timeout=20.0) as client:
            while next_url:
                if next_url in seen_urls:
                    raise ShopifyConfigurationError("Shopify pagination repeated a page URL.")
                seen_urls.add(next_url)
                response = await client.get(next_url, params=params, headers=headers)
                response.raise_for_status()
                payload = response.json().get("orders", [])
                orders.extend(self._to_order(order) for order in payload)
                if limit is not None and len(orders) >= limit:
                    return orders[:limit]
                next_url = self._next_page_url(response.headers.get("link"))
                params = None

        return orders

    @staticmethod
    def _next_page_url(link_header: str | None) -> str | None:
        if not link_header:
            return None
        for part in link_header.split(","):
            section = part.strip().split(";")
            if len(section) < 2:
                continue
            target = section[0].strip()
            rel = next((item.strip() for item in section[1:] if item.strip().startswith("rel=")), "")
            if rel != 'rel="next"':
                continue
            if target.startswith("<") and target.endswith(">"):
                return target[1:-1]
        return None

    @staticmethod
    def _to_order(order: dict[str, Any]) -> ShopifyOrder:
        customer = order.get("customer") or {}
        address = order.get("shipping_address") or {}
        full_name = " ".join(part for part in [customer.get("first_name"), customer.get("last_name")] if part) or address.get("name")
        shopify_name = str(order.get("name") or "").lstrip("#") or None
        return ShopifyOrder(
            order_id=str(order["id"]),
            order_number=shopify_name or str(order.get("order_number", order["id"])),
            shopify_name=shopify_name,
            created_date=order["created_at"],
            cancelled_at=order.get("cancelled_at"),
            shopify_status=order.get("status"),
            customer_name=full_name,
            customer_id=str(customer.get("id")) if customer.get("id") is not None else None,
            customer_orders_count=customer.get("orders_count"),
            phone=order.get("phone") or customer.get("phone") or address.get("phone"),
            email=order.get("email") or customer.get("email"),
            shipping_address=ShippingAddress(name=address.get("name"), address=" ".join(filter(None, [address.get("address1"), address.get("address2")])) or None, landmark=None, city=address.get("city"), state=address.get("province"), pincode=address.get("zip")) if address else None,
            products=[OrderProduct(product_name=item.get("title", "Untitled product"), sku=item.get("sku"), quantity=item.get("quantity", 0), weight_grams=item.get("grams"), price=item.get("price", 0)) for item in order.get("line_items", [])],
            total_amount=order.get("total_price", 0),
            shipping_amount=sum((Decimal(str(line.get("price") or 0)) for line in order.get("shipping_lines", [])), start=Decimal("0")) if order.get("shipping_lines") else None,
            payment_status=order.get("financial_status"),
            fulfillment_status=order.get("fulfillment_status"),
            tags=[tag.strip() for tag in order.get("tags", "").split(",") if tag.strip()],
        )
