"""Shopify Admin API access used by Mumchies OS."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.orders import ExternalTracking, OrderProduct, ShippingAddress, ShopifyOrder

# Safe, confident tracking-URL templates for a small set of known providers - reuses the exact
# pattern already used elsewhere in this codebase (see DelhiveryService/normalize_tracking).
# Deliberately NOT populated for providers we aren't sure of the public tracking URL for; those
# just show the tracking number without a link rather than risk an invented/incorrect URL.
_KNOWN_TRACKING_URL_TEMPLATES = {
    "delhivery": "https://www.delhivery.com/track/package/{awb}",
}


class ShopifyConfigurationError(RuntimeError):
    """Raised when Shopify credentials have not been configured."""


class ShopifySyncError(RuntimeError):
    """Safe error raised when a Shopify address write cannot be completed."""

    def __init__(self, message: str, *, user_errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.user_errors = user_errors or []


class ShopifyService:
    """Small reusable, GET-only wrapper around the Shopify Admin API."""

    _token_cache: dict[str, Any] | None = None
    _token_lock = asyncio.Lock()
    _orders_cache: dict[tuple[str, str], tuple[float, list[ShopifyOrder]]] = {}
    _orders_lock = asyncio.Lock()
    _orders_cache_ttl_seconds = 300

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

    async def _admin_headers(self) -> dict[str, str]:
        return {
            "X-Shopify-Access-Token": await self._get_access_token(),
            "Content-Type": "application/json",
        }

    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a current-version Admin GraphQL operation with safe errors."""
        url = f"https://{self.store}/admin/api/{self.api_version}/graphql.json"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                url,
                json={"query": query, "variables": variables or {}},
                headers=await self._admin_headers(),
            )
        if response.status_code >= 400:
            raise ShopifySyncError(f"Shopify Admin GraphQL request failed ({response.status_code}).")
        body = response.json()
        errors = body.get("errors") or []
        if errors:
            message = str((errors[0] or {}).get("message") or "Shopify rejected the GraphQL operation.")
            raise ShopifySyncError(message, user_errors=errors)
        return body.get("data") or {}

    async def granted_access_scopes(self) -> set[str]:
        data = await self.graphql(
            "query CurrentAppScopes { currentAppInstallation { accessScopes { handle } } }"
        )
        scopes = ((data.get("currentAppInstallation") or {}).get("accessScopes") or [])
        return {str(scope.get("handle")) for scope in scopes if scope.get("handle")}

    async def get_order_fulfillment_context(self, order_gid: str) -> dict[str, Any]:
        """Return open fulfillment orders plus existing fulfillment tracking."""
        query = """query OrderFulfillmentContext($id: ID!) {
          order(id: $id) {
            id name cancelledAt displayFulfillmentStatus
            fulfillmentOrders(first: 100) {
              nodes {
                id status
                assignedLocation { location { id name } }
                supportedActions { action }
                lineItems(first: 100) { nodes { id remainingQuantity totalQuantity } }
              }
            }
            fulfillments(first: 100) {
              id status trackingInfo(first: 10) { company number url }
              fulfillmentOrders(first: 100) { nodes { id } }
            }
          }
        }"""
        data = await self.graphql(query, {"id": order_gid})
        order = data.get("order")
        if not isinstance(order, dict):
            raise ShopifySyncError("The Shopify order could not be found.")
        return order

    async def create_fulfillment(self, fulfillment_input: dict[str, Any]) -> dict[str, Any]:
        mutation = """mutation FulfillmentCreate($fulfillment: FulfillmentInput!) {
          fulfillmentCreate(fulfillment: $fulfillment) {
            fulfillment { id status trackingInfo(first: 10) { company number url } }
            userErrors { field message }
          }
        }"""
        data = await self.graphql(mutation, {"fulfillment": fulfillment_input})
        payload = data.get("fulfillmentCreate") or {}
        errors = payload.get("userErrors") or []
        if errors:
            raise ShopifySyncError(
                str(errors[0].get("message") or "Shopify rejected fulfillment creation."),
                user_errors=errors,
            )
        fulfillment = payload.get("fulfillment")
        if not isinstance(fulfillment, dict) or not fulfillment.get("id"):
            raise ShopifySyncError("Shopify did not return a fulfillment identifier.")
        return fulfillment

    async def update_fulfillment_tracking(
        self,
        fulfillment_id: str,
        tracking_input: dict[str, Any],
        *,
        notify_customer: bool,
    ) -> dict[str, Any]:
        mutation = """mutation FulfillmentTrackingUpdate(
          $id: ID!, $tracking: FulfillmentTrackingInput!, $notify: Boolean!
        ) {
          fulfillmentTrackingInfoUpdate(
            fulfillmentId: $id, trackingInfoInput: $tracking, notifyCustomer: $notify
          ) {
            fulfillment { id status trackingInfo(first: 10) { company number url } }
            userErrors { field message }
          }
        }"""
        data = await self.graphql(mutation, {
            "id": fulfillment_id,
            "tracking": tracking_input,
            "notify": notify_customer,
        })
        payload = data.get("fulfillmentTrackingInfoUpdate") or {}
        errors = payload.get("userErrors") or []
        if errors:
            raise ShopifySyncError(
                str(errors[0].get("message") or "Shopify rejected the tracking update."),
                user_errors=errors,
            )
        return payload.get("fulfillment") or {"id": fulfillment_id}

    async def get_order_address_context(self, order_id: str) -> dict[str, Any]:
        url = f"https://{self.store}/admin/api/{self.api_version}/orders/{order_id}.json"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, params={"fields": "id,customer,shipping_address"}, headers=await self._admin_headers())
        if response.status_code >= 400:
            raise ShopifySyncError(f"Shopify order lookup failed ({response.status_code}).")
        order = response.json().get("order") or {}
        customer = order.get("customer") or {}
        return {
            "order_id": str(order.get("id") or order_id),
            "customer_id": str(customer.get("id")) if customer.get("id") is not None else None,
            "shipping_address": order.get("shipping_address") or {},
        }

    @staticmethod
    def _shopify_address(address: dict[str, Any]) -> dict[str, Any]:
        name = str(address.get("customer_name") or address.get("name") or "").strip()
        names = name.split(maxsplit=1)
        return {
            "first_name": names[0] if names else "",
            "last_name": names[1] if len(names) > 1 else "",
            "address1": address.get("address_line1") or address.get("address") or "",
            "address2": " ".join(filter(None, [address.get("address_line2"), address.get("landmark")])),
            "city": address.get("city") or "",
            "province": address.get("state") or "",
            "country": address.get("country") or "India",
            "zip": address.get("pincode") or address.get("zip") or "",
            "phone": address.get("phone") or "",
        }

    @staticmethod
    def _normalized_address(address: dict[str, Any]) -> tuple[str, ...]:
        def text(value: Any) -> str:
            return " ".join(str(value or "").casefold().split())

        def phone(value: Any) -> str:
            digits = "".join(character for character in str(value or "") if character.isdigit())
            return digits[-10:]

        return (
            text(address.get("address1") or address.get("address_line1") or address.get("address")),
            text(address.get("address2") or address.get("address_line2")),
            text(address.get("city")),
            text(address.get("province") or address.get("state")),
            text(address.get("zip") or address.get("pincode")),
            phone(address.get("phone")),
        )

    @classmethod
    def match_customer_address(cls, original: dict[str, Any], saved: list[dict[str, Any]]) -> dict[str, Any] | None:
        identifiers = {
            str(value) for value in (
                original.get("id"), original.get("address_id"), original.get("customer_address_id")
            ) if value is not None
        }
        if identifiers:
            for address in saved:
                if str(address.get("id")) in identifiers:
                    return address
        target = cls._normalized_address(original)
        if not any(target):
            return None
        return next((address for address in saved if cls._normalized_address(address) == target), None)

    async def update_order_shipping_address(self, order_id: str, corrected: dict[str, Any]) -> None:
        query = """mutation OrderAddressUpdate($input: OrderInput!) {
          orderUpdate(input: $input) { order { id } userErrors { field message } }
        }"""
        payload = {
            "query": query,
            "variables": {
                "input": {
                    "id": f"gid://shopify/Order/{order_id}",
                    "shippingAddress": self._shopify_address(corrected),
                }
            },
        }
        url = f"https://{self.store}/admin/api/{self.api_version}/graphql.json"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, json=payload, headers=await self._admin_headers())
        if response.status_code >= 400:
            raise ShopifySyncError(f"Shopify order address update failed ({response.status_code}).")
        body = response.json()
        errors = body.get("errors") or ((body.get("data") or {}).get("orderUpdate") or {}).get("userErrors") or []
        if errors:
            message = errors[0].get("message") if isinstance(errors[0], dict) else str(errors[0])
            raise ShopifySyncError(f"Shopify rejected the order address update: {message}")

    async def get_customer_addresses(self, customer_id: str) -> list[dict[str, Any]]:
        url = f"https://{self.store}/admin/api/{self.api_version}/customers/{customer_id}/addresses.json"
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, params={"limit": "250"}, headers=await self._admin_headers())
        if response.status_code >= 400:
            raise ShopifySyncError(f"Shopify customer address lookup failed ({response.status_code}).")
        return [value for value in response.json().get("addresses", []) if isinstance(value, dict)]

    async def update_customer_address(
        self, customer_id: str, original: dict[str, Any], corrected: dict[str, Any], *, set_as_default: bool = False
    ) -> dict[str, Any]:
        addresses = await self.get_customer_addresses(customer_id)
        matched = self.match_customer_address(original, addresses)
        body = {"address": self._shopify_address(corrected)}
        async with httpx.AsyncClient(timeout=20.0) as client:
            if matched and matched.get("id") is not None:
                address_id = str(matched["id"])
                url = f"https://{self.store}/admin/api/{self.api_version}/customers/{customer_id}/addresses/{address_id}.json"
                response = await client.put(url, json=body, headers=await self._admin_headers())
                created = False
            else:
                url = f"https://{self.store}/admin/api/{self.api_version}/customers/{customer_id}/addresses.json"
                response = await client.post(url, json=body, headers=await self._admin_headers())
                created = True
        if response.status_code >= 400:
            raise ShopifySyncError(f"Shopify customer address update failed ({response.status_code}).")
        result = response.json().get("customer_address") or response.json().get("address") or {}
        address_id = result.get("id") or (matched or {}).get("id")
        if created and set_as_default and address_id is not None:
            default_url = f"https://{self.store}/admin/api/{self.api_version}/customers/{customer_id}/addresses/{address_id}/default.json"
            async with httpx.AsyncClient(timeout=20.0) as client:
                default_response = await client.put(default_url, json={}, headers=await self._admin_headers())
            if default_response.status_code >= 400:
                raise ShopifySyncError(f"Shopify created the customer address but could not make it default ({default_response.status_code}).")
        return {"created": created, "address_id": str(address_id) if address_id is not None else None, "preserved_default": bool((matched or {}).get("default"))}

    async def get_latest_orders(self, limit: int | None = None, *, force_refresh: bool = False) -> list[ShopifyOrder]:
        """Fetch and normalize recent Shopify orders with cursor pagination. This method never writes to Shopify."""
        cache_key = (self.store, self.api_version or "")
        if limit is None and not force_refresh:
            cached = self._orders_cache.get(cache_key)
            if cached and cached[0] > time.monotonic():
                return list(cached[1])

        async with self._orders_lock:
            if limit is None and not force_refresh:
                cached = self._orders_cache.get(cache_key)
                if cached and cached[0] > time.monotonic():
                    return list(cached[1])

            orders = await self._fetch_orders(limit)
            if limit is None:
                self._orders_cache[cache_key] = (
                    time.monotonic() + self._orders_cache_ttl_seconds,
                    list(orders),
                )
            return orders

    async def _fetch_orders(self, limit: int | None = None) -> list[ShopifyOrder]:
        access_token = await self._get_access_token()
        fields = "id,name,status,order_number,created_at,customer,email,phone,shipping_address,line_items,shipping_lines,total_price,current_total_price,total_outstanding,financial_status,fulfillment_status,cancelled_at,tags,payment_gateway_names,fulfillments"
        url = f"https://{self.store}/admin/api/{self.api_version}/orders.json"
        headers = {"X-Shopify-Access-Token": access_token}
        orders: list[ShopifyOrder] = []
        next_url: str | None = url
        created_at_min = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
        params: dict[str, str] | None = {
            "status": "any",
            "limit": "250",
            "order": "created_at desc",
            "created_at_min": created_at_min,
            "fields": fields,
        }
        seen_urls: set[str] = set()
        async with httpx.AsyncClient(timeout=20.0) as client:
            while next_url:
                if next_url in seen_urls:
                    raise ShopifyConfigurationError("Shopify pagination repeated a page URL.")
                seen_urls.add(next_url)
                response = await client.get(next_url, params=params, headers=headers)
                response.raise_for_status()
                payload = response.json().get("orders", [])
                partial_orders = [order for order in payload if str(order.get("financial_status") or "").casefold() == "partially_paid"]
                if partial_orders:
                    summaries = await asyncio.gather(*(self._transaction_summary(client, str(order["id"]), headers) for order in partial_orders))
                    for order, summary in zip(partial_orders, summaries, strict=True):
                        order["_transaction_summary"] = summary
                orders.extend(self._to_order(order) for order in payload)
                if limit is not None and len(orders) >= limit:
                    return orders[:limit]
                next_url = self._next_page_url(response.headers.get("link"))
                if payload and min(datetime.fromisoformat(str(order["created_at"]).replace("Z", "+00:00")) for order in payload) < datetime.fromisoformat(created_at_min):
                    next_url = None
                params = None

        return orders

    async def _transaction_summary(self, client: httpx.AsyncClient, order_id: str, headers: dict[str, str]) -> list[dict[str, Any]]:
        url = f"https://{self.store}/admin/api/{self.api_version}/orders/{order_id}/transactions.json"
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return [
            {
                "id": str(item.get("id") or ""),
                "kind": str(item.get("kind") or ""),
                "status": str(item.get("status") or ""),
                "amount": str(item.get("amount") or "0"),
                "gateway": str(item.get("gateway") or ""),
            }
            for item in response.json().get("transactions", [])
            if isinstance(item, dict)
        ]

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
    def _external_tracking(order: dict[str, Any]) -> ExternalTracking | None:
        """Detect a shipment/fulfilment booked outside Mumchies OS from Shopify's own REST
        fulfillments array. Picks the most relevant fulfillment (prefers one with a tracking
        number; otherwise the most recently updated) rather than assuming array order."""
        fulfillments = [value for value in (order.get("fulfillments") or []) if isinstance(value, dict)]
        if not fulfillments:
            return None
        with_tracking = [value for value in fulfillments if value.get("tracking_number")]
        candidates = with_tracking or fulfillments
        fulfillment = max(candidates, key=lambda value: str(value.get("updated_at") or ""))

        provider = str(fulfillment.get("tracking_company") or "").strip() or None
        awb = str(fulfillment.get("tracking_number") or "").strip() or None
        status = str(fulfillment.get("shipment_status") or fulfillment.get("status") or "").strip() or None
        tracking_url = str(fulfillment.get("tracking_url") or "").strip() or None
        if not tracking_url and provider and awb:
            template = _KNOWN_TRACKING_URL_TEMPLATES.get(provider.strip().casefold())
            if template:
                tracking_url = template.format(awb=awb)
        if not (provider or awb or status):
            return None
        return ExternalTracking(provider=provider, awb=awb, status=status, tracking_url=tracking_url)

    @staticmethod
    def _to_order(order: dict[str, Any]) -> ShopifyOrder:
        customer = order.get("customer") or {}
        address = order.get("shipping_address") or {}
        full_name = " ".join(part for part in [customer.get("first_name"), customer.get("last_name")] if part) or address.get("name")
        shopify_name = str(order.get("name") or "").lstrip("#") or None
        order_total = Decimal(str(order.get("current_total_price") or order.get("total_price") or 0))
        financial_status = str(order.get("financial_status") or "").casefold()
        if order.get("total_outstanding") not in (None, ""):
            outstanding = max(Decimal(str(order.get("total_outstanding") or 0)), Decimal("0"))
        elif financial_status in {"pending", "authorized", "partially_paid"}:
            transactions = order.get("_transaction_summary") or []
            captured = sum((Decimal(str(value.get("amount") or 0)) for value in transactions if value.get("status") == "success" and value.get("kind") in {"sale", "capture"}), Decimal("0"))
            refunded = sum((Decimal(str(value.get("amount") or 0)) for value in transactions if value.get("status") == "success" and value.get("kind") == "refund"), Decimal("0"))
            outstanding = max(order_total - captured + refunded, Decimal("0"))
        else:
            outstanding = Decimal("0")
        paid = max(order_total - outstanding, Decimal("0"))
        payment_type = "partial_cod" if financial_status == "partially_paid" and outstanding > 0 else "cod" if outstanding > 0 else "prepaid"
        return ShopifyOrder(
            order_id=str(order["id"]),
            shopify_graphql_id=f"gid://shopify/Order/{order['id']}",
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
            order_total=order_total,
            paid_amount=paid,
            outstanding_amount=outstanding,
            cod_collectable_amount=outstanding if payment_type in {"cod", "partial_cod"} else Decimal("0"),
            payment_type=payment_type,
            payment_gateway_names=[str(value) for value in order.get("payment_gateway_names", [])],
            transaction_summary=order.get("_transaction_summary") or [],
            shipping_amount=sum((Decimal(str(line.get("price") or 0)) for line in order.get("shipping_lines", [])), start=Decimal("0")) if order.get("shipping_lines") else None,
            payment_status=order.get("financial_status"),
            fulfillment_status=order.get("fulfillment_status"),
            tags=[tag.strip() for tag in order.get("tags", "").split(",") if tag.strip()],
            external_tracking=ShopifyService._external_tracking(order),
        )
