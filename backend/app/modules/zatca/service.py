"""ZATCA e-invoicing: onboarding each branch, stamping invoices, sending them.

How it fits together:

- A branch is onboarded once: a key and CSR are made here, the owner pastes
  the OTP from the Fatoora portal, and we get a compliance certificate, pass
  ZATCA's compliance checks with test documents, and receive the production
  certificate. From then on the branch is "active".
- Every tax invoice and credit note issued for an active branch is signed in
  the same transaction that issues it (so the PDF can carry the QR code right
  away), with the next invoice counter (ICV) and the previous document's hash
  (PIH). The branch row is locked while this happens, so the chain never forks.
- Sending happens in the background: standard (B2B) documents are cleared,
  simplified (B2C) ones are reported. Network trouble is retried with the
  same document; a rejection is recorded with ZATCA's reasons and can be
  fixed and sent again as a new document (new UUID and ICV, PIH = the latest
  hash), which is what ZATCA expects.
- Data problems found before signing (a customer without an address, say)
  leave a "blocked" record without using an ICV.
"""
import base64
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_box import open_, seal
from app.db.models.accounts import AccountSettings, SalesInvoice
from app.db.models.branch import Branch
from app.db.models.customer import Customer
from app.db.models.tenant import Tenant
from app.db.models.zatca import ZatcaDocument, ZatcaUnit
from app.jobs.queue import ZATCA_SUBMIT, enqueue
from app.modules.zatca import client, crypto
from app.modules.zatca import xml as zx

logger = logging.getLogger("salesman.zatca")

ENVIRONMENTS = ("sandbox", "simulation", "production")
SOLUTION_NAME = "Salesman"
SOLUTION_VERSION = "2.0"
SUBMIT_ATTEMPTS = 12          # with the queue's backoff: retries for about 1.5 hours
STAMPABLE = ("invoice", "credit_note")
ENV_LABEL = {"sandbox": "Developer sandbox", "simulation": "Simulation", "production": "Production"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tz(tenant: Tenant | None):
    try:
        return ZoneInfo(tenant.timezone) if tenant and tenant.timezone else ZoneInfo("Asia/Riyadh")
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Riyadh")


# ---- the seller and the buyer ---------------------------------------------------------------

def seller_name(s: AccountSettings, tenant: Tenant | None = None) -> str:
    en = (s.seller_name or (tenant.name if tenant else "") or "").strip()
    ar = (s.seller_name_ar or "").strip()
    return f"{ar} | {en}" if ar and en else (ar or en)


def seller_party(s: AccountSettings, tenant: Tenant | None = None) -> zx.Party:
    address = zx.Address(
        street=(s.seller_street or "").strip(), building_number=(s.seller_building_number or "").strip(),
        district=(s.seller_district or "").strip(), city=(s.seller_city or "").strip(),
        postal_code=(s.seller_postal_code or "").strip(),
    )
    return zx.Party(name=seller_name(s, tenant), address=address, vat_number=(s.seller_vat_number or "").strip() or None,
                    other_id=(s.seller_cr_number or "").strip() or None, other_id_scheme="CRN")


def seller_problems(s: AccountSettings, tenant: Tenant | None = None) -> list[str]:
    """What the business must fill in (Accounts > Settings) before e-invoicing can start."""
    probe = zx.Document(
        number="CHECK", uuid=str(uuid.uuid4()), kind="invoice", flow="simplified",
        issue_date=datetime.now().date(), issue_time="00:00:00", icv=1, pih=zx.FIRST_PIH,
        seller=seller_party(s, tenant), buyer=None,
        lines=[zx.Line("check", Decimal("1"), Decimal("1"), Decimal("0.15"), Decimal("15"))],
    )
    out = zx.validate(probe)
    if not seller_name(s, tenant):
        out.insert(0, "The business name is missing.")
    return out


def flow_for(buyer: dict | None) -> str:
    """Customers with a VAT or CR number are businesses: standard invoices. Everyone else: simplified."""
    buyer = buyer or {}
    return "standard" if (buyer.get("vat_number") or buyer.get("cr_number")) else "simplified"


def buyer_snapshot(customer: Customer) -> dict:
    """The customer as printed on an invoice (stored on SalesInvoice.buyer)."""
    return {
        "name": customer.name, "company": customer.company, "vat_number": customer.vat_number,
        "cr_number": customer.cr_number, "address": customer.address, "phone": customer.whatsapp_number,
        "street": customer.street, "building_number": customer.building_number, "district": customer.district,
        "city": customer.city, "postal_code": customer.postal_code,
    }


def buyer_party(buyer: dict) -> zx.Party:
    address = None
    if any(buyer.get(k) for k in ("street", "building_number", "district", "city", "postal_code")):
        address = zx.Address(
            street=(buyer.get("street") or "").strip(), building_number=(buyer.get("building_number") or "").strip(),
            district=(buyer.get("district") or "").strip(), city=(buyer.get("city") or "").strip(),
            postal_code=(buyer.get("postal_code") or "").strip(),
        )
    return zx.Party(
        name=(buyer.get("company") or buyer.get("name") or "Customer").strip(), address=address,
        vat_number=(buyer.get("vat_number") or "").strip() or None,
        other_id=(buyer.get("cr_number") or "").strip() or None, other_id_scheme="CRN",
    )


def _lines(inv: SalesInvoice) -> list[zx.Line]:
    return [
        zx.Line(name=str(ln.get("name") or ln.get("sku") or "Item")[:1000], quantity=Decimal(str(ln["quantity"])),
                net=Decimal(str(ln["net"])), vat=Decimal(str(ln["vat"])), vat_rate=Decimal(str(ln["vat_rate"])))
        for ln in inv.lines or []
    ]


# ---- units ----------------------------------------------------------------------------------

async def get_unit(db: AsyncSession, tenant_id: uuid.UUID, unit_id: uuid.UUID) -> ZatcaUnit:
    unit = await db.scalar(select(ZatcaUnit).where(ZatcaUnit.id == unit_id, ZatcaUnit.tenant_id == tenant_id))
    if unit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "E-invoicing device not found")
    return unit


async def unit_for_branch(db: AsyncSession, branch_id: uuid.UUID, *, lock: bool = False) -> ZatcaUnit | None:
    q = select(ZatcaUnit).where(ZatcaUnit.branch_id == branch_id)
    if lock:
        q = q.with_for_update()
    return await db.scalar(q)


async def list_units(db: AsyncSession, tenant_id: uuid.UUID) -> list[ZatcaUnit]:
    return list(await db.scalars(select(ZatcaUnit).where(ZatcaUnit.tenant_id == tenant_id)))


async def prepare_unit(
    db: AsyncSession, tenant_id: uuid.UUID, *, branch_id: uuid.UUID, environment: str, location: str,
    industry: str, invoice_types: str = "1100", common_name: str | None = None,
) -> ZatcaUnit:
    """Make the branch's key and CSR. Safe to repeat until the branch is active."""
    from app.modules.accounts import service as accounts

    if environment not in ENVIRONMENTS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown ZATCA environment")
    if invoice_types not in ("1100", "1000", "0100"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invoice types must be 1100, 1000 or 0100")
    branch = await db.scalar(select(Branch).where(Branch.id == branch_id, Branch.tenant_id == tenant_id))
    if branch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Branch not found")
    tenant = await db.get(Tenant, tenant_id)
    settings = await accounts.get_settings(db, tenant_id)
    problems = seller_problems(settings, tenant)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, " ".join(problems))
    if not location.strip() or not industry.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Location and industry are required")

    unit = await unit_for_branch(db, branch.id, lock=True)
    if unit is not None and unit.status == "active":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{branch.name} is already connected to ZATCA")

    key = crypto.new_private_key_pem()
    serial = f"1-{SOLUTION_NAME}|2-{SOLUTION_VERSION}|3-{uuid.uuid4()}"
    cn = (common_name or f"{SOLUTION_NAME}-{branch.name}").strip()[:64]
    csr = crypto.build_csr(crypto.CsrInput(
        common_name=cn, organization=(settings.seller_name or tenant.name)[:64], organization_unit=branch.name[:64],
        vat_number=settings.seller_vat_number, egs_serial=serial, invoice_types=invoice_types,
        location=location.strip()[:255], industry=industry.strip()[:120],
    ), key, environment)
    fields = dict(
        environment=environment, status="draft", common_name=cn, egs_serial=serial,
        organization_unit=branch.name[:64], invoice_types=invoice_types, location=location.strip()[:255],
        industry=industry.strip()[:120], private_key=seal(key), csr=csr, compliance_token=None,
        compliance_secret=None, compliance_request_id=None, compliance_results=[], production_token=None,
        production_secret=None, certificate=None, certificate_expires_at=None, last_error=None,
    )
    if unit is None:
        unit = ZatcaUnit(tenant_id=tenant_id, branch_id=branch.id, icv=0, last_hash=zx.FIRST_PIH, **fields)
        db.add(unit)
    else:
        for k, v in fields.items():
            setattr(unit, k, v)
    await db.commit()
    await db.refresh(unit)
    return unit


def _check_documents(unit: ZatcaUnit, seller: zx.Party, today, now_time: str) -> list[tuple[str, zx.Document]]:
    """The test documents ZATCA wants to see before it issues the production certificate."""
    flows = [f for f, flag in (("standard", unit.invoice_types[0]), ("simplified", unit.invoice_types[1])) if flag == "1"]
    buyer = zx.Party(name="Compliance check customer", vat_number="399999999800003", address=seller.address)
    out, n = [], 0
    for flow in flows:
        first_number = None
        for kind, label in (("invoice", "invoice"), ("credit_note", "credit note"), ("debit_note", "debit note")):
            n += 1
            number = f"CHK-{n:04d}"
            first_number = first_number or number
            doc = zx.Document(
                number=number, uuid=str(uuid.uuid4()), kind=kind, flow=flow, issue_date=today, issue_time=now_time,
                icv=n, pih=zx.FIRST_PIH, seller=seller, buyer=buyer if flow == "standard" else None,
                supply_date=today, payment_means_code="10",
                billing_reference=first_number if kind != "invoice" else None,
                reason="Compliance check" if kind != "invoice" else None,
                lines=[zx.Line("Compliance check item", Decimal("1"), Decimal("100.00"), Decimal("15.00"), Decimal("15"))],
            )
            out.append((f"{flow.capitalize()} {label}", doc))
    return out


async def onboard(db: AsyncSession, tenant_id: uuid.UUID, unit_id: uuid.UUID, otp: str | None) -> ZatcaUnit:
    """Compliance certificate -> compliance checks -> production certificate. Resumes where it stopped."""
    from app.modules.accounts import service as accounts

    unit = await get_unit(db, tenant_id, unit_id)
    if unit.status == "active":
        return unit
    tenant = await db.get(Tenant, tenant_id)
    settings = await accounts.get_settings(db, tenant_id)
    env = unit.environment

    def fail(message: str, http: int = status.HTTP_422_UNPROCESSABLE_ENTITY):
        unit.status, unit.last_error = "failed", message
        return HTTPException(http, message)

    try:
        # 1. compliance certificate (needs the portal's OTP)
        if not unit.compliance_token:
            if not (otp or "").strip():
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter the OTP from the Fatoora portal")
            code, data = await client.compliance_csid(env, crypto.csr_for_api(unit.csr), otp.strip())
            if code != 200 or not data.get("binarySecurityToken"):
                errors, _ = client.messages(data)
                raise fail("ZATCA refused the request: " + "; ".join(e["message"] or str(e["code"]) for e in errors)
                           if errors else f"ZATCA refused the request ({code})")
            unit.compliance_token = data["binarySecurityToken"]
            unit.compliance_secret = seal(data.get("secret"))
            unit.compliance_request_id = str(data.get("requestID"))
            await db.commit()

        # 2. compliance checks with test documents, signed with the compliance certificate
        if not unit.compliance_results or any(r["status"] == "ERROR" for r in unit.compliance_results):
            cert = crypto.certificate_from_token(unit.compliance_token)
            key, secret = open_(unit.private_key), open_(unit.compliance_secret)
            local = datetime.now(_tz(tenant))
            pih, results = zx.FIRST_PIH, []
            for label, doc in _check_documents(unit, seller_party(settings, tenant), local.date(),
                                               local.strftime("%H:%M:%S")):
                doc.pih = pih
                signed = zx.sign(doc, cert, key)
                pih = signed.invoice_hash
                code, data = await client.compliance_check(
                    env, unit.compliance_token, secret, invoice_hash=signed.invoice_hash, uuid=doc.uuid,
                    xml_b64=base64.b64encode(signed.xml.encode()).decode(),
                )
                errors, warnings = client.messages(data)
                verdict = (data.get("validationResults") or {}).get("status") or ("PASS" if code in (200, 202) else "ERROR")
                if code not in (200, 202):
                    verdict = "ERROR"
                results.append({"label": label, "status": verdict, "errors": errors, "warnings": warnings})
            unit.compliance_results = results
            failed = [r for r in results if r["status"] == "ERROR"]
            if failed:
                first = failed[0]
                detail = "; ".join(e["message"] or str(e["code"]) for e in first["errors"][:3])
                raise fail(f"ZATCA's compliance check failed on the {first['label'].lower()}: {detail}")
            await db.commit()

        # 3. production certificate
        code, data = await client.production_csid(
            env, unit.compliance_token, open_(unit.compliance_secret), unit.compliance_request_id or "",
        )
        if code != 200 or not data.get("binarySecurityToken"):
            errors, _ = client.messages(data)
            raise fail("ZATCA did not issue the production certificate: "
                       + ("; ".join(e["message"] or str(e["code"]) for e in errors) or str(code)))
        cert_b64 = crypto.certificate_from_token(data["binarySecurityToken"])
        info = crypto.certificate_info(cert_b64)
        if env != "sandbox" and not crypto.key_matches_certificate(open_(unit.private_key), info):
            raise fail("ZATCA's certificate does not match this branch's key. Start again with a new OTP.")
        unit.production_token = data["binarySecurityToken"]
        unit.production_secret = seal(data.get("secret"))
        unit.certificate = info.base64_body
        unit.certificate_expires_at = info.not_after
        unit.status, unit.last_error, unit.onboarded_at = "active", None, _now()
        await db.commit()
        await db.refresh(unit)
        return unit
    except client.ZatcaUnavailable as exc:
        unit.last_error = str(exc)
        await db.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "ZATCA can't be reached right now. Try again in a few minutes.") from exc
    except HTTPException:
        await db.commit()
        raise


async def disable_unit(db: AsyncSession, tenant_id: uuid.UUID, unit_id: uuid.UUID) -> ZatcaUnit:
    unit = await get_unit(db, tenant_id, unit_id)
    unit.status = "disabled" if unit.production_token else "draft"
    await db.commit()
    return unit


async def enable_unit(db: AsyncSession, tenant_id: uuid.UUID, unit_id: uuid.UUID) -> ZatcaUnit:
    unit = await get_unit(db, tenant_id, unit_id)
    if not unit.production_token:
        raise HTTPException(status.HTTP_409_CONFLICT, "Finish connecting this branch to ZATCA first")
    unit.status = "active"
    await db.commit()
    return unit


# ---- stamping -------------------------------------------------------------------------------

async def latest_document(db: AsyncSession, invoice_id: uuid.UUID) -> ZatcaDocument | None:
    return await db.scalar(
        select(ZatcaDocument).where(ZatcaDocument.invoice_id == invoice_id, ZatcaDocument.status != "superseded")
        .order_by(ZatcaDocument.created_at.desc()).limit(1)
    )


async def stamp(db: AsyncSession, inv: SalesInvoice) -> ZatcaDocument | None:
    """Sign a freshly issued invoice or credit note, if its branch is connected. Does not commit."""
    from app.modules.accounts import service as accounts

    if inv.kind not in STAMPABLE:
        return None
    original = None
    if inv.kind == "credit_note" and inv.original_invoice_id:
        original = await db.get(SalesInvoice, inv.original_invoice_id)
        if original is not None and original.kind not in STAMPABLE:
            return None  # credits against opening balances aren't tax documents
    unit = await unit_for_branch(db, inv.branch_id, lock=True)
    if unit is None or unit.status != "active":
        return None

    tenant = await db.get(Tenant, inv.tenant_id)
    settings = await accounts.get_settings(db, inv.tenant_id)
    flow = flow_for(inv.buyer)
    if original is not None:
        prior = await latest_document(db, original.id)
        if prior is not None:
            flow = prior.flow
    local = inv.issued_at.astimezone(_tz(tenant))
    doc = zx.Document(
        number=inv.number, uuid=str(uuid.uuid4()), kind=inv.kind, flow=flow, issue_date=inv.issue_date,
        issue_time=local.strftime("%H:%M:%S"), icv=unit.icv + 1, pih=unit.last_hash,
        seller=seller_party(settings, tenant), buyer=buyer_party(inv.buyer) if flow == "standard" else None,
        lines=_lines(inv), currency=inv.currency, supply_date=inv.issue_date,
        payment_means_code="30" if inv.customer_id else "10",
        billing_reference=original.number if original is not None else None,
        reason=inv.reason if inv.kind == "credit_note" else None,
    )
    record = ZatcaDocument(
        tenant_id=inv.tenant_id, branch_id=inv.branch_id, unit_id=unit.id, invoice_id=inv.id, flow=flow,
        kind=inv.kind, status="blocked", attempts=0, errors=[], warnings=[],
    )
    allowed = unit.invoice_types[0] == "1" if flow == "standard" else unit.invoice_types[1] == "1"
    problems = zx.validate(doc)
    if not allowed:
        problems.insert(0, f"This branch is registered with ZATCA for {'simplified' if flow == 'standard' else 'standard'} "
                           f"invoices only, but this document is {flow}.")
    if problems:
        record.errors = [{"code": None, "message": p, "category": "Before sending"} for p in problems]
        db.add(record)
        await db.flush()
        return record

    signed = zx.sign(doc, unit.certificate, open_(unit.private_key))
    unit.icv, unit.last_hash = doc.icv, signed.invoice_hash
    record.status, record.icv, record.document_uuid = "queued", doc.icv, doc.uuid
    record.invoice_hash, record.pih, record.xml, record.qr = signed.invoice_hash, doc.pih, signed.xml, signed.qr
    record.signed_at = _now()
    db.add(record)
    await db.flush()
    await enqueue(db, ZATCA_SUBMIT, {"document_id": str(record.id)}, tenant_id=inv.tenant_id,
                  dedupe_key=f"zatca:{record.id}", max_attempts=SUBMIT_ATTEMPTS, commit=False)
    return record


async def stamp_safely(db: AsyncSession, inv: SalesInvoice) -> None:
    """stamp() inside a savepoint: e-invoicing trouble never stops an invoice being issued."""
    try:
        async with db.begin_nested():
            await stamp(db, inv)
    except Exception:  # noqa: BLE001
        logger.exception("could not stamp invoice", extra={"ctx_invoice_id": str(inv.id)})


# ---- sending --------------------------------------------------------------------------------

async def submit_document(db: AsyncSession, document_id: uuid.UUID) -> str:
    """Send one queued document to ZATCA. Raises ZatcaUnavailable to be retried later."""
    doc = await db.scalar(select(ZatcaDocument).where(ZatcaDocument.id == document_id).with_for_update())
    if doc is None or doc.status != "queued":
        return "skipped"
    unit = await db.get(ZatcaUnit, doc.unit_id) if doc.unit_id else None
    if unit is None or not unit.production_token:
        doc.last_error = "This branch is no longer connected to ZATCA."
        await db.commit()
        return "no unit"

    doc.attempts += 1
    try:
        code, data = await client.submit(
            unit.environment, unit.production_token, open_(unit.production_secret), flow=doc.flow,
            invoice_hash=doc.invoice_hash, uuid=doc.document_uuid,
            xml_b64=base64.b64encode(doc.xml.encode()).decode(),
        )
    except client.ZatcaUnavailable as exc:
        doc.last_error = str(exc)
        await db.commit()
        raise

    doc.submitted_at = _now()
    errors, warnings = client.messages(data)
    doc.warnings = warnings
    zstatus = data.get("clearanceStatus") or data.get("reportingStatus")
    accepted = "cleared" if doc.flow == "standard" else "reported"

    if code in (200, 202) and zstatus in ("CLEARED", "REPORTED"):
        doc.status, doc.zatca_status, doc.errors, doc.last_error = accepted, zstatus, [], None
        if doc.flow == "standard" and data.get("clearedInvoice"):
            cleared = base64.b64decode(data["clearedInvoice"]).decode()
            doc.cleared_xml = cleared
            doc.qr = zx.qr_from_xml(cleared) or doc.qr
    elif code == 409:
        # ZATCA already has this exact document (an earlier attempt got through)
        doc.status, doc.zatca_status, doc.errors = accepted, "CLEARED" if doc.flow == "standard" else "REPORTED", []
        doc.last_error = "ZATCA already had this document from an earlier attempt."
    elif code in (401, 403):
        doc.last_error = ("ZATCA refused this branch's certificate. Reconnect the branch under "
                          "Accounts > E-invoicing, then send again.")
        unit.last_error = doc.last_error
    elif code in (400, 422) or zstatus in ("NOT_CLEARED", "NOT_REPORTED"):
        doc.status, doc.zatca_status = "rejected", zstatus or ("NOT_CLEARED" if doc.flow == "standard" else "NOT_REPORTED")
        doc.errors = errors or [{"code": str(code), "message": data.get("message") or "Rejected", "category": None}]
        doc.last_error = None
    else:
        doc.last_error = f"Unexpected answer from ZATCA ({code}): {str(data)[:300]}"
    await db.commit()
    return doc.status


async def _get_document(db: AsyncSession, tenant_id: uuid.UUID, document_id: uuid.UUID,
                        scope: uuid.UUID | None = None) -> ZatcaDocument:
    from app.core.branches import in_scope

    doc = await db.scalar(select(ZatcaDocument).where(ZatcaDocument.id == document_id, ZatcaDocument.tenant_id == tenant_id))
    if doc is None or not in_scope(scope, doc.branch_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "E-invoice not found")
    return doc


async def get_document(db: AsyncSession, tenant_id: uuid.UUID, document_id: uuid.UUID,
                       scope: uuid.UUID | None = None) -> ZatcaDocument:
    return await _get_document(db, tenant_id, document_id, scope)


async def send_again(db: AsyncSession, tenant_id: uuid.UUID, document_id: uuid.UUID,
                     scope: uuid.UUID | None = None) -> ZatcaDocument:
    """Queue a waiting document for another attempt now (same document, same hash)."""
    doc = await _get_document(db, tenant_id, document_id, scope)
    if doc.status != "queued":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only documents waiting to be sent can be sent again")
    await enqueue(db, ZATCA_SUBMIT, {"document_id": str(doc.id)}, tenant_id=tenant_id,
                  dedupe_key=f"zatca:{doc.id}:{doc.attempts}:{int(_now().timestamp())}",
                  max_attempts=SUBMIT_ATTEMPTS, commit=False)
    await db.commit()
    return doc


async def resubmit(db: AsyncSession, tenant_id: uuid.UUID, document_id: uuid.UUID,
                   scope: uuid.UUID | None = None) -> ZatcaDocument:
    """Replace a rejected or blocked document with a corrected one, using today's customer and business details."""
    doc = await _get_document(db, tenant_id, document_id, scope)
    if doc.status not in ("rejected", "blocked"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only rejected or blocked e-invoices can be corrected and sent again")
    inv = await db.scalar(select(SalesInvoice).where(SalesInvoice.id == doc.invoice_id).with_for_update())
    if inv.customer_id:
        customer = await db.get(Customer, inv.customer_id)
        if customer is not None:
            inv.buyer = {**(inv.buyer or {}), **buyer_snapshot(customer)}
    new = await stamp(db, inv)
    if new is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This branch isn't connected to ZATCA")
    doc.status, doc.replaced_by_id = "superseded", new.id
    await db.commit()
    await db.refresh(new)
    return new


async def stamp_now(db: AsyncSession, tenant_id: uuid.UUID, invoice_id: uuid.UUID,
                    scope: uuid.UUID | None = None) -> ZatcaDocument:
    """E-invoice an invoice that has none yet (e.g. stamping failed unexpectedly when it was issued)."""
    from app.modules.accounts import service as accounts

    inv = await accounts.get_invoice(db, tenant_id, invoice_id, scope)
    if await latest_document(db, inv.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This invoice already has an e-invoice")
    unit = await unit_for_branch(db, inv.branch_id)
    if unit is None or unit.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "This branch isn't connected to ZATCA")
    if unit.onboarded_at and inv.issued_at < unit.onboarded_at - timedelta(minutes=1):
        raise HTTPException(status.HTTP_409_CONFLICT, "Invoices issued before the branch was connected aren't sent to ZATCA")
    new = await stamp(db, inv)
    if new is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This document isn't a tax invoice or credit note")
    await db.commit()
    await db.refresh(new)
    return new


# ---- reading --------------------------------------------------------------------------------

async def einvoice_for_pdf(db: AsyncSession, inv: SalesInvoice) -> dict | None:
    """What the invoice PDF prints about the e-invoice (None when ZATCA doesn't apply)."""
    doc = await latest_document(db, inv.id)
    if doc is None:
        return None
    return {"flow": doc.flow, "status": doc.status, "qr": doc.qr if doc.status != "blocked" else None}


async def documents_for(db: AsyncSession, invoice_ids: list[uuid.UUID]) -> dict[uuid.UUID, ZatcaDocument]:
    """The current e-invoice of each invoice (for lists)."""
    if not invoice_ids:
        return {}
    rows = await db.scalars(
        select(ZatcaDocument).where(ZatcaDocument.invoice_id.in_(invoice_ids), ZatcaDocument.status != "superseded")
        .order_by(ZatcaDocument.created_at)
    )
    return {d.invoice_id: d for d in rows}


async def list_documents(
    db: AsyncSession, tenant_id: uuid.UUID, *, status_: str | None = None, flow: str | None = None,
    scope: uuid.UUID | None = None, limit: int = 200,
) -> list[tuple[ZatcaDocument, SalesInvoice]]:
    q = (
        select(ZatcaDocument, SalesInvoice).join(SalesInvoice, SalesInvoice.id == ZatcaDocument.invoice_id)
        .where(ZatcaDocument.tenant_id == tenant_id)
    )
    if status_ == "attention":
        q = q.where(ZatcaDocument.status.in_(("rejected", "blocked")))
    elif status_ == "waiting":
        q = q.where(ZatcaDocument.status == "queued")
    elif status_ == "done":
        q = q.where(ZatcaDocument.status.in_(("cleared", "reported")))
    elif status_:
        q = q.where(ZatcaDocument.status == status_)
    else:
        q = q.where(ZatcaDocument.status != "superseded")
    if flow:
        q = q.where(ZatcaDocument.flow == flow)
    if scope is not None:
        q = q.where(ZatcaDocument.branch_id == scope)
    rows = await db.execute(q.order_by(ZatcaDocument.created_at.desc()).limit(limit))
    return [(d, i) for d, i in rows.all()]


async def counts(db: AsyncSession, tenant_id: uuid.UUID, scope: uuid.UUID | None = None) -> dict[str, int]:
    q = select(ZatcaDocument.status, func.count()).where(ZatcaDocument.tenant_id == tenant_id)
    if scope is not None:
        q = q.where(ZatcaDocument.branch_id == scope)
    rows = dict((await db.execute(q.group_by(ZatcaDocument.status))).all())
    return {
        "cleared": rows.get("cleared", 0), "reported": rows.get("reported", 0), "waiting": rows.get("queued", 0),
        "rejected": rows.get("rejected", 0), "blocked": rows.get("blocked", 0),
    }