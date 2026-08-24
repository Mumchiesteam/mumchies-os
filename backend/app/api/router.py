from fastapi import APIRouter

from app.api.routes.couriers import booking_router, router as couriers_router
from app.api.routes.health import router as health_router
from app.api.routes.orders import router as orders_router
from app.api.routes.labels import router as labels_router
from app.api.routes.auth import router as auth_router
from app.api.routes.courier_webhooks import router as courier_webhooks_router
from app.api.routes.courier_platform import router as courier_platform_router
from app.api.routes.users import router as users_router
from app.api.routes.ndr import router as ndr_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.courier_issues import router as courier_issues_router
from app.api.routes.reports import router as reports_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(couriers_router)
api_router.include_router(booking_router)
api_router.include_router(health_router)
api_router.include_router(orders_router)
api_router.include_router(labels_router)
api_router.include_router(courier_webhooks_router)
api_router.include_router(courier_platform_router)
api_router.include_router(users_router)
api_router.include_router(ndr_router)
api_router.include_router(dashboard_router)
api_router.include_router(analytics_router)
api_router.include_router(courier_issues_router)
api_router.include_router(reports_router)
