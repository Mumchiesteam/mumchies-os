"""Internal-only support test endpoint. Global session auth and CSRF apply."""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.support_ai import answer_support_message_with_ai

router = APIRouter(prefix="/support", tags=["support"])


class SupportRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@router.post("/test-reply")
async def test_reply(payload: SupportRequest) -> dict[str, object]:
    return await answer_support_message_with_ai(payload.message)
