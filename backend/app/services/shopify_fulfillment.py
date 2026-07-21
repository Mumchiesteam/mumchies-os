"""Idempotent Shopify fulfillment synchronization for booked courier shipments."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.shiprocket import get_shipment, snapshot, upsert_shipment
from app.services.shopify import ShopifyConfigurationError, ShopifyService, ShopifySyncError


READ_SCOPE = "read_merchant_managed_fulfillment_orders"
WRITE_SCOPE = "write_merchant_managed_fulfillment_orders"


class ShopifyFulfillmentSyncError(RuntimeError):
    """Safe operational error; courier booking remains persisted."""


class ShopifyFulfillmentSynchronizer:
    def __init__(self, shopify: ShopifyService | None = None) -> None:
        self.shopify = shopify or ShopifyService()

    async def _context(self, order_gid: str) -> dict[str, Any]:
        return await self.shopify.get_order_fulfillment_context(order_gid)

    @staticmethod
    def _tracking_values(fulfillment: dict[str, Any]) -> list[dict[str, Any]]:
        values = fulfillment.get("trackingInfo") or []
        return [value for value in values if isinstance(value, dict)]

    @staticmethod
    def _open_groups(context: dict[str, Any]) -> list[list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        nodes = ((context.get("fulfillmentOrders") or {}).get("nodes") or [])
        for fulfillment_order in nodes:
            if not isinstance(fulfillment_order, dict):
                continue
            actions = {
                str(action.get("action") if isinstance(action, dict) else action).upper()
                for action in (fulfillment_order.get("supportedActions") or [])
            }
            if "CREATE_FULFILLMENT" not in actions:
                continue
            items = []
            for item in ((fulfillment_order.get("lineItems") or {}).get("nodes") or []):
                remaining = int(item.get("remainingQuantity") or 0)
                if item.get("id") and remaining > 0:
                    items.append({"id": item["id"], "quantity": remaining})
            if not items:
                continue
            location = (((fulfillment_order.get("assignedLocation") or {}).get("location") or {}).get("id") or "unassigned")
            groups[str(location)].append({
                "fulfillmentOrderId": fulfillment_order["id"],
                "fulfillmentOrderLineItems": items,
            })
        return list(groups.values())

    async def _create(
        self,
        lines: list[dict[str, Any]],
        *,
        awb: str,
        courier: str,
        tracking_url: str | None,
        notify_customer: bool,
    ) -> dict[str, Any]:
        return await self.shopify.create_fulfillment({
            "lineItemsByFulfillmentOrder": lines,
            "trackingInfo": {"company": courier, "number": awb, "url": tracking_url},
            "notifyCustomer": notify_customer,
        })

    async def _update_tracking(
        self,
        fulfillment_id: str,
        *,
        awb: str,
        courier: str,
        tracking_url: str | None,
        notify_customer: bool,
    ) -> dict[str, Any]:
        return await self.shopify.update_fulfillment_tracking(
            fulfillment_id,
            {"company": courier, "number": awb, "url": tracking_url},
            notify_customer=notify_customer,
        )

    async def sync(self, db: Session, order_id: str, order_gid: str | None = None) -> dict[str, Any]:
        shipment = get_shipment(db, order_id)
        if shipment is None or not shipment.awb:
            raise ShopifyFulfillmentSyncError("A booked courier shipment with an AWB is required before Shopify sync.")
        if shipment.booking_status not in {"booked", "complete", "completed", "awb_assigned"}:
            raise ShopifyFulfillmentSyncError("The courier shipment is not in a bookable-complete state.")

        awb = str(shipment.awb)
        courier = (
            "Delhivery" if shipment.provider == "delhivery"
            else str(shipment.courier_name or shipment.selected_courier_name or shipment.provider or "Courier")
        )
        tracking_url = shipment.tracking_url
        upsert_shipment(db, order_id,
            shopify_fulfillment_sync_status="pending",
            shopify_fulfillment_sync_error=None,
            shopify_tracking_number=awb,
            shopify_tracking_url=tracking_url,
        )
        try:
            scopes = await self.shopify.granted_access_scopes()
            missing = [scope for scope in (READ_SCOPE, WRITE_SCOPE) if scope not in scopes]
            if missing:
                raise ShopifyFulfillmentSyncError("Shopify fulfillment sync is not authorized. Missing app scopes: " + ", ".join(missing))

            gid = order_gid or f"gid://shopify/Order/{order_id}"
            context = await self._context(gid)
            if context.get("cancelledAt"):
                updated = upsert_shipment(db, order_id,
                    shopify_fulfillment_sync_status="not_applicable",
                    shopify_fulfillment_sync_error="The Shopify order is cancelled.",
                )
                return snapshot(updated)

            fulfillments = [value for value in (context.get("fulfillments") or []) if isinstance(value, dict)]
            for fulfillment in fulfillments:
                if any(str(value.get("number") or "") == awb for value in self._tracking_values(fulfillment)):
                    updated = upsert_shipment(db, order_id,
                        shopify_fulfillment_id=str(fulfillment.get("id")),
                        shopify_fulfillment_status=str(fulfillment.get("status") or context.get("displayFulfillmentStatus") or "SUCCESS"),
                        shopify_fulfillment_sync_status="synced",
                        shopify_fulfillment_synced_at=datetime.now(timezone.utc),
                        shopify_fulfillment_sync_error=None,
                        shopify_tracking_number=awb,
                        shopify_tracking_url=tracking_url,
                    )
                    return snapshot(updated)

            groups = self._open_groups(context)
            notify = bool(settings.shopify_notify_customer_on_fulfillment and not shipment.shopify_customer_notified)
            fulfillment_ids: list[str] = []
            fulfillment_status = str(context.get("displayFulfillmentStatus") or "")
            if groups:
                for group in groups:
                    fulfillment = await self._create(group, awb=awb, courier=courier, tracking_url=tracking_url, notify_customer=notify)
                    fulfillment_ids.append(str(fulfillment["id"]))
                    fulfillment_status = str(fulfillment.get("status") or fulfillment_status)
                    if notify:
                        upsert_shipment(db, order_id, shopify_customer_notified=True)
                        notify = False
            elif len(fulfillments) == 1:
                fulfillment_id = str(fulfillments[0].get("id") or "")
                if not fulfillment_id:
                    raise ShopifyFulfillmentSyncError("The existing Shopify fulfillment has no identifier.")
                await self._update_tracking(
                    fulfillment_id, awb=awb, courier=courier, tracking_url=tracking_url,
                    notify_customer=notify,
                )
                fulfillment_ids.append(fulfillment_id)
                fulfillment_status = str(fulfillments[0].get("status") or fulfillment_status)
                if notify:
                    upsert_shipment(db, order_id, shopify_customer_notified=True)
            else:
                status = str(context.get("displayFulfillmentStatus") or "").replace("_", " ").title()
                message = "No open, merchant-managed Shopify fulfillment order supports fulfillment creation."
                if status:
                    message += f" Current order status: {status}."
                updated = upsert_shipment(db, order_id,
                    shopify_fulfillment_sync_status="not_applicable",
                    shopify_fulfillment_status=str(context.get("displayFulfillmentStatus") or ""),
                    shopify_fulfillment_sync_error=message,
                )
                return snapshot(updated)

            updated = upsert_shipment(db, order_id,
                shopify_fulfillment_id=",".join(fulfillment_ids),
                shopify_fulfillment_status=fulfillment_status or "SUCCESS",
                shopify_fulfillment_sync_status="synced",
                shopify_fulfillment_synced_at=datetime.now(timezone.utc),
                shopify_fulfillment_sync_error=None,
                shopify_tracking_number=awb,
                shopify_tracking_url=tracking_url,
            )
            return snapshot(updated)
        except (ShopifyFulfillmentSyncError, ShopifySyncError, ShopifyConfigurationError, httpx.HTTPError) as error:
            upsert_shipment(db, order_id,
                shopify_fulfillment_sync_status="failed",
                shopify_fulfillment_sync_error=str(error),
            )
            if isinstance(error, ShopifyFulfillmentSyncError):
                raise
            raise ShopifyFulfillmentSyncError(str(error)) from error
