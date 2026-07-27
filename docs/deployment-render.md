# Render deployment

## Readiness summary

Mumchies OS can be hosted on Render as a FastAPI web service, a static Vite site,
and managed PostgreSQL. The included `render.yaml` provisions those resources,
runs Alembic as a pre-deploy command, checks `/health`, and keeps the two current
file-backed stores on a persistent disk.

This preparation does not deploy the application and does not change order,
courier, Shopify, reporting, P&L, or other business behavior.

## Required environment values

Set these secret or environment-specific values in the Render Blueprint form:

- API `CORS_ORIGINS`: the final frontend URL, for example
  `https://mumchies-os-web.onrender.com`. Use a comma-separated list for more
  than one exact allowed origin. Do not use `*`.
- Web `VITE_API_BASE_URL`: the final API URL, for example
  `https://mumchies-os-api.onrender.com`, without a trailing slash.
- Authentication: `AUTH_ADMIN_USERNAME` and `AUTH_ADMIN_PASSWORD_HASH`.
  Render generates `AUTH_SESSION_SECRET`; never expose it to the frontend.
- Shopify: `SHOPIFY_STORE`, `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`,
  `SHOPIFY_API_VERSION`.
- Courier integrations in use: `SHIPROCKET_EMAIL`, `SHIPROCKET_PASSWORD`,
  `SHIPROCKET_PICKUP`, `DELHIVERY_TOKEN`, `DELHIVERY_PICKUP`, and
  `SHADOWFAX_TOKEN`.

`DATABASE_URL` is supplied directly by the managed database. Provider URLs using
`postgres://` or `postgresql://` are normalized to the installed psycopg driver.

## Exact deployment steps

1. Commit and push the deployment-readiness changes to the production Git branch.
2. In Render, choose **New > Blueprint** and connect the repository.
3. Select `render.yaml` and review the three Singapore-region resources. The
   Blueprint starts with paid Starter API and Basic PostgreSQL plans; increase
   their sizes if load testing requires it. Do not use free instances for
   operational use.
4. Enter every required value listed above when Render asks for `sync: false`
   variables. Generate frontend/API URLs consistently with the service names.
5. Apply the Blueprint. Render creates PostgreSQL first, then runs
   `pip install -r requirements.txt`, `alembic upgrade head`, and starts Uvicorn.
6. Confirm the API deployment is healthy at `https://<api-host>/health`.
7. Confirm the frontend opens and its browser network requests target
   `https://<api-host>/api/v1/...`.
8. Run a controlled operational smoke test with a non-critical order before
   allowing normal production use.

## Users and sessions

Create the initial administrator hash locally. The plaintext password is prompted
interactively and is never written to the repository or command history:

```powershell
cd backend
python -m app.core.auth hash-password
```

Passwords must contain at least 6 characters and have no character-class
requirements. Copy only the resulting
`scrypt$...` value into Render as `AUTH_ADMIN_PASSWORD_HASH`, and set the chosen
username as `AUTH_ADMIN_USERNAME`. For local development, place those two values
in the ignored `.env` file and leave `AUTH_COOKIE_SECURE=false`.

Authentication uses a salted scrypt password hash and an HMAC-SHA256 signed,
expiring HttpOnly session cookie. Render sets `AUTH_COOKIE_SECURE=true`. The
default session lifetime is eight hours (`AUTH_SESSION_MINUTES=480`). Changing
`AUTH_SESSION_SECRET` immediately invalidates all active sessions.
Render uses `SameSite=None` because its frontend and API can have different
hosts; state-changing API calls additionally require the per-session CSRF token.

After the users migration is applied, the existing environment administrator is
created as the database-backed owner on its first successful login. Create other
users interactively from the API service shell with
`python -m app.core.users create-user`; use `python -m app.core.users reset-user`
for an interactive password reset. Passwords are never command-line arguments.

All backend paths, including API documentation, require a valid session except
`/health`, `/api/v1/auth/login`, `/api/v1/auth/logout`, and CORS preflight
requests. The frontend checks the session before rendering the operations UI,
returns to login on expiry or any unauthorised API response, and provides logout
in the existing header.

If a service URL changes, update both `CORS_ORIGINS` and
`VITE_API_BASE_URL`, then redeploy the affected service. Vite embeds its value at
build time.

## PostgreSQL and Alembic

- SQLAlchemy uses `DATABASE_URL` and psycopg with connection pre-ping.
- Alembic reads the same application setting, has one linear revision chain, and
  is executed by Render before each deploy.
- Run locally from `backend` with `alembic upgrade head`.
- Before schema changes, take a Render PostgreSQL backup. Keep migrations
  backward-compatible with the currently running application.

## Remaining production blockers

Operational order state remains in `DATA_DIR/order_operations.json`: call logs,
corrected and verified addresses, package details, selected courier, sync results,
and human-action timestamps. Generated label-batch PDFs also remain under
`DATA_DIR/label_batches`; database rows point to their local paths.

The Render disk prevents loss across restarts, but these stores are not
PostgreSQL-backed, cannot safely support multiple API instances, and complicate
backup/restore. Keep the API at one instance until a separately scoped,
business-logic-reviewed migration moves this state to PostgreSQL/object storage.
Existing `backend/data/order_operations.json` must be migrated securely to the
mounted disk before cutover if its current records are required.

The included authentication supports database-backed owner, admin, and operator
accounts. It does not provide MFA, automated account recovery, rate limiting, or
audit-managed credential rotation. Add those controls if the deployment's risk
profile requires them.

## Secrets and local development

`.env` variants, private-key formats, database files, generated PDFs, and the
operational JSON path are ignored by Git. `.env.example` files contain placeholders
only. Never put real credentials in `render.yaml` or a `VITE_` variable because
Vite values are public browser configuration.

Local defaults remain `http://127.0.0.1:8000` for the frontend API,
localhost PostgreSQL for the backend, and both common Vite localhost origins for
CORS. Copy the example environment files when overrides are needed.
