from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def api_health_check() -> dict[str, str]:
    """Return API health status."""
    return {"status": "ok"}
