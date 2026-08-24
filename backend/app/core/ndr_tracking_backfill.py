"""Read-only historical NDR tracking dry run.

Usage: python -m app.core.ndr_tracking_backfill --limit 500 [--provider delhivery]
This command performs provider GETs only and never persists events or NDR changes.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.ndr import NDRCase
from app.services.courier_platform import courier_registry
from app.services.ndr_tracking import classify_tracking_result, provider_name, valid_tracking_identity


async def dry_run(*, limit: int, provider: str | None = None) -> dict[str, int]:
    with SessionLocal() as db:
        query = select(NDRCase).where(NDRCase.source_lifecycle == "no_longer_reported", NDRCase.current_status != "resolved")
        if provider:
            query = query.where(NDRCase.provider == provider.casefold())
        cases = [case for case in db.scalars(query.order_by(NDRCase.first_ndr_at.asc()).limit(limit)).all() if valid_tracking_identity(case)]
        for case in cases:
            db.expunge(case)
    counts = {"attempted": 0, "provider_success": 0, "delivered": 0, "rto_complete": 0, "rto_in_progress": 0, "in_transit_reattempt": 0, "cancelled": 0, "unknown": 0, "not_found": 0, "provider_error": 0}
    for case in cases:
        counts["attempted"] += 1
        try:
            adapter = courier_registry.get(provider_name(case.provider))
            result = await adapter.track_shipment({"provider": provider_name(case.provider), "awb": str(case.awb).strip(), "order_id": case.order_id, "order_number": case.order_number})
            classification = classify_tracking_result(result)
            counts["provider_success"] += 1
            counts[classification] += 1
        except Exception as error:
            status = getattr(error, "http_status", None) or getattr(error, "status_code", None)
            counts["not_found" if status == 404 else "provider_error"] += 1
        await asyncio.sleep(1)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only historical NDR tracking dry run")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--provider", choices=["delhivery", "shiprocket", "shadowfax"])
    args = parser.parse_args()
    print(json.dumps(asyncio.run(dry_run(limit=max(1, args.limit), provider=args.provider)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
