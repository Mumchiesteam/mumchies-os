from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
import httpx
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.shiprocket import get_shipment, upsert_shipment
from app.services.shiprocket import ShiprocketAPIError, ShiprocketConfigurationError, ShiprocketService

router = APIRouter(prefix="/couriers/shiprocket", tags=["couriers"])


@router.get("/health")
async def shiprocket_health() -> dict[str, object]:
    try:
        result = await ShiprocketService().health()
    except ShiprocketConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ShiprocketAPIError as error:
        return {
            "provider": "shiprocket",
            "configured": True,
            "authenticated": False,
            "pickup_exists": False,
            "pickup_location": None,
            "message": "Shiprocket authentication failed.",
            "error": str(error),
        }
    except httpx.HTTPError:
        return {
            "provider": "shiprocket",
            "configured": True,
            "authenticated": False,
            "pickup_exists": False,
            "pickup_location": None,
            "message": "Unable to reach Shiprocket.",
        }

    return {
        "provider": "shiprocket",
        "configured": result.configured,
        "authenticated": result.authenticated,
        "pickup_exists": result.pickup_exists,
        "pickup_location": result.pickup_location,
        "message": result.message,
    }


@router.get("/serviceability")
async def shiprocket_serviceability(pickup_postcode: str, delivery_postcode: str, weight: float = 1.0, cod: bool = False) -> dict[str, object]:
    try:
        quotes = await ShiprocketService().serviceability(pickup_postcode, delivery_postcode, weight, cod)
    except ShiprocketConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ShiprocketAPIError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"provider": "shiprocket", "couriers": [quote.__dict__ for quote in quotes]}


@router.post("/shipments")
async def shiprocket_book_shipment(payload: dict[str, object], db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        service = ShiprocketService()
        result = await service.create_shipment(db, str(payload["order_id"]), payload, payload.get("courier_id"))
    except ShiprocketConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ShiprocketAPIError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return result


@router.get("/orders/{order_id}/tracking")
async def shiprocket_tracking(order_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        shipment = get_shipment(db, order_id)
        if shipment is None or not shipment.awb:
            raise HTTPException(status_code=404, detail="No Shiprocket shipment exists for this order.")
        return await ShiprocketService().sync_tracking(db, order_id, shipment.awb)
    except ShiprocketConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ShiprocketAPIError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.put("/orders/{order_id}/address")
async def shiprocket_update_address(order_id: str, payload: dict[str, object], db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        shipment = get_shipment(db, order_id)
        if shipment is None or not shipment.awb:
            raise HTTPException(status_code=404, detail="No Shiprocket shipment exists for this order.")
        service = ShiprocketService()
        result = await service.update_address(shipment.awb, payload)
        upsert_shipment(db, order_id, address_sync_status="updated", address_sync_error=None)
        return {"provider": "shiprocket", "updated": True, "response": result}
    except ShiprocketConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ShiprocketAPIError as error:
        upsert_shipment(db, order_id, address_sync_status="failed", address_sync_error=str(error))
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.get("/orders/{order_id}/shipping-label")
async def shiprocket_shipping_label(order_id: str, db: Session = Depends(get_db)):
    try:
        shipment = get_shipment(db, order_id)
        if shipment is None or not shipment.awb:
            raise HTTPException(status_code=404, detail="No Shiprocket shipment exists for this order.")
        response = await ShiprocketService().fetch_label(shipment.awb)
        content_type = response.headers.get("content-type", "application/pdf")
        return StreamingResponse(iter([response.content]), media_type=content_type)
    except ShiprocketConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ShiprocketAPIError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
