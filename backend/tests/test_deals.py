"""Customer prices, promotions and free goods: the pricing rule, orders, the AI tools and the API."""
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.ai import tools
from app.db.models.order_item import OrderItem
from app.modules.accounts import service as accounts
from app.modules.deals import service as deals
from app.modules.orders import service as orders
from app.modules.pricing import service as pricing
from app.schemas.order import OrderCreate, OrderItemIn
from tests.test_order_intelligence import _business, _customer, _owner, client, session  # noqa: F401

D = Decimal


async def _items(db, order):
    return list(await db.scalars(select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.is_free)))


async def _order(db, t, c, *lines):
    return await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku=s, quantity=q) for s, q in lines],
                                                           customer_id=c.id))


async def test_customer_price_tiers_and_dates(session):
    db = session
    t, branch = await _business(db)
    c = await _customer(db, t, branch)
    other = await _customer(db, t, branch, phone="+966500000002", name="Other shop")
    today = await accounts._today(db, t.id)
    await deals.save_customer_price(db, t.id, {"customer_id": c.id, "sku": "TOM-5", "unit_price": D("95")})
    await deals.save_customer_price(db, t.id, {"customer_id": c.id, "sku": "TOM-5", "unit_price": D("90"), "min_quantity": 10})
    await deals.save_customer_price(db, t.id, {"customer_id": c.id, "sku": "MAN-4", "unit_price": D("30"),
                                               "valid_from": today + timedelta(days=3)})   # not yet

    order = await _order(db, t, c, ("TOM-5", 2), ("MAN-4", 1))
    tom, man = sorted(await _items(db, order), key=lambda i: i.sku, reverse=True)
    assert (tom.unit_price, tom.list_price, tom.price_source) == (D("95.00"), D("100.00"), "customer")
    assert (man.unit_price, man.price_source) == (D("40.00"), "list")
    big = await _order(db, t, c, ("TOM-5", 12))
    assert (await _items(db, big))[0].unit_price == D("90.00") and big.total_amount == D("1080.00")
    assert (await _items(db, await _order(db, t, other, ("TOM-5", 2))))[0].unit_price == D("100.00")

    # saving the same customer, product and tier again updates it
    again = await deals.save_customer_price(db, t.id, {"customer_id": c.id, "sku": "TOM-5", "unit_price": D("94")})
    assert again["unit_price"] == D("94.00") and len(await deals.list_customer_prices(db, t.id, c.id)) == 3


async def test_best_price_wins_and_deals_dont_stack(session):
    db = session
    t, branch = await _business(db)
    c = await _customer(db, t, branch)
    await deals.save_customer_price(db, t.id, {"customer_id": c.id, "sku": "TOM-5", "unit_price": D("85")})
    await deals.save_promotion(db, t.id, {"kind": "percent_off", "sku": "TOM-5", "percent_off": D("10")})
    order = await _order(db, t, c, ("TOM-5", 1))
    assert (await _items(db, order))[0].unit_price == D("85.00")      # 85 < 90: their price, no extra 10%

    await deals.save_promotion(db, t.id, {"kind": "fixed_price", "sku": "TOM-5", "fixed_price": D("80"),
                                          "min_quantity": 5, "name": "Weekend tomatoes"})
    item = (await _items(db, await _order(db, t, c, ("TOM-5", 5))))[0]
    assert (item.unit_price, item.price_source) == (D("80.00"), "promotion") and item.promotion_id is not None

    with pytest.raises(HTTPException, match="percentage"):
        await deals.save_promotion(db, t.id, {"kind": "percent_off", "sku": "TOM-5", "percent_off": D("150")})


async def test_free_goods_are_added_and_never_take_paid_stock(session):
    db = session
    t, branch = await _business(db, stock=23)
    c = await _customer(db, t, branch)
    await deals.save_promotion(db, t.id, {"kind": "buy_get", "sku": "TOM-5", "buy_quantity": 10, "free_quantity": 1})
    await deals.save_promotion(db, t.id, {"kind": "buy_get", "sku": "MAN-4", "buy_quantity": 5, "free_quantity": 1,
                                          "free_sku": "MLK-1L"})

    order = await _order(db, t, c, ("TOM-5", 20), ("MAN-4", 10))
    assert order.status == "confirmed" and order.total_amount == D("2400.00")
    items = await _items(db, order)
    free = {i.sku: i for i in items if i.is_free}
    assert free["TOM-5"].quantity == 2 and free["TOM-5"].unit_price == D("0.00")
    assert free["MLK-1L"].quantity == 2 and free["MLK-1L"].product_name == "Almarai Milk 1L"
    assert (await pricing.get_current_price(db, t.id, "TOM-5", branch.id))["quantity_on_hand"] == 1   # 23 - 20 - 2
    assert (await pricing.get_current_price(db, t.id, "MLK-1L", branch.id))["quantity_on_hand"] == 21

    # stock left: 1 tomato box. Buying 10 more is short -> held; free goods never cause the hold
    held = await _order(db, t, c, ("MAN-4", 5))
    assert held.status == "confirmed" and {i.sku for i in await _items(db, held) if i.is_free} == {"MLK-1L"}


async def test_free_goods_given_only_from_spare_stock(session):
    db = session
    t, branch = await _business(db, stock=11)
    c = await _customer(db, t, branch)
    await deals.save_promotion(db, t.id, {"kind": "buy_get", "sku": "TOM-5", "buy_quantity": 5, "free_quantity": 1})
    order = await _order(db, t, c, ("TOM-5", 10))       # earns 2 free, only 1 spare
    assert [i.quantity for i in await _items(db, order) if i.is_free] == [1]
    assert (await pricing.get_current_price(db, t.id, "TOM-5", branch.id))["quantity_on_hand"] == 0


async def test_ai_sees_the_customers_price_and_offers(session):
    db = session
    t, branch = await _business(db)
    c = await _customer(db, t, branch)
    await deals.save_customer_price(db, t.id, {"customer_id": c.id, "sku": "MAN-4", "unit_price": D("36")})
    await deals.save_promotion(db, t.id, {"kind": "buy_get", "sku": "MAN-4", "buy_quantity": 10, "free_quantity": 1})
    ctx = tools.ToolContext(tenant_id=t.id, branch_id=branch.id, customer_number=c.whatsapp_number)
    out = await tools._get_price_and_stock(db, ctx, "MAN-4")
    assert out["unit_price"] == 36.0 and out["list_price"] == 40.0 and out["price_note"] == "This customer's agreed price"
    assert out["offers"] == ["Buy 10 Mangoes 4 kg, get 1 free"]

    placed = await tools._place_order(db, ctx, [{"sku": "MAN-4", "quantity": 10, "customer_wording": "mango"}])
    assert placed["total_amount"] == 360.0 and placed["free_items"] == [{"name": "Mangoes 4 kg", "quantity": 1}]


async def test_api(session, client):
    db = session
    t, branch = await _business(db)
    c = await _customer(db, t, branch)
    owner = await _owner(db, t)
    r = await client.post("/api/v1/deals/customer-prices", headers=owner,
                          json={"customer_id": str(c.id), "sku": "TOM-5", "unit_price": "92.50"})
    assert r.status_code == 200 and r.json()["customer_name"] == "Al Noor Grocery"
    r = await client.post("/api/v1/deals/promotions", headers=owner,
                          json={"kind": "buy_get", "sku": "TOM-5", "buy_quantity": 10, "free_quantity": 1})
    assert r.status_code == 200 and r.json()["summary"] == "Buy 10 Tomatoes 5 kg, get 1 free" and r.json()["live"]
    r = await client.get(f"/api/v1/deals/quote?sku=TOM-5&quantity=20&customer_id={c.id}", headers=owner)
    body = r.json()
    assert body["unit_price"] == "92.50" and body["source"] == "customer" and body["line_total"] == "1850.00"
    assert body["free"][0]["quantity"] == 2
    promo_id = (await client.get("/api/v1/deals/promotions", headers=owner)).json()[0]["id"]
    assert (await client.delete(f"/api/v1/deals/promotions/{promo_id}", headers=owner)).status_code == 204
