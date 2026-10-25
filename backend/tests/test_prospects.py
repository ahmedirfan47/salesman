"""AI prospecting: phones, import, Google Maps search, AI drafts, win-back, convert, access."""
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from openpyxl import Workbook
from sqlalchemy import func, select

from app.config import settings
from app.core.security import create_access_token, hash_password
from app.db.models.customer import Customer
from app.db.models.inventory import Inventory
from app.db.models.order import Order
from app.db.models.price_list import PriceList
from app.db.models.product import Product
from app.db.models.product_price import ProductPrice
from app.db.models.prospect import Prospect, ProspectActivity
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.models.zone import Zone
from app.db.session import get_session
from app.main import app
from app.modules.prospects import drafting, places
from app.modules.prospects.importer import ProspectFileError, parse_prospect_file
from app.modules.prospects.phones import InvalidPhone, normalize_phone


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


async def _tenant(db):
    t = Tenant(name="Al Rayyan Fresh", slug=f"t-{uuid.uuid4().hex[:10]}")
    db.add(t)
    await db.flush()
    return t


async def _user(db, tenant, role, name=None):
    u = User(tenant_id=tenant.id, email=f"{role}-{uuid.uuid4().hex[:6]}@x.co", full_name=name,
             password_hash=hash_password("pw-123456"), role=role)
    db.add(u)
    await db.flush()
    return u


def _auth(u):
    return {"Authorization": f"Bearer {create_access_token(u.id, u.tenant_id, u.role)}"}


async def _setup(db, role="salesman"):
    t = await _tenant(db)
    u = await _user(db, t, role, name="Faisal")
    await db.commit()
    return t, u


async def _catalog(db, t):
    """Active price list: tomatoes and cucumbers in stock, mangoes out of stock."""
    pl = PriceList(tenant_id=t.id, version=1, status="active")
    db.add(pl)
    await db.flush()
    now = datetime.now(timezone.utc)
    out = {}
    for sku, en, ar, price, stock in (("TOM-5", "Tomatoes 5 kg", "طماطم ٥ كجم", "35.00", 100),
                                      ("CUC-5", "Cucumbers 5 kg", "خيار ٥ كجم", "28.50", 40),
                                      ("MAN-4", "Mangoes 4 kg", None, "48.00", 0)):
        p = Product(tenant_id=t.id, sku=sku, name_en=en, name_ar=ar)
        db.add(p)
        await db.flush()
        db.add(ProductPrice(tenant_id=t.id, product_id=p.id, price_list_id=pl.id, unit_price=Decimal(price),
                            currency="SAR", effective_from=now, effective_to=None))
        db.add(Inventory(tenant_id=t.id, product_id=p.id, quantity_on_hand=stock))
        out[sku] = p
    await db.commit()
    return out


def _xlsx(rows):
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --- phones ---------------------------------------------------------------------

@pytest.mark.parametrize("raw", ["0501234567", "+966 50 123 4567", "00966501234567", "966501234567",
                                 "501234567", "٠٥٠١٢٣٤٥٦٧", 966501234567.0, "(050) 123-4567"])
def test_saudi_numbers_normalise_to_one_form(raw):
    assert normalize_phone(raw, "966") == "+966501234567"


def test_other_country_and_bad_numbers():
    assert normalize_phone("+92 300 1234567", "966") == "+923001234567"
    assert normalize_phone("", "966") is None
    with pytest.raises(InvalidPhone):
        normalize_phone("abc", "966")
    with pytest.raises(InvalidPhone):
        normalize_phone("12", "966")


# --- importer ---------------------------------------------------------------------

def test_import_arabic_headers_from_xlsx():
    rows, problems = parse_prospect_file(_xlsx([
        ["قائمة المحلات"],
        ["اسم المحل", "الجوال", "الحي", "ملاحظات"],
        ["بقالة النور", "٠٥٠١٢٣٤٥٦٧", "العليا", "يفتح بعد العصر"],
        ["Hayat Mini", "not-a-number", "Malqa", None],
        [None, None, None, None],
    ]), "shops.xlsx", "966")
    assert len(rows) == 1 and rows[0]["row"] == 3
    assert rows[0]["name"] == "بقالة النور" and rows[0]["phone"] == "+966501234567"
    assert rows[0]["area"] == "العليا" and rows[0]["notes"] == "يفتح بعد العصر"
    assert problems == [{"row": 4, "name": "Hayat Mini", "reason": "Phone 'not-a-number' is not a valid number"}]


def test_import_semicolon_csv():
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Shop name", "WhatsApp", "Zone", "Contact"])
    w.writerow(["Green Valley", "0559876543", "Riyadh North", "Khalid"])
    rows, problems = parse_prospect_file(buf.getvalue().encode("utf-8-sig"), "list.csv", "966")
    assert not problems
    assert rows[0] == {"row": 2, "name": "Green Valley", "phone": "+966559876543", "contact_name": "Khalid",
                       "address": None, "area": None, "zone": "Riyadh North", "category": None, "notes": None}


def test_import_needs_a_name_column_and_a_supported_file():
    with pytest.raises(ProspectFileError, match="name column"):
        parse_prospect_file(_xlsx([["Phone"], ["0501234567"]]), "x.xlsx", "966")
    with pytest.raises(ProspectFileError, match=".xlsx or .csv"):
        parse_prospect_file(b"x", "x.pdf", "966")


# --- create, dedupe, access -----------------------------------------------------------

async def test_create_prospect_normalises_phone_and_assigns_creator(db, client):
    t, u = await _setup(db)
    r = await client.post("/api/v1/prospects", headers=_auth(u),
                          json={"name": "Al Noor Grocery", "phone": "050 123 4567", "area": "Olaya"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["phone"] == "+966501234567" and body["phone_digits"] == "966501234567"
    assert body["assigned_to_name"] == "Faisal" and body["status"] == "new" and body["kind"] == "new"
    assert body["activities"][0]["kind"] == "created"

    dup = await client.post("/api/v1/prospects", headers=_auth(u), json={"name": "Noor 2", "phone": "+966501234567"})
    assert dup.status_code == 409 and "Already in your prospects" in dup.json()["detail"]


async def test_an_existing_customer_is_not_a_new_prospect(db, client):
    t, u = await _setup(db)
    db.add(Customer(tenant_id=t.id, name="Bait Al Khair", whatsapp_number="966501112222"))
    await db.commit()
    r = await client.post("/api/v1/prospects", headers=_auth(u), json={"name": "BAK", "phone": "0501112222"})
    assert r.status_code == 409 and "already a customer" in r.json()["detail"]


async def test_roles(db, client):
    t, u = await _setup(db)
    driver = await _user(db, t, "driver")
    demo = await _user(db, t, "demo")
    await db.commit()
    assert (await client.get("/api/v1/prospects", headers=_auth(driver))).status_code == 403
    assert (await client.get("/api/v1/prospects", headers=_auth(u))).status_code == 200
    assert (await client.get("/api/v1/prospects/summary", headers=_auth(demo))).status_code == 200
    r = await client.post("/api/v1/prospects", headers=_auth(demo), json={"name": "X"})
    assert r.status_code == 403


async def test_import_endpoint_skips_known_shops_and_matches_zones(db, client):
    t, u = await _setup(db)
    zone = Zone(tenant_id=t.id, name="Riyadh North")
    db.add(zone)
    db.add(Customer(tenant_id=t.id, name="Existing", whatsapp_number="+966500000001"))
    await db.commit()
    await client.post("/api/v1/prospects", headers=_auth(u), json={"name": "Known", "phone": "0500000002"})

    content = _xlsx([
        ["Name", "Phone", "Zone"],
        ["Existing shop", "0500000001", "Riyadh North"],
        ["Known again", "0500000002", ""],
        ["Fresh Corner", "0500000003", "riyadh north"],
        ["Fresh Corner dup", "0500000003", ""],
        ["Walk-in only", None, "Al Kharj"],
    ])
    r = await client.post("/api/v1/prospects/import", headers=_auth(u),
                          files={"file": ("shops.xlsx", content, "application/octet-stream")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2
    assert [(s["row"], s["reason"]) for s in body["skipped"]] == [
        (2, "Already a customer"), (3, "Already in your prospects"), (5, "Same number appears earlier in the file"),
    ]
    fresh = await db.scalar(select(Prospect).where(Prospect.name == "Fresh Corner"))
    walk_in = await db.scalar(select(Prospect).where(Prospect.name == "Walk-in only"))
    assert fresh.zone_id == zone.id and fresh.source == "import"
    assert walk_in.zone_id is None and walk_in.area == "Al Kharj"


async def test_status_changes(db, client):
    t, u = await _setup(db)
    p = (await client.post("/api/v1/prospects", headers=_auth(u), json={"name": "Shop"})).json()
    r = await client.patch(f"/api/v1/prospects/{p['id']}", headers=_auth(u), json={"status": "won"})
    assert r.status_code == 422
    r = await client.patch(f"/api/v1/prospects/{p['id']}", headers=_auth(u),
                           json={"status": "lost", "lost_reason": "Buys from a cousin"})
    body = r.json()
    assert body["status"] == "lost" and body["closed_at"] is not None
    assert "Buys from a cousin" in body["activities"][0]["body"]


# --- AI drafts ----------------------------------------------------------------------

def _fake_llm(monkeypatch, text=None, error=None):
    async def _chat(messages, tools=None):
        if error:
            raise error
        _fake_llm.last_messages = messages
        return SimpleNamespace(content=text)
    monkeypatch.setattr(drafting, "chat", _chat)


async def test_ai_draft_uses_real_prices_and_skips_out_of_stock(db, client, monkeypatch):
    t, u = await _setup(db)
    await _catalog(db, t)
    p = (await client.post("/api/v1/prospects", headers=_auth(u), json={"name": "Al Noor", "phone": "0501234567"})).json()
    _fake_llm(monkeypatch, "Hello Al Noor, this is Faisal from Al Rayyan Fresh. Tomatoes 5 kg are SAR 35 today. "
                           "Would you like our price list?")
    r = await client.post(f"/api/v1/prospects/{p['id']}/draft", headers=_auth(u), json={"language": "en"})
    assert r.status_code == 200
    assert r.json()["source"] == "ai" and "SAR 35" in r.json()["message"]
    sheet = _fake_llm.last_messages[1]["content"]
    assert "Tomatoes 5 kg: SAR 35" in sheet and "Cucumbers 5 kg: SAR 28.50" in sheet
    assert "Mangoes" not in sheet  # out of stock is never offered


async def test_invented_price_falls_back_to_safe_template(db, client, monkeypatch):
    t, u = await _setup(db)
    await _catalog(db, t)
    p = (await client.post("/api/v1/prospects", headers=_auth(u), json={"name": "Al Noor", "phone": "0501234567"})).json()
    _fake_llm(monkeypatch, "Hi! Tomatoes are only SAR 30 this week, 10% off!")
    r = (await client.post(f"/api/v1/prospects/{p['id']}/draft", headers=_auth(u), json={"language": "en"})).json()
    assert r["source"] == "template"
    assert "SAR 35" in r["message"] and "SAR 30" not in r["message"] and "Faisal" in r["message"]


async def test_llm_down_gives_arabic_template(db, client, monkeypatch):
    t, u = await _setup(db)
    await _catalog(db, t)
    p = (await client.post("/api/v1/prospects", headers=_auth(u), json={"name": "بقالة النور", "phone": "0501234567"})).json()
    _fake_llm(monkeypatch, error=RuntimeError("provider down"))
    r = (await client.post(f"/api/v1/prospects/{p['id']}/draft", headers=_auth(u), json={"language": "ar"})).json()
    assert r["source"] == "template" and r["language"] == "ar"
    assert "طماطم ٥ كجم: 35 ر.س" in r["message"] and "السلام عليكم" in r["message"]


def test_draft_check_rejects_links_and_wrong_language():
    f = drafting.Facts(language="en", business="B", rep=None, shop="S", contact=None, area=None,
                       winback=False, insight=None,
                       products=[drafting.PricedProduct("Tomatoes 5 kg", None, Decimal("35"), "SAR")])
    assert drafting.check_draft("Tomatoes 5 kg are SAR 35.00 today. Interested?", f)
    assert not drafting.check_draft("See www.example.com for SAR 35", f)
    assert not drafting.check_draft("مرحبا", f)
    assert not drafting.check_draft("Delivery in 2 days!", f)


# --- contacted and convert -------------------------------------------------------------

async def test_contacted_logs_message_and_advances_status(db, client):
    t, u = await _setup(db)
    p = (await client.post("/api/v1/prospects", headers=_auth(u), json={"name": "Shop", "phone": "0501234567"})).json()
    r = (await client.post(f"/api/v1/prospects/{p['id']}/contacted", headers=_auth(u),
                           json={"message": "Hello from Faisal"})).json()
    assert r["status"] == "contacted" and r["last_contacted_at"]
    assert r["activities"][0]["kind"] == "contacted" and r["activities"][0]["body"] == "Hello from Faisal"

    no_phone = (await client.post("/api/v1/prospects", headers=_auth(u), json={"name": "No phone"})).json()
    r = await client.post(f"/api/v1/prospects/{no_phone['id']}/contacted", headers=_auth(u), json={})
    assert r.status_code == 422


async def test_convert_creates_customer_once(db, client):
    t, u = await _setup(db)
    zone = Zone(tenant_id=t.id, name="Riyadh East")
    db.add(zone)
    await db.commit()
    p = (await client.post("/api/v1/prospects", headers=_auth(u),
                           json={"name": "Fresh Corner", "phone": "0503334444", "address": "King Fahd Rd"})).json()
    r = await client.post(f"/api/v1/prospects/{p['id']}/convert", headers=_auth(u), json={"zone_id": str(zone.id)})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "won" and body["customer_id"]
    c = await db.get(Customer, uuid.UUID(body["customer_id"]))
    assert c.name == "Fresh Corner" and c.whatsapp_number == "+966503334444" and c.zone_id == zone.id
    again = await client.post(f"/api/v1/prospects/{p['id']}/convert", headers=_auth(u), json={})
    assert again.status_code == 409


# --- win-back ----------------------------------------------------------------------------

async def test_winback_refresh_is_idempotent_and_closes_when_they_order(db, client, monkeypatch):
    t, u = await _setup(db)
    products = await _catalog(db, t)
    c = Customer(tenant_id=t.id, name="Al Waha Market", whatsapp_number="+966507778888")
    db.add(c)
    await db.flush()
    now = datetime.now(timezone.utc)
    for i, days_ago in enumerate((45, 40, 35, 30)):
        db.add(Order(tenant_id=t.id, order_number=f"ORD-{i}", customer_id=c.id, status="completed",
                     currency="SAR", total_amount=Decimal("100"), created_at=now - timedelta(days=days_ago)))
    await db.commit()

    r = (await client.post("/api/v1/prospects/winback/refresh", headers=_auth(u))).json()
    assert r == {"created": 1, "closed": 0}
    assert (await client.post("/api/v1/prospects/winback/refresh", headers=_auth(u))).json()["created"] == 0

    rows = (await client.get("/api/v1/prospects?kind=winback", headers=_auth(u))).json()
    assert len(rows) == 1 and rows[0]["priority"] == "high"
    assert "Usually orders every 5 days; last order 30 days ago" in rows[0]["insight"]

    _fake_llm(monkeypatch, error=RuntimeError("down"))
    draft = (await client.post(f"/api/v1/prospects/{rows[0]['id']}/draft", headers=_auth(u), json={})).json()
    assert "haven't had an order" in draft["message"]

    db.add(Order(tenant_id=t.id, order_number="ORD-NEW", customer_id=c.id, status="confirmed",
                 currency="SAR", total_amount=Decimal("50"), created_at=datetime.now(timezone.utc)))
    await db.commit()
    rows = (await client.get("/api/v1/prospects?kind=winback", headers=_auth(u))).json()
    assert rows[0]["status"] == "won"
    acts = await db.scalar(select(func.count(ProspectActivity.id)).where(ProspectActivity.kind == "won"))
    assert acts == 1


# --- Google Maps -----------------------------------------------------------------------------

def _google(monkeypatch, handler):
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", "test-key")
    real = httpx.AsyncClient

    def _client(*a, **k):
        return real(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(places.httpx, "AsyncClient", _client)


async def test_google_search_off_without_key(db, client, monkeypatch):
    t, u = await _setup(db)
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", "")
    assert (await client.get("/api/v1/prospects/summary", headers=_auth(u))).json()["google_search_enabled"] is False
    r = await client.get("/api/v1/prospects/places/search?q=grocery", headers=_auth(u))
    assert r.status_code == 503


async def test_google_search_marks_known_shops_and_add(db, client, monkeypatch):
    t, u = await _setup(db)
    db.add(Customer(tenant_id=t.id, name="Customer Shop", whatsapp_number="+966501110000"))
    await db.commit()
    seen = {}

    def handler(request: httpx.Request):
        seen["key"] = request.headers["X-Goog-Api-Key"]
        seen["mask"] = request.headers["X-Goog-FieldMask"]
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={
            "places": [
                {"id": "P1", "displayName": {"text": "Fresh Mart"}, "formattedAddress": "Olaya, Riyadh",
                 "internationalPhoneNumber": "+966 50 222 3333", "nationalPhoneNumber": "050 222 3333",
                 "businessStatus": "OPERATIONAL", "rating": 4.4, "userRatingCount": 120},
                {"id": "P2", "displayName": {"text": "Customer Shop"},
                 "internationalPhoneNumber": "+966 50 111 0000", "businessStatus": "OPERATIONAL"},
                {"id": "P3", "displayName": {"text": "Gone"}, "businessStatus": "CLOSED_PERMANENTLY"},
            ],
            "nextPageToken": "NEXT",
        })

    _google(monkeypatch, handler)
    r = await client.get("/api/v1/prospects/places/search?q=grocery store in Olaya&language=ar", headers=_auth(u))
    assert r.status_code == 200, r.text
    body = r.json()
    assert seen["key"] == "test-key" and "places.internationalPhoneNumber" in seen["mask"]
    assert '"regionCode":"SA"' in seen["body"].replace(" ", "") and '"languageCode":"ar"' in seen["body"].replace(" ", "")
    assert [p["place_id"] for p in body["results"]] == ["P1", "P2"]
    assert body["next_page_token"] == "NEXT"
    first, second = body["results"]
    assert first["phone"] == "+966502223333" and not first["already_prospect"] and not first["already_customer"]
    assert second["already_customer"] is True

    add = await client.post("/api/v1/prospects/places", headers=_auth(u), json={
        "place_id": "P1", "name": "Fresh Mart", "phone": first["phone"], "address": first["address"]})
    assert add.status_code == 201 and add.json()["source"] == "google"
    dup = await client.post("/api/v1/prospects/places", headers=_auth(u), json={"place_id": "P1", "name": "Fresh Mart"})
    assert dup.status_code == 409
    again = (await client.get("/api/v1/prospects/places/search?q=grocery", headers=_auth(u))).json()
    assert again["results"][0]["already_prospect"] is True


async def test_google_error_is_reported(db, client, monkeypatch):
    t, u = await _setup(db)
    _google(monkeypatch, lambda req: httpx.Response(403, json={"error": {"message": "API key not valid."}}))
    r = await client.get("/api/v1/prospects/places/search?q=grocery", headers=_auth(u))
    assert r.status_code == 502 and "API key not valid" in r.json()["detail"]