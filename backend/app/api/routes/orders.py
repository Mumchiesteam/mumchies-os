import httpx
from fastapi import APIRouter, HTTPException

from app.schemas.orders import ShopifyOrder
from app.services.shopify import ShopifyConfigurationError, ShopifyService

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=list[ShopifyOrder])
async def list_orders() -> list[ShopifyOrder]:
    """Return the latest Shopify orders through a read-only integration."""
    try:
        return await ShopifyService().get_latest_orders(limit=100)
    except ShopifyConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except httpx.HTTPStatusError as error:
        raise HTTPException(status_code=502, detail="Shopify could not provide orders. Check the store, token, and API version.") from error
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="Unable to reach Shopify.") from error
