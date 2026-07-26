import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.courier_platform.base import ProviderError
from app.services.courier_platform.webhooks import process_webhook

router = APIRouter(prefix="/couriers/webhooks", tags=["courier-webhooks"])


@router.post("/{provider}")
async def courier_webhook(provider: str, request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    body = await request.body()
    try:
        payload = json.loads(body)
    except Exception as error:
        raise HTTPException(status_code=400, detail="Webhook payload must be valid JSON.") from error
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be an object.")
    try:
        return process_webhook(db, provider=provider.casefold(), body=body, headers={key.casefold(): value for key, value in request.headers.items()}, payload=payload)
    except ProviderError as error:
        raise HTTPException(status_code=401 if "signature" in str(error).casefold() else 503, detail=str(error)) from error
