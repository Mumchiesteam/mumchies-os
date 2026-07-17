# Mumchies OS

Mumchies OS is a production-oriented monorepo foundation for a FastAPI backend and React frontend.

## Stack

- Backend: Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL
- Frontend: React, TypeScript, Vite, Tailwind CSS
- Local infrastructure: Docker Compose

## Structure

```text
backend/    FastAPI application and migrations
frontend/   React web application
database/   Local database initialization assets
docs/       Project documentation
scripts/    Developer automation
tests/      Cross-service test workspace
```

## Quick start

1. Copy the environment template: `Copy-Item .env.example .env`
2. Start PostgreSQL: `docker compose up -d db`
3. Start the backend:
   ```powershell
   cd backend
   python -m venv .venv
   .\\.venv\\Scripts\\Activate.ps1
   pip install -r requirements.txt
   uvicorn app.main:app --reload
   ```
4. Start the frontend in another terminal:
   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

The API is available at `http://localhost:8000`, with interactive docs at `/docs`. The frontend is available at `http://localhost:5173`.

## Shopify read-only orders

The Orders dashboard reads the latest 100 orders through the backend only; the browser never receives your Shopify credentials or Shopify access token. The backend first exchanges the Shopify client credentials for a short-lived Admin API token, then makes a single `GET` request to Shopify. There are no write, fulfillment, tag, or update operations.

1. In Shopify, create and install a custom app for the store and grant it the Admin API scopes needed for orders.
2. Copy `.env.example` to `.env`, then set `SHOPIFY_STORE` (for example `my-store.myshopify.com`), `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`, and a supported `SHOPIFY_API_VERSION`.
3. The backend requests `POST /admin/oauth/access_token` with `grant_type=client_credentials`, caches the token until shortly before expiry, and uses it for Admin API requests.
3. Start the backend and frontend as described above. The dashboard requests `GET /api/v1/orders` on load and every 60 seconds.

Without valid Shopify variables, the endpoint responds with a clear configuration error and the dashboard shows a retry state. No Shopify data is modified.

## Database migrations

From `backend/`, run `alembic upgrade head` after PostgreSQL is available. Migration files will be added as domain models are introduced.
