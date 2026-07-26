from fastapi import APIRouter

from app.services.courier_platform import courier_registry

router = APIRouter(prefix="/couriers", tags=["courier-platform"])


@router.get("/providers")
async def courier_providers() -> dict[str, dict[str, object]]:
    """Public-to-operators capability metadata; never returns provider credentials."""
    return courier_registry.capabilities()
