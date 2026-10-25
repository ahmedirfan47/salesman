"""API tests for /analytics: access control, tenant isolation, cost entry, summary."""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio

from app.core.security import create_access_token, hash_password
from app.db.models.order import Order
from app.db.models.order_item import OrderItem
from app.db.models.price_list import PriceList
from app.db.models.product import Product
from app.db.models.product_price import ProductPrice
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.session import get_session
from app.main import app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


async def _tenant(db, name="Al Rayyan Fresh"):
    t = Tenant(name=name, slug=f"t-{uuid.uuid4().hex[:10]}")
    db.add(t)
    await db.flush()
    return t


async def _user(db, tenant, role):
    u = User(
        tenant_id=tenant.id, email=f"{role}-{uuid.uuid4().hex[:6]}@x.test",
        password_hash=hash_password("pw-123456"), role=role,
    )
    db.add(u)
    await db.flush()
    return u


def _auth(u):
    return {"Authorization": f"Bearer {create_access_token(u.id, u.tenant_id, u.role)}"}


async def _product(db, tenant, sku, price=None, currency="SAR"):
    p = Product(tenant_id=tenant.id, sku=sku, name_en=sku.title())
    db.add(p)
    await db.flush()
    if price is not None:
        pl = PriceList(tenant_id=tenant.id, version=1, status="active")
        db.add(pl)
        await db.flush()
        db.add(ProductPrice(
            tenant_id=tenant.id, product_id=p.id, price_list_id=pl.id, unit_price=price,
            currency=currency, effective_from=datetime.now(timezone.utc) - timedelta(days=1),
        ))
        await db.flush()
    return p


async def _sale(db, tenant, product, *, qty, price, cost, number, status="completed"):
    o = Order(tenant_id=tenant.id, order_number=number, status=status, currency="SAR",
              created_at=datetime.now(timezone.utc) - timedelta(days=1))
    db.add(o)
    await db.flush()
    db.add(OrderItem(tenant_id=tenant.id, order_id=o.id, product_id=product.id, sku=product.sku,
                     product_name=product.name_en, quantity=qty, unit_price=price,
                     line_total=price * qty, unit_cost=cost))
    await db.flush()


@pytest.mark.parametrize("role", ["salesman", "viewer", "driver", "dispatcher", "warehouse"])
async def test_non_owner_roles_cannot_see_analytics(db, client, role):
    t = await _tenant(db)
    u = await _user(db, t, role)
    await db.commit()
    r = await client.get("/api/v1/analytics/summary", headers=_auth(u))
    assert r.status_code == 403


async def test_requires_auth(client):
    r = await client.get("/api/v1/analytics/summary")
    assert r.status_code == 401


async def test_summary_uses_only_costed_lines_and_reports_coverage(db, client):
    t = await _tenant(db)
    owner = await _user(db, t, "owner")
    tom = await _product(db, t, "TOMATO", price=35)
    pot = await _product(db, t, "POTATO", price=22)
    await _sale(db, t, tom, qty=10, price=35, cost=25, number="ORD-1")    # revenue 350, cost 250
    await _sale(db, t, pot, qty=10, price=22, cost=None, number="ORD-2")  # revenue 220, cost unknown
    await _sale(db, t, tom, qty=99, price=35, cost=25, number="ORD-3", status="cancelled")
    await db.commit()

    r = await client.get("/api/v1/analytics/summary?days=30", headers=_auth(owner))
    assert r.status_code == 200
    s = r.json()
    assert s["revenue"] == 570
    assert s["order_count"] == 2
    assert s["costed_revenue"] == 350
    assert s["costed_profit"] == 100
    assert s["margin_percent"] == pytest.approx(28.6)
    assert s["cost_coverage_percent"] == pytest.approx(61.4)
    assert s["products_missing_cost"] == 2   # neither product has Product.cost_price set
    assert s["currency"] == "SAR"


async def test_set_costs_then_list_shows_current_margin(db, client):
    t = await _tenant(db)
    owner = await _user(db, t, "owner")
    tom = await _product(db, t, "TOMATO", price=35)
    await db.commit()

    r = await client.put("/api/v1/analytics/product-costs", headers=_auth(owner),
                         json={"items": [{"product_id": str(tom.id), "cost_price": "24.50"}]})
    assert r.status_code == 200 and r.json() == {"updated": 1}

    rows = (await client.get("/api/v1/analytics/product-costs", headers=_auth(owner))).json()
    row = next(x for x in rows if x["sku"] == "TOMATO")
    assert row["cost_price"] == 24.5
    assert row["cost_currency"] == "SAR"          # defaulted from the sell price
    assert row["current_margin_percent"] == 30.0  # (35 - 24.5) / 35

    # clearing a cost returns it to unknown
    r = await client.put("/api/v1/analytics/product-costs", headers=_auth(owner),
                         json={"items": [{"product_id": str(tom.id), "cost_price": None}]})
    rows = (await client.get("/api/v1/analytics/product-costs", headers=_auth(owner))).json()
    assert rows[0]["cost_price"] is None and rows[0]["current_margin_percent"] is None


async def test_cannot_set_cost_on_another_tenants_product(db, client):
    mine = await _tenant(db, "Mine")
    theirs = await _tenant(db, "Theirs")
    owner = await _user(db, mine, "owner")
    foreign = await _product(db, theirs, "SECRET", price=10)
    await db.commit()

    r = await client.put("/api/v1/analytics/product-costs", headers=_auth(owner),
                         json={"items": [{"product_id": str(foreign.id), "cost_price": "1"}]})
    assert r.status_code == 404
    await db.refresh(foreign)
    assert foreign.cost_price is None


async def test_product_costs_are_tenant_scoped(db, client):
    mine = await _tenant(db, "Mine")
    theirs = await _tenant(db, "Theirs")
    owner = await _user(db, mine, "owner")
    await _product(db, mine, "MINE", price=10)
    await _product(db, theirs, "THEIRS", price=10)
    await db.commit()

    rows = (await client.get("/api/v1/analytics/product-costs", headers=_auth(owner))).json()
    assert [r["sku"] for r in rows] == ["MINE"]


async def test_negative_cost_rejected(db, client):
    t = await _tenant(db)
    owner = await _user(db, t, "owner")
    p = await _product(db, t, "X", price=10)
    await db.commit()
    r = await client.put("/api/v1/analytics/product-costs", headers=_auth(owner),
                         json={"items": [{"product_id": str(p.id), "cost_price": "-1"}]})
    assert r.status_code == 422


async def test_margin_and_health_endpoints_respond(db, client):
    t = await _tenant(db)
    owner = await _user(db, t, "admin")
    await db.commit()
    for path in ("margins", "drifting-customers", "stuck-orders"):
        r = await client.get(f"/api/v1/analytics/{path}", headers=_auth(owner))
        assert r.status_code == 200, path
        assert r.json() == []