"""Save the demo business's screens as sample data for the dashboard's "See the demo" button.

    python -m app.scripts.seed_demo --email demo@stonic.site --password "demo-pass-123"
    python -m app.scripts.export_preview

Run both from backend/ against your local database. The second command signs in
as the read-only demo account (in-process, no server needed), reads every screen
the dashboard shows and writes dashboard/public/preview/data.json. The "See the
demo" button on the plans page opens those screens without a sign-in and without
a backend. Run it again any time to refresh the sample data (for example after
`seed_demo --reset`, which moves the dates up), then commit data.json.
"""
import argparse
import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import select

from app.core.security import create_access_token
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.session import SessionLocal
from app.main import app
from app.modules.platform import access

DEMO_SLUG = "salesman-demo"
DEFAULT_OUT = Path(__file__).resolve().parents[3] / "dashboard" / "public" / "preview" / "data.json"
PROSPECT_STATUSES = ("open", "new", "contacted", "interested", "won", "lost")

# Every screen's data that doesn't depend on a clicked row.
STATIC = [
    "/auth/me", "/branches", "/branches/whatsapp-setup", "/products", "/products/catalog", "/customers", "/users",
    "/zones", "/zones/my-deliveries/list", "/orders", "/orders/escalations/open", "/pricing/price-lists",
    "/printing/jobs", "/conversations", "/billing",
    "/accounts", "/accounts/settings", "/accounts/payments", "/accounts/invoices",
    "/analytics/product-costs", "/analytics/stuck-orders", "/analytics/drifting-customers",
    "/prospects", "/prospects/summary",
    "/zatca", "/zatca/documents",
    "/integrations", "/integrations/options", "/integrations/balances", "/integrations/events",
]


async def _demo_user() -> User:
    async with SessionLocal() as db:
        tenant = await db.scalar(select(Tenant).where(Tenant.slug == DEMO_SLUG))
        if tenant is None:
            raise SystemExit("No demo business found. Run `python -m app.scripts.seed_demo` first.")
        user = await db.scalar(select(User).where(User.tenant_id == tenant.id, User.role == "demo"))
        if user is None:
            raise SystemExit("The demo business has no demo user. Run `python -m app.scripts.seed_demo` again.")
        return user


async def _switches_ignored(db, user):
    """Only a switched-off account is refused here: closing sign-in in the Stonic Console
    keeps people out of the site, not this export, which runs in-process and only reads."""
    return ("inactive", access.INACTIVE) if not user.is_active else None


async def export(out: Path) -> None:
    logging.disable(logging.INFO)  # keep the request log quiet
    access.blocked = _switches_ignored
    user = await _demo_user()
    token = create_access_token(user.id, user.tenant_id, user.role, user.token_version)
    responses: dict[str, dict] = {}

    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token}", "X-Client": "api"}
    async with httpx.AsyncClient(transport=transport, base_url="http://preview/api/v1", headers=headers) as client:

        async def get(path: str):
            r = await client.get(path)
            try:
                body = r.json()
            except ValueError:
                body = None
            responses[path] = {"status": r.status_code, "body": body}
            return body if r.status_code < 400 else None

        me = await client.get("/auth/me")
        if me.status_code >= 400:
            detail = (me.json() if me.content else {}).get("detail", me.text)
            raise SystemExit(f"The demo account was refused ({me.status_code}): {detail}\n"
                             "Run `python -m app.scripts.seed_demo ... --reset` and try again.")

        for path in STATIC:
            await get(path)

        today = date.today()
        for days in (7, 30, 90):
            await get(f"/analytics/summary?days={days}")
            await get(f"/analytics/margins?days={days}")
        for back in range(7):
            await get(f"/reports/daily/summary?day={today - timedelta(days=back)}")
        for status in PROSPECT_STATUSES:
            await get(f"/prospects?status={status}")

        def rows(path: str) -> list:
            body = responses[path]["body"]
            return body if responses[path]["status"] < 400 and isinstance(body, list) else []

        # rows people can open
        for o in rows("/orders"):
            await get(f"/orders/{o['id']}")
            await get(f"/accounts/orders/{o['id']}/invoice")
        for c in rows("/conversations"):
            await get(f"/conversations/{c['id']}/messages")
        for p in rows("/prospects"):
            await get(f"/prospects/{p['id']}")
        for u in rows("/users"):
            if u["role"] == "driver":
                await get(f"/zones/drivers/{u['id']}/zones")
        for z in rows("/zones"):
            await get(f"/zones/suggest-driver/{z['id']}")
        accounts_body = responses["/accounts"]["body"]
        accounts = accounts_body.get("customers", []) if isinstance(accounts_body, dict) else []
        start, end = today - timedelta(days=90), today
        for a in accounts:
            cid = a.get("customer_id") or a.get("id")
            await get(f"/accounts/customers/{cid}")
            await get(f"/accounts/customers/{cid}/statement?start={start}&end={end}")

    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"captured_at": datetime.now(timezone.utc).isoformat(), "responses": responses}
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
    failed = sorted(p for p, r in responses.items() if r["status"] >= 400)
    print(f"Saved {len(responses)} screens to {out} ({out.stat().st_size // 1024} KB).")
    if failed:
        print(f"{len(failed)} answered with an error (the preview shows the same message): {', '.join(failed[:8])}"
              + (" ..." if len(failed) > 8 else ""))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Save demo screens for the dashboard preview mode")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where to write data.json")
    asyncio.run(export(parser.parse_args().out))