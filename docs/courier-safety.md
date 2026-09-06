# Courier booking safety

## Invariants

- A Shopify-origin Shiprocket booking must resolve an existing channel order and assign an AWB against its shipment. An unresolved or ambiguous lookup is blocked; it must not call `orders/create/adhoc`.
- A persisted provider identifier, shipment ID, AWB, fulfilment, or uncertain booking outcome blocks another booking attempt.
- The Shiprocket channel order reference must exactly match the OS order reference before the row is persisted.
- Direct Delhivery booking remains separate and is never used as a fallback for Shiprocket.
- Shadowfax remains read-only/manual until its documented channel-order API is implemented.

## Required pre-deploy command

From `backend` run:

```powershell
python scripts/courier_safety_regression.py
```

Run it when changing `backend/app/api/routes/couriers.py`, `backend/app/services/shiprocket.py`, `backend/app/services/delhivery.py`, `backend/app/services/courier_platform/`, Shopify order mapping, shipment persistence, or the frontend booking drawer/client. A deployment also requires the relevant production build and no new lint findings in touched files.

The backend Render build invokes this command, so a backend deployment cannot proceed without this suite. Frontend deployments retain their production build and must run lint with the existing lint baseline; touched files may not introduce new findings.

## Read-only production smoke checks

- Admin/owner aggregate safety state: `/api/v1/couriers/shiprocket/safety-smoke`.
- Admin/owner Shiprocket search inspection: `/api/v1/couriers/shiprocket/debug-search?order_number=<number>`.
- Admin/owner Shadowfax health check: `/api/v1/shadowfax/health-check`.
- Delhivery smoke state is configuration-only; direct booking is never exercised by a smoke test.

The Shiprocket diagnostic is GET-only and reports the sanitized lookup rows and strict resolver comparison. It never creates, assigns, cancels, or persists a provider record.

## Dangerous fallback policy

- `ShiprocketService.create_shipment()` is an explicit low-level adhoc operation only. Normal OS Shopify booking calls `book_order_shipment(..., allow_adhoc_create=False)` and fails closed.
- Manual/external shipment recording requires explicit operator input and exact-provider association validation or explicit operator confirmation; it is not an automatic recovery path.
- Courier quote failures may show other available quotes, but selecting a provider remains explicit. Booking never switches providers automatically.
