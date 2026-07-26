# Mumchies OS — Architecture

Internal operations platform for Mumchies Foods. It consolidates daily ecommerce
operations — pulling orders from Shopify, verifying addresses, confirming COD orders by
phone, booking couriers through provider-neutral adapters (Shiprocket / Delhivery / Shadowfax),
generating shipping labels, and syncing fulfilment back to Shopify.

The primary user is a **non-technical business operator**. Design priorities, in order:
**reliability, simplicity, operational safety.**

> This document describes how the system is put together as of the current codebase. It is
> a map for humans, not a spec — when in doubt, the code is the source of truth.

---

## 1. High-level shape

```
┌─────────────────────┐      HTTP (JSON)      ┌──────────────────────┐
│  Frontend (React)   │  ───────────────────► │  Backend (FastAPI)   │
│  Vite + TS + Tailwind│  ◄─────────────────── │  Uvicorn             │
│  localhost:5173     │                       │  127.0.0.1:8000      │
└─────────────────────┘                       └──────────┬───────────┘
                                                          │
                    ┌─────────────────────────────────────┼─────────────────────────────┐
                    │                                     │                             │
             ┌──────▼──────┐                    ┌─────────▼─────────┐         ┌─────────▼─────────┐
             │  Shopify    │                    │  Local data store │         │ Courier providers │
             │ Admin API   │                    │  SQLite + JSON    │         │ Shiprocket /      │
             │ (orders,    │                    │  (on-disk files)  │         │ Delhivery /       │
             │ fulfilment) │                    └───────────────────┘         │ Shadowfax Direct  │
             └─────────────┘                                                  └───────────────────┘
```

- **Frontend** is a single-page React app. It holds no data of its own; every screen is
  driven by calls to the backend.
- **Backend** is the brain: it talks to Shopify and the couriers, applies all business
  rules, and persists operational state locally.
- **External services** (Shopify, Shiprocket, Delhivery) are reached over HTTPS using
  credentials held in the backend's environment (`.env`).

---

## 2. Technology stack

### Backend (`backend/`)
- **Python** + **FastAPI** (web framework), served by **Uvicorn**.
- **SQLAlchemy** ORM + **Alembic** migrations.
- **SQLite** for local/current development (`backend/data/mumchies_os.db`). A PostgreSQL
  connection string is the configured default (`database_url`) for when the app moves to a
  server.
- **httpx** for all outbound API calls (Shopify, couriers).
- **pypdf** + **reportlab** for shipping-label PDF generation.
- **openpyxl** for Excel exports.
- **pytest** for tests.

### Frontend (`frontend/`)
- **React** + **TypeScript**, built with **Vite**.
- **Tailwind CSS** for styling.
- Almost all UI lives in a single component file, `src/App.tsx`; all server calls are
  centralised in `src/services/orders.ts`.

---

## 3. Directory map

```
mumchies-os/
├── CLAUDE.md                     # Project/assistant instructions
├── architecture.md              # This document
├── backend/
│   ├── .env                      # Secrets (never committed) — Shopify/Shiprocket/Delhivery creds
│   ├── requirements.txt          # Python dependencies
│   ├── alembic/                  # Database migrations (schema history)
│   ├── data/                     # ── RUNTIME DATA (see §6) ──
│   │   ├── mumchies_os.db         #   SQLite database
│   │   ├── order_operations.json  #   Operational state (call logs, addresses…)
│   │   └── label_batches/         #   Generated label PDFs (gitignored)
│   └── app/
│       ├── main.py               # FastAPI app + CORS setup
│       ├── core/config.py        # Settings loaded from environment
│       ├── api/
│       │   ├── router.py         # Wires all route modules under /api/v1
│       │   └── routes/           # HTTP endpoints (see §5)
│       │       ├── orders.py      #   Order list, operations, address, call logs, export
│       │       ├── couriers.py    #   Eligibility, quotes, booking, tracking, refresh
│       │       ├── labels.py      #   Label print queue / batches / confirm / reprint
│       │       └── health.py      #   Health check
│       ├── services/             # Business logic (see §4)
│       ├── repositories/         # DB read/write helpers for shipments
│       ├── models/               # SQLAlchemy tables
│       └── schemas/              # Pydantic request/response shapes
└── frontend/
    └── src/
        ├── App.tsx               # The entire operations console UI
        ├── services/orders.ts    # All backend API bindings + type definitions
        ├── main.tsx              # React entry point
        └── styles/index.css      # Tailwind styles
```

---

## 4. Backend services (the business logic)

All under `backend/app/services/`. This is where the real work happens; routes are thin
wrappers around these.

| Service | Responsibility |
|---|---|
| `shopify.py` | Reads orders from Shopify's Admin API (REST for the order list, GraphQL for fulfilment context). Normalises raw Shopify orders into the app's `ShopifyOrder` shape, including partial-COD balance calculation and detection of **externally-booked shipments** from Shopify's `fulfillments` data. Has an in-memory cache with a TTL to avoid hammering Shopify. |
| `shopify_fulfillment.py` | Idempotently creates/repairs Shopify fulfilment + tracking after a courier booking. Never rolls back a courier booking if the Shopify write fails — sync errors are recorded, not fatal. |
| `shiprocket.py` | Shiprocket integration: auth/token caching, courier serviceability quotes, order creation + AWB assignment, tracking, address updates. Also owns **booking eligibility evaluation**. |
| `delhivery.py` | Direct Delhivery integration: serviceability, shipment manifestation, waybill fetch, tracking, cancellation, and the official-label proxy. Delhivery labels are rendered natively (see below). |
| `delhivery_label.py` | Renders a compact **A6 (298×420pt) Delhivery shipping label** as a PDF from Delhivery's own packing-slip JSON, enriched with Mumchies order data (price, totals, partial-COD amount). Uses reportlab + Code128 barcodes. *(A layout redesign is currently parked in a git stash.)* |
| `label_printing.py` | Manages idempotent **print batches**: gathering selected labels into one PDF, tracking print status (`not_printed` → `awaiting_confirmation` → `printed`), and preventing duplicate batching. |
| `order_operations.py` | The file-backed store for operational state that Shopify doesn't hold: call logs, corrected/verified addresses, package details, selected courier. Persists to `data/order_operations.json`. |
| `shipment_status.py` | **Single authoritative source** for order status precedence and "does an active shipment already exist?" Shipment-backed states (Cancelled/Delivered/Shipped/Booked/NDR) always outrank locally-derived states (Ready for Booking, Call Pending…). Used by the order list, booking eligibility, and the booking guard alike so the rule can't drift. |

---

## 5. API surface

All endpoints are served under the `/api/v1` prefix. CORS currently allows only
`localhost:5173` and `127.0.0.1:5173` (this must be widened when the app is hosted).

**Orders** (`orders.py`)
- `GET  /orders` — the merged order list (Shopify + local operational state).
- `GET  /orders/{id}/operations` — call logs, addresses, shipment snapshot for one order.
- `PUT  /orders/{id}/address` — save an address correction (and best-effort sync to Shopify/courier).
- `POST /orders/{id}/call-logs` — append a COD call attempt.
- `POST /orders/{id}/address/verify` — mark an address verified.
- `POST /orders/{id}/address/validate` — advisory address checks (+ Shiprocket score placeholder).
- `POST /orders/{id}/shopify-fulfillment/sync` — push fulfilment/tracking to Shopify.
- `GET  /orders/{id}/shipment/label`, `/shipping-label` — official provider label PDF.
- `POST /orders/export` — Excel export (current view or full workbook).

**Couriers** (`couriers.py`)
- `GET  /couriers/shiprocket/health` — Shiprocket connectivity/pickup check.
- `POST /couriers/shiprocket/orders/{id}/package` — save package weight/dimensions.
- `GET  /couriers/shiprocket/orders/{id}/eligibility` — is this order bookable?
- `POST /couriers/shiprocket/orders/{id}/couriers/check` — fetch courier quotes (Shiprocket + Delhivery + Shadowfax estimate).
- `POST /couriers/shiprocket/orders/{id}/couriers/select` — remember the chosen courier.
- `POST /orders/{id}/book` — **provider-neutral booking** entrypoint (delegates to the guarded implementation).
- `POST /couriers/shiprocket/orders/{id}/refresh` — refresh shipment status.
- `GET  /couriers/shiprocket/orders/{id}/tracking` — live tracking.
- `PUT  /couriers/shiprocket/orders/{id}/address` — update a booked courier address.

**Labels** (`labels.py`)
- `GET  /labels/queue` — labels to print / awaiting confirmation / printed today.
- `POST /labels/batches` + `GET /labels/batches/active` + `GET /labels/batches/{id}/pdf` — create/list/download a print batch.
- `POST /labels/batches/{id}/confirm` — confirm which labels actually printed.
- `POST /labels/orders/{id}/activate` + `/reprint` — add legacy shipment to queue / reprint.

**Health** (`health.py`)
- `GET /health` — liveness check.

---

## 6. Data & persistence

There are **three kinds of stored state**, all currently on this machine's disk:

1. **SQLite database** — `backend/data/mumchies_os.db`
   Tables (see `app/models/shiprocket.py`):
   - `shiprocket_shipments` — one row per booked shipment (provider, AWB, courier, booking
     status, tracking, package dims, Shopify fulfilment sync fields, label-print state,
     address-confidence fields).
   - `label_print_batches` — a print batch (provider, status, cached PDF path).
   - `label_print_batch_items` — the individual labels within a batch.
   Schema is managed by **Alembic** migrations in `backend/alembic/versions/`.

2. **JSON operational store** — `backend/data/order_operations.json`
   Per-order operational metadata that Shopify doesn't own: call logs, corrected &
   verified addresses, package details, selected courier, sync results. This file is the
   live record of operator activity and must be treated as **production data** — never
   deleted or reset lightly. (It is tracked in git for now, which is a known caveat given
   it can contain customer PII.)

3. **Generated label PDFs** — `backend/data/label_batches/*.pdf`
   Cached print-batch PDFs, referenced by `label_print_batches.pdf_cache_path`.
   This folder is gitignored.

**Source of truth**: Shopify is authoritative for order/customer/fulfilment facts. The
local stores hold operational overlay state (what the ops team has *done* with each order).
The order list endpoint merges the two on every request.

---

## 7. Configuration & secrets

Settings load from environment (`.env` in `backend/`), via `app/core/config.py`:

- `database_url` — DB connection (SQLite locally; PostgreSQL default for a server).
- `shopify_store`, `shopify_client_id`, `shopify_client_secret`, `shopify_api_version` —
  Shopify Admin API app credentials (a client-credentials flow, not a static token).
- `shiprocket_email`, `shiprocket_password`, `shiprocket_pickup` — Shiprocket account.
- `delhivery_token`, `delhivery_pickup` — direct Delhivery account.
- `shadowfax_token` / `shadowfax_base_url` — backend-only Shadowfax Direct configuration.
- `shopify_notify_customer_on_fulfillment` — whether Shopify emails the customer on fulfilment.

Secrets live only in `.env` (gitignored) and, in a hosted setup, as host environment
variables. They are never committed and never returned by the API.

---

## 8. Core workflow — the order lifecycle

This is the sequence the ops team follows and the reason the system exists:

```
Shopify order imported
        │
        ▼
Address review / correction ──► (verify address, or confirm COD by phone via call logs)
        │
        ▼
Package details entered (weight + dimensions)
        │
        ▼
Check Couriers ──► quotes from Shiprocket + Delhivery + Shadowfax estimate (cheapest first)
        │
        ▼
Select courier ──► Book Shipment through the selected provider adapter
        │
        ▼
Label print batch generated (A6 for Delhivery) ──► confirm printed
        │
        ▼
Shopify fulfilment + tracking synced back
```

**Guardrails baked into this flow:**
- An order with **any existing shipment or fulfilment** (local shipment, AWB, or a Shopify
  fulfilment booked outside the app) is **not bookable** — booking controls disable and the
  backend booking endpoint rejects duplicates. Call logs and address edits can update
  operational metadata but can never downgrade a shipment-backed status back to bookable.
  This rule is centralised in `shipment_status.py`.
- Externally-booked orders show a read-only **tracking section** (provider, AWB, track link)
  instead of booking controls.
- Booking is idempotent: an already-booked order short-circuits instead of re-booking.

---

## 9. External integrations at a glance

| Provider | What it does | Automation |
|---|---|---|
| **Shopify** | Source of orders, customers, fulfilment. Read orders; write fulfilment/tracking/address. | Automated (read + write) |
| **Shiprocket** | Courier aggregator: serviceability quotes, booking, AWB, tracking, label. | Automated booking |
| **Delhivery** | Direct courier account: quotes, manifestation, native A6 label, tracking. | Automated booking |
| **Shadowfax** | Provider-neutral Direct adapter, persistence, reconciliation, tracking, cancellation, labels and NDR contracts. | Transport fails closed until the official Forward Integration endpoint contract is wired. |

---

## 10. Running it locally

Two long-running processes, in two terminals, from the project root:

```
# Backend  → http://127.0.0.1:8000
cd backend
.venv\Scripts\uvicorn app.main:app --reload --port 8000

# Frontend → http://localhost:5173
cd frontend
npm run dev
```

The frontend currently points at the backend via a hard-coded `apiBase` in
`frontend/src/services/orders.ts` (`http://127.0.0.1:8000`). Both processes must be running
for the app to work; they do not restart automatically after a machine reboot.

Tests: `cd backend && .venv\Scripts\pytest`. Frontend build: `cd frontend && npm run build`.

---

## 11. Known constraints & things to know before hosting

- **No authentication.** There is no login or per-user access control; anyone who can reach
  the app has full access, including customer PII and booking actions. This must be gated
  (private access or an added login) before the app is exposed online.
- **Single-machine data.** All operational data is files on one disk with no backups yet —
  a hosting move should add persistent storage + automatic backups.
- **Hard-coded API base URL** in the frontend and a **localhost-only CORS allowlist** in the
  backend both need updating for any non-local deployment.
- **Shopify load.** The order list is re-fetched aggressively (auto-refresh + force-refresh),
  which can trip Shopify's rate limit under load; worth tuning before multiple users share it.
- **SQLite → PostgreSQL.** SQLite is fine for one instance; a multi-user hosted setup should
  move to the already-configured PostgreSQL.
