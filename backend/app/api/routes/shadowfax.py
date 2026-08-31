from fastapi import APIRouter, HTTPException, Request

from app.services.shadowfax_diagnostics import shadowfax_health_check

router = APIRouter(prefix="/shadowfax", tags=["shadowfax"])


@router.get("/health-check")
async def shadowfax_read_only_health_check(request: Request) -> dict[str, object]:
    user = getattr(request.state, "auth_user", None)
    if user is None or user.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return await shadowfax_health_check()
