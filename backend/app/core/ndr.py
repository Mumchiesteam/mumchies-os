import asyncio
import sys

from app.db.session import SessionLocal
from app.services.ndr import NDRSyncAlreadyRunning, sync_ndr


async def _run() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "sync":
        print("Usage: python -m app.core.ndr sync", file=sys.stderr); return 2
    with SessionLocal() as db:
        try: run = await sync_ndr(db, trigger="scheduler")
        except NDRSyncAlreadyRunning as error: print(str(error), file=sys.stderr); return 3
        except Exception as error: print(f"NDR sync failed: {error}", file=sys.stderr); return 1
        print(f"NDR sync completed: seen={run.cases_seen} created={run.cases_created} updated={run.cases_updated}")
        return 0


if __name__ == "__main__": raise SystemExit(asyncio.run(_run()))
