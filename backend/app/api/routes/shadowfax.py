from fastapi import APIRouter, HTTPException, Request
from app.services.shadowfax_diagnostics import shadowfax_health_check

router = APIRouter(prefix="/shadowfax", tags=["shadowfax"])


@router.get("/health-check")
async def shadowfax_read_only_health_check(request: Request) -> dict[str, object]:
    user = getattr(request.state, "auth_user", None)
    if user is None or user.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return await shadowfax_health_check()


def _require_shadowfax_admin(request: Request) -> None:
    user = getattr(request.state, "auth_user", None)
    if user is None or user.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Admin access required.")


@router.post("/test-create-order/{order_id}")
async def shadowfax_create_only_diagnostic(
    order_id: str, request: Request,
) -> dict[str, object]:
    """Retired legacy endpoint; it can never call the Unified API."""
    _require_shadowfax_admin(request)
    raise HTTPException(
        status_code=410,
        detail="The legacy Shadowfax create diagnostic is retired. Direct booking remains feature-disabled pending end-to-end validation.",
    )
