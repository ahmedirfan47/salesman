"""ZATCA e-invoicing: signing checked against ZATCA's own SDK output, the hash chain, onboarding and submission."""
import base64
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from cryptography import x509
from sqlalchemy import select

from app.core.branches import default_branch
from app.core.secret_box import open_, seal
from app.core.security import create_access_token, hash_password
from app.db.models.customer import Customer
from app.db.models.job import Job
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.models.zatca import ZatcaDocument, ZatcaUnit
from app.db.session import get_session
from app.jobs.queue import ZATCA_SUBMIT
from app.main import app
from app.modules.accounts import pdf as account_pdf
from app.modules.accounts import service as accounts
from app.modules.orders import service as orders
from app.modules.pricing import service as pricing
from app.modules.zatca import client, crypto
from app.modules.zatca import service as zatca
from app.modules.zatca import xml as zx
from app.schemas.order import OrderCreate, OrderItemIn
from app.schemas.pricing import PriceLineIn, PriceListCreate

D = Decimal
FIXTURES = Path(__file__).parent / "fixtures" / "zatca"
# ZATCA's SDK test certificate and its private key (public test material from the official SDK)
CERT = (FIXTURES / "cert.pem").read_text().strip()
KEY = (FIXTURES / "private-key.pem").read_text().strip()
SELLER = dict(
    seller_name="Al Rayyan Fresh", seller_name_ar="الريان للخضار", seller_vat_number="399999999900003",
    seller_cr_number="1010010000", seller_street="Prince Sultan", seller_building_number="2322",
    seller_district="Al-Murabba", seller_city="Riyadh", seller_postal_code="23333",
)
B2B_ADDRESS = dict(street="Salah Al-Din", building_number="1111", district="Al-Murooj", city="Riyadh", postal_code="12222")


# ---- signing, checked against documents signed by ZATCA's Java SDK ------------------------------

@pytest.mark.parametrize("name", ["simplified-invoice.xml", "standard-credit-note.xml"])
def test_hashes_digests_and_signature_match_zatcas_sdk(name):
    signed = (FIXTURES / name).read_text(encoding="utf-8")
    digests = re.findall(r"<ds:DigestValue>([^<]+)</ds:DigestValue>", signed)
    cert = crypto.certificate_info(re.search(r"<ds:X509Certificate>([^<]+)<", signed).group(1))
    signing_time = re.search(r"<xades:SigningTime>([^<]+)<", signed).group(1)

    assert zx.invoice_hash(signed) == digests[0]
    assert zx.signed_properties_digest(signing_time, cert) == digests[1]
    assert cert.digest == digests[2]
    assert cert.issuer == re.search(r"<ds:X509IssuerName>([^<]+)<", signed).group(1)
    assert cert.serial_number == re.search(r"<ds:X509SerialNumber>([^<]+)<", signed).group(1)
    signature = re.search(r"<ds:SignatureValue>([^<]+)<", signed).group(1)
    assert crypto.verify_hash_signature(digests[0], signature, cert.public_key)


def test_csr_carries_the_template_and_the_egs_details():
    pem = crypto.build_csr(crypto.CsrInput(
        common_name="Salesman-Riyadh", organization="Al Rayyan Fresh", organization_unit="Riyadh",
        vat_number="399999999900003", egs_serial="1-Salesman|2-2.0|3-abc", invoice_types="1100",
        location="Riyadh", industry="Wholesale",
    ), crypto.new_private_key_pem(), "simulation")
    csr = x509.load_pem_x509_csr(pem.encode())
    assert csr.is_signature_valid
    template = csr.extensions.get_extension_for_oid(x509.ObjectIdentifier("1.3.6.1.4.1.311.20.2")).value.value
    assert template == b"\x0c\x15PREZATCA-Code-Signing"
    san = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    dirname = {a.oid.dotted_string: a.value for a in san.get_values_for_type(x509.DirectoryName)[0]}
    assert dirname["2.5.4.4"] == "1-Salesman|2-2.0|3-abc" and dirname["0.9.2342.19200300.100.1.1"] == "399999999900003"
    assert dirname["2.5.4.12"] == "1100"
    assert base64.b64decode(crypto.csr_for_api(pem)).decode() == pem


def _doc(flow="simplified", kind="invoice", **kw) -> zx.Document:
    seller = zx.Party(name="الريان | Al Rayyan", vat_number="399999999900003", other_id="1010010000",
                      address=zx.Address("Prince Sultan", "2322", "Al-Murabba", "Riyadh", "23333"))
    buyer = zx.Party(name="Al Noor", vat_number="399999999800003", address=zx.Address("Salah", "1111", "Murooj", "Riyadh", "12222"))
    base = dict(number="INV-000001", uuid=str(uuid.uuid4()), kind=kind, flow=flow, issue_date=date(2026, 10, 27),
                issue_time="10:15:00", icv=1, pih=zx.FIRST_PIH, seller=seller,
                buyer=buyer if flow == "standard" else None, supply_date=date(2026, 10, 27),
                lines=[zx.Line("Tomatoes 5 kg", D("20"), D("700.00"), D("105.00"), D("15"))],
                billing_reference="INV-000001" if kind != "invoice" else None,
                reason="Returned" if kind != "invoice" else None)
    base.update(kw)
    return zx.Document(**base)


def test_signing_keeps_the_hash_and_stamps_the_qr():
    signed = zx.sign(_doc(), CERT, KEY, signing_time=datetime(2026, 10, 27, 7, 15, tzinfo=timezone.utc))
    assert zx.invoice_hash(signed.xml) == signed.invoice_hash
    assert "<xades:SigningTime>2026-10-27T07:15:00</xades:SigningTime>" in signed.xml
    assert zx.qr_from_xml(signed.xml) == signed.qr
    tags = zx.decode_qr(signed.qr)
    assert tags[1].decode() == "الريان | Al Rayyan" and tags[2] == b"399999999900003"
    assert tags[3] == b"2026-10-27T10:15:00" and tags[4] == b"805.00" and tags[5] == b"105.00"
    assert tags[6].decode() == signed.invoice_hash and 9 in tags  # simplified: certificate signature included
    cert = crypto.certificate_info(CERT)
    assert crypto.verify_hash_signature(signed.invoice_hash, signed.signature, cert.public_key)
    # standard documents leave tag 9 for ZATCA's own stamp
    assert 9 not in zx.decode_qr(zx.sign(_doc("standard"), CERT, KEY).qr)


def test_credit_notes_reference_the_invoice_and_give_a_reason():
    signed = zx.sign(_doc("standard", "credit_note", number="CN-000001"), CERT, KEY)
    assert '<cbc:InvoiceTypeCode name="0100000">381</cbc:InvoiceTypeCode>' in signed.xml
    assert "<cbc:InstructionNote>Returned</cbc:InstructionNote>" in signed.xml
    assert "<cac:InvoiceDocumentReference>\n            <cbc:ID>INV-000001</cbc:ID>" in signed.xml


def test_validation_explains_what_zatca_would_reject():
    no_address = _doc("standard", buyer=zx.Party(name="Shop", vat_number="399999999800003"))
    assert any("customer's address" in p for p in zx.validate(no_address))
    bad_vat = _doc(buyer=None)
    bad_vat.seller.vat_number = "123"
    assert any("VAT number must be 15 digits" in p for p in zx.validate(bad_vat))


# ---- the business flow ------------------------------------------------------------------------

@pytest_asyncio.fixture
async def session(db):
    db.sync_session.autoflush = False
    yield db
    client.TRANSPORT = None


@pytest_asyncio.fixture
async def http(session):
    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


async def _business(db, *, connected=True, seller=True):
    t = Tenant(name="Al Rayyan Fresh", slug=f"t-{uuid.uuid4().hex[:10]}", timezone="Asia/Riyadh")
    db.add(t)
    await db.flush()
    branch = await default_branch(db, t.id)
    await db.commit()
    pl = await pricing.create_price_list(db, t.id, PriceListCreate(lines=[
        PriceLineIn(sku="TOM-5", unit_price=D("100"), quantity=500, currency="SAR", name_en="Tomatoes 5 kg"),
    ]), branch_id=branch.id)
    await pricing.activate_price_list(db, t.id, pl.id)
    await accounts.update_settings(db, t.id, SELLER if seller else {})
    unit = None
    if connected:
        unit = ZatcaUnit(
            tenant_id=t.id, branch_id=branch.id, environment="sandbox", status="active", common_name="Salesman-Main",
            egs_serial="1-Salesman|2-2.0|3-test", organization_unit="Main", invoice_types="1100", location="Riyadh",
            industry="Wholesale", private_key=seal(KEY), csr="csr", compliance_results=[],
            production_token=base64.b64encode(CERT.encode()).decode(), production_secret=seal("secret"),
            certificate=CERT, icv=0, last_hash=zx.FIRST_PIH, onboarded_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.add(unit)
        await db.commit()
    return t, branch, unit


async def _customer(db, t, branch, name="Al Noor Grocery", **kw):
    c = Customer(tenant_id=t.id, branch_id=branch.id, name=name, whatsapp_number=f"+9665{uuid.uuid4().int % 10**8:08d}", **kw)
    db.add(c)
    await db.commit()
    return c


async def _invoice(db, t, c, qty=1):
    order = await orders.create_order(db, t.id, OrderCreate(items=[OrderItemIn(sku="TOM-5", quantity=qty)], customer_id=c.id))
    for s in ("dispatched", "delivered"):
        order = await orders.transition_order(db, t.id, order.id, s)
    return await accounts.invoice_for_order(db, order.id), order


async def _docs(db, t):
    return list(await db.scalars(select(ZatcaDocument).where(ZatcaDocument.tenant_id == t.id).order_by(ZatcaDocument.created_at)))


async def test_invoices_are_signed_on_issue_and_chained(session):
    db = session
    t, b, unit = await _business(db)
    c = await _customer(db, t, b)
    first, _ = await _invoice(db, t, c)
    second, _ = await _invoice(db, t, c, qty=2)
    d1, d2 = await _docs(db, t)

    assert (d1.flow, d1.kind, d1.status, d1.icv, d1.pih) == ("simplified", "invoice", "queued", 1, zx.FIRST_PIH)
    assert (d2.icv, d2.pih) == (2, d1.invoice_hash)
    assert zx.invoice_hash(d2.xml) == d2.invoice_hash and f"<cbc:ID>{second.number}</cbc:ID>" in d2.xml
    await db.refresh(unit)
    assert (unit.icv, unit.last_hash) == (2, d2.invoice_hash)
    jobs = list(await db.scalars(select(Job).where(Job.kind == ZATCA_SUBMIT)))
    assert {j.payload["document_id"] for j in jobs} == {str(d1.id), str(d2.id)} and jobs[0].max_attempts == 12

    # a credit note is signed too, in the same flow as its invoice
    await accounts.issue_credit_note(db, t.id, second.id, amount=D("50"), reason="Two boxes damaged")
    d3 = (await _docs(db, t))[-1]
    assert (d3.kind, d3.flow, d3.icv, d3.pih) == ("credit_note", "simplified", 3, d2.invoice_hash)
    assert f"<cbc:ID>{second.number}</cbc:ID>\n        </cac:InvoiceDocumentReference>" in d3.xml

    # the PDF carries the QR code
    pdf = account_pdf.render_invoice_pdf(first, await zatca.einvoice_for_pdf(db, first))
    assert b"/Subtype /Image" in pdf


async def test_nothing_is_signed_until_the_branch_is_connected(session):
    db = session
    t, b, _ = await _business(db, connected=False)
    c = await _customer(db, t, b)
    await _invoice(db, t, c)
    assert await _docs(db, t) == []


async def test_b2b_customer_without_an_address_is_blocked_then_fixed_and_sent(session, http):
    db = session
    t, b, unit = await _business(db)
    c = await _customer(db, t, b, vat_number="399999999800003")
    inv, _ = await _invoice(db, t, c)
    (blocked,) = await _docs(db, t)
    assert blocked.status == "blocked" and blocked.flow == "standard" and blocked.icv is None
    assert any("customer's address" in e["message"] for e in blocked.errors)
    await db.refresh(unit)
    assert unit.icv == 0  # no counter used for a document that was never signed

    owner = User(tenant_id=t.id, email=f"o-{uuid.uuid4().hex[:6]}@x.co", role="owner", password_hash=hash_password("pw-123456"))
    db.add(owner)
    await db.commit()
    auth = {"Authorization": f"Bearer {create_access_token(owner.id, owner.tenant_id, owner.role)}"}
    r = await http.patch(f"/api/v1/accounts/customers/{c.id}/tax-details", json=B2B_ADDRESS, headers=auth)
    assert r.status_code == 200 and r.json()["postal_code"] == "12222"

    r = await http.post(f"/api/v1/zatca/documents/{blocked.id}/resubmit", headers=auth)
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["status"] == "queued" and new["flow"] == "standard" and new["icv"] == 1
    await db.refresh(blocked)
    assert blocked.status == "superseded" and str(blocked.replaced_by_id) == new["id"]
    doc = await db.get(ZatcaDocument, uuid.UUID(new["id"]))
    assert "<cbc:PostalZone>12222</cbc:PostalZone>" in doc.xml and "<cbc:CompanyID>399999999800003</cbc:CompanyID>" in doc.xml

    listing = (await http.get(f"/api/v1/accounts/invoices?customer_id={c.id}", headers=auth)).json()
    assert listing[0]["einvoice"] == {"document_id": new["id"], "flow": "standard", "status": "queued"}


def _mock(handler):
    client.TRANSPORT = httpx.MockTransport(handler)


async def test_submission_outcomes(session):
    db = session
    t, b, _ = await _business(db)
    simple = await _customer(db, t, b)
    b2b = await _customer(db, t, b, name="Big Buyer", vat_number="399999999800003", **B2B_ADDRESS)
    await _invoice(db, t, simple)
    await _invoice(db, t, b2b)
    reported_doc, cleared_doc = await _docs(db, t)
    seen = []

    def ok(request: httpx.Request):
        body = json.loads(request.content)
        seen.append((request.url.path, request.headers["Clearance-Status"], request.headers["Accept-Version"],
                     request.headers["Authorization"]))
        if request.url.path.endswith("/clearance/single"):
            cleared = base64.b64decode(body["invoice"]).decode().replace(cleared_doc.qr, "ZATCAQR")
            return httpx.Response(200, json={"validationResults": {"status": "PASS", "warningMessages": [], "errorMessages": []},
                                             "clearanceStatus": "CLEARED", "clearedInvoice": base64.b64encode(cleared.encode()).decode()})
        return httpx.Response(202, json={"validationResults": {"status": "WARNING", "errorMessages": [], "warningMessages": [
            {"code": "BR-KSA-98", "message": "Reported late", "category": "KSA"}]}, "reportingStatus": "REPORTED"})

    _mock(ok)
    assert await zatca.submit_document(db, reported_doc.id) == "reported"
    assert await zatca.submit_document(db, cleared_doc.id) == "cleared"
    await db.refresh(reported_doc)
    await db.refresh(cleared_doc)
    assert reported_doc.warnings[0]["code"] == "BR-KSA-98" and reported_doc.zatca_status == "REPORTED"
    assert cleared_doc.cleared_xml and cleared_doc.qr == "ZATCAQR"
    assert seen[0][0].endswith("/developer-portal/invoices/reporting/single") and seen[0][1] == "0" and seen[0][2] == "V2"
    assert seen[1][0].endswith("/invoices/clearance/single") and seen[1][1] == "1"
    token = base64.b64decode(seen[0][3].split()[1]).decode()
    assert token == f"{base64.b64encode(CERT.encode()).decode()}:secret"
    assert await zatca.submit_document(db, reported_doc.id) == "skipped"  # done is done


async def test_rejections_and_outages(session):
    db = session
    t, b, _ = await _business(db)
    c = await _customer(db, t, b)
    for _ in range(3):
        await _invoice(db, t, c)
    rejected, waiting, duplicate = await _docs(db, t)

    _mock(lambda r: httpx.Response(400, json={"validationResults": {"status": "ERROR", "warningMessages": [], "errorMessages": [
        {"code": "BR-KSA-37", "message": "The seller address building number must contain 4 digits.", "category": "KSA"}]},
        "reportingStatus": "NOT_REPORTED"}))
    assert await zatca.submit_document(db, rejected.id) == "rejected"
    await db.refresh(rejected)
    assert rejected.errors[0]["code"] == "BR-KSA-37"

    _mock(lambda r: httpx.Response(503, text="maintenance"))
    with pytest.raises(client.ZatcaUnavailable):
        await zatca.submit_document(db, waiting.id)
    await db.refresh(waiting)
    assert waiting.status == "queued" and waiting.attempts == 1 and "503" in waiting.last_error

    _mock(lambda r: httpx.Response(409, json={"validationResults": {"status": "ERROR", "errorMessages": [
        {"message": "Invoice was already Reported successfully earlier."}]}, "reportingStatus": "NOT_REPORTED"}))
    assert await zatca.submit_document(db, duplicate.id) == "reported"

    # a rejected document is replaced by a new one: new UUID, next ICV, PIH = the latest hash
    unit = await zatca.unit_for_branch(db, b.id)
    new = await zatca.resubmit(db, t.id, rejected.id)
    assert new.icv == 4 and new.pih == duplicate.invoice_hash and new.document_uuid != rejected.document_uuid
    await db.refresh(unit)
    assert unit.last_hash == new.invoice_hash


async def test_onboarding_runs_the_compliance_checks_then_goes_live(session, http):
    db = session
    t, b, _ = await _business(db, connected=False)
    owner = User(tenant_id=t.id, email=f"o-{uuid.uuid4().hex[:6]}@x.co", role="owner", password_hash=hash_password("pw-123456"))
    rep = User(tenant_id=t.id, email=f"s-{uuid.uuid4().hex[:6]}@x.co", role="salesman", password_hash=hash_password("pw-123456"), branch_id=b.id)
    db.add_all([owner, rep])
    await db.commit()
    auth = {"Authorization": f"Bearer {create_access_token(owner.id, owner.tenant_id, owner.role)}"}
    token = base64.b64encode(CERT.encode()).decode()
    checks, fail_first = [], {"on": True}

    def zatca_api(request: httpx.Request):
        path = request.url.path
        if path.endswith("/compliance"):
            assert request.headers["OTP"] == "123456"
            csr = base64.b64decode(json.loads(request.content)["csr"]).decode()
            assert "BEGIN CERTIFICATE REQUEST" in csr
            return httpx.Response(200, json={"requestID": 1234567890123, "dispositionMessage": "ISSUED",
                                             "binarySecurityToken": token, "secret": "compliance-secret"})
        if path.endswith("/compliance/invoices"):
            body = json.loads(request.content)
            xml = base64.b64decode(body["invoice"]).decode()
            assert zx.invoice_hash(xml) == body["invoiceHash"]
            checks.append(re.search(r'name="(\d+)">(\d+)<', xml).groups())
            if fail_first["on"]:
                fail_first["on"] = False
                return httpx.Response(400, json={"validationResults": {"status": "ERROR", "warningMessages": [], "errorMessages": [
                    {"code": "BR-KSA-09", "message": "Seller address incomplete"}]}})
            return httpx.Response(200, json={"validationResults": {"status": "PASS", "warningMessages": [], "errorMessages": []}})
        if path.endswith("/production/csids"):
            assert json.loads(request.content) == {"compliance_request_id": "1234567890123"}
            return httpx.Response(200, json={"requestID": 1, "binarySecurityToken": token, "secret": "production-secret"})
        return httpx.Response(404)

    _mock(zatca_api)
    rep_auth = {"Authorization": f"Bearer {create_access_token(rep.id, rep.tenant_id, rep.role)}"}
    body = {"branch_id": str(b.id), "environment": "sandbox", "location": "Riyadh", "industry": "Wholesale"}
    assert (await http.post("/api/v1/zatca/units", json=body, headers=rep_auth)).status_code == 403
    unit = (await http.post("/api/v1/zatca/units", json=body, headers=auth)).json()
    assert unit["status"] == "draft" and unit["invoice_types"] == "1100"

    r = await http.post(f"/api/v1/zatca/units/{unit['id']}/onboard", json={"otp": "123456"}, headers=auth)
    assert r.status_code == 422 and "standard invoice" in r.json()["detail"]
    r = await http.post(f"/api/v1/zatca/units/{unit['id']}/onboard", json={}, headers=auth)  # resumes, no new OTP needed
    assert r.status_code == 200, r.text
    live = r.json()
    assert live["status"] == "active" and live["certificate_expires_at"].startswith("2029")
    assert [r["status"] for r in live["compliance_results"]] == ["PASS"] * 6
    assert len(checks) == 12 and checks[6:] == [("0100000", "388"), ("0100000", "381"), ("0100000", "383"),
                          ("0200000", "388"), ("0200000", "381"), ("0200000", "383")]
    row = await db.get(ZatcaUnit, uuid.UUID(live["id"]))
    await db.refresh(row)
    assert open_(row.production_secret) == "production-secret" and row.private_key != open_(row.private_key)

    overview = (await http.get("/api/v1/zatca", headers=rep_auth)).json()
    assert overview["seller_problems"] == [] and overview["units"][0]["status"] == "active"


async def test_missing_business_details_are_listed_before_connecting(session, http):
    db = session
    t, b, _ = await _business(db, connected=False, seller=False)
    owner = User(tenant_id=t.id, email=f"o-{uuid.uuid4().hex[:6]}@x.co", role="owner", password_hash=hash_password("pw-123456"))
    db.add(owner)
    await db.commit()
    auth = {"Authorization": f"Bearer {create_access_token(owner.id, owner.tenant_id, owner.role)}"}
    problems = (await http.get("/api/v1/zatca", headers=auth)).json()["seller_problems"]
    assert any("VAT number" in p for p in problems) and any("commercial registration" in p for p in problems)
    r = await http.post("/api/v1/zatca/units", headers=auth, json={
        "branch_id": str(b.id), "environment": "sandbox", "location": "Riyadh", "industry": "Wholesale"})
    assert r.status_code == 422