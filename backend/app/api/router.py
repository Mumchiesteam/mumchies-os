from fastapi import APIRouter

from app.api.routes.couriers import router as couriers_router
from app.api.routes.health import router as health_router
from app.api.routes.orders import router as orders_router

api_router = APIRouter()
api_router.include_router(couriers_router)
api_router.include_router(health_router)
api_router.include_router(orders_router)
