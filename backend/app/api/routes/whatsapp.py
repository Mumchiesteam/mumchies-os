"""Meta WhatsApp webhook: verified receive-only skeleton.

No automatic messages are sent and no customer messages are persisted yet.
"""
import hashlib
import hmac

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.core.config import settings

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


def verify_meta_signature(body: bytes, signature: str | None, app_secret: str | None) -> bool:
    if not signature or not app_secret or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.get("/webhook")
def verify_subscription(
    mode: str | None = Query(None, alias="hub.mode"),
    token: str | None = Query(None, alias="hub.verify_token"),
    challenge: str | None = Query(None, alias="hub.challenge"),
) -> Response:
    if not settings.whatsapp_webhook_enabled or not settings.whatsapp_verify_token:
        raise HTTPException(status_code=404, detail="Webhook disabled")
    if mode != "subscribe" or not token or not hmac.compare_digest(token, settings.whatsapp_verify_token):
        raise HTTPException(status_code=403, detail="Verification failed")
    if challenge is None:
        raise HTTPException(status_code=400, detail="Missing challenge")
    return Response(content=challenge, media_type="text/plain")


@router.post("/webhook")
async def receive_webhook(request: Request) -> dict[str, str]:
    if not settings.whatsapp_webhook_enabled or not settings.whatsapp_app_secret:
        raise HTTPException(status_code=404, detail="Webhook disabled")
    body = await request.body()
    if not verify_meta_signature(body, request.headers.get("X-Hub-Signature-256"), settings.whatsapp_app_secret):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")
    # Deliberately no message processing, storage or outgoing API calls yet.
    return {"status": "accepted"}
