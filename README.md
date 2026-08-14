# SALESMAN

AI Sales & Order-Management Agent — multi-tenant SaaS.

See `SALESMAN_ARCHITECTURE.md` for the full system design.

## Phase 1 (current): Core backend
- Multi-tenant foundation (FastAPI + async SQLAlchemy 2.0 + Postgres)
- Tenant registration, JWT auth (access + refresh), RBAC (owner/admin/warehouse/viewer)
- Products module (tenant-scoped CRUD)

## Run locally

```bash
# 1. Start Postgres + Redis
docker compose up -d

# 2. Backend deps (Python 3.11+)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. Configure env
cp ../.env.example .env        # then edit JWT_SECRET

# 4. Run migrations
alembic upgrade head

# 5. Start the API
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs