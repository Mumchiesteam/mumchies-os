from fastapi import APIRouter

from app.api.routes.couriers import booking_router, router as couriers_router
from app.api.routes.health import router as health_router
from app.api.routes.orders import router as orders_router
from app.api.routes.labels import router as labels_router

api_router = APIRouter()
api_router.include_router(couriers_router)
api_router.include_router(booking_router)
api_router.include_router(health_router)
api_router.include_router(orders_router)
api_router.include_router(labels_router)
