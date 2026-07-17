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

## Database migrations

From `backend/`, run `alembic upgrade head` after PostgreSQL is available. Migration files will be added as domain models are introduced.
