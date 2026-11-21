"""Data protection (Saudi PDPL and similar laws): export, erasure, retention.

- export(): everything a business has in Salesman, as a ZIP of JSON files
  (one per kind of record), for the business's own records or to move to
  another system. Secrets are left out: password hashes, WhatsApp and ERP
  keys, API keys.
- erase_customer(): a customer asks to be forgotten. Their name, number,
  company, address and identifiers are removed from the customer record,
  their orders, their WhatsApp conversations and messages; the words the AI
  learned from them and their reorder messages are deleted. Issued tax
  invoices and credit notes are NOT changed: VAT law requires keeping them
  as issued. A customer who still owes or is owed money can't be erased
  until the balance is settled.
- retention: with `message_retention_days` set, WhatsApp message text older
  than that is deleted every hour (orders and invoices are kept).

Every export, erasure and retention run is recorded in data_requests (who,
when, what was done -- no personal data).
"""
import io
import json
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import CustomerPayment, PaymentAllocation, SalesInvoice
from app.db.models.agent_settings import AgentSettings
from app.db.models.branch import Branch
from app.db.models.conversation import Conversation
from app.db.models.customer import Customer
from app.db.models.data_request import DataRequest
from app.db.models.deals import CustomerPrice, Promotion
from app.db.models.escalation import Escalation
from app.db.models.message import Message
from app.db.models.order import Order
from app.db.models.order_item import OrderItem
from app.db.models.product import Product
from app.db.models.product_alias import ProductAlias
from app.db.models.product_price import ProductPrice
from app.db.models.reorder import ReorderNudge
from app.db.models.tenant import Tenant
from app.db.models.user import User

ERASED = "Erased customer"
# columns never exported
SECRET_COLUMNS = {"password_hash", "whatsapp_access_token", "secret", "api_key", "key_hash", "totp_secret"}


def _jsonable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _rows(objs) -> list[dict]:
    out = []
    for obj in objs:
        attrs = sa_inspect(obj).mapper.column_attrs
        out.append({a.columns[0].name: _jsonable(getattr(obj, a.key)) for a in attrs
                    if a.columns[0].name not in SECRET_COLUMNS})
    return out


async def _record(db: AsyncSession, tenant_id: uuid.UUID, kind: str, *, actor_id=None, subject_id=None,
                  detail: dict | None = None) -> DataRequest:
    req = DataRequest(tenant_id=tenant_id, kind=kind, subject_id=subject_id, requested_by=actor_id, detail=detail or {})
    db.add(req)
    await db.commit()
    return req


async def export(db: AsyncSession, tenant_id: uuid.UUID, *, actor_id: uuid.UUID | None = None) -> bytes:
    tenant = await db.get(Tenant, tenant_id)
    order_ids = select(Order.id).where(Order.tenant_id == tenant_id)
    conv_ids = select(Conversation.id).where(Conversation.tenant_id == tenant_id)
    tables = {
        "business.json": [tenant],
        "branches.json": await db.scalars(select(Branch).where(Branch.tenant_id == tenant_id)),
        "users.json": await db.scalars(select(User).where(User.tenant_id == tenant_id)),
        "customers.json": await db.scalars(select(Customer).where(Customer.tenant_id == tenant_id)),
        "products.json": await db.scalars(select(Product).where(Product.tenant_id == tenant_id)),
        "prices.json": await db.scalars(select(ProductPrice).where(ProductPrice.tenant_id == tenant_id)),
        "customer_prices.json": await db.scalars(select(CustomerPrice).where(CustomerPrice.tenant_id == tenant_id)),
        "promotions.json": await db.scalars(select(Promotion).where(Promotion.tenant_id == tenant_id)),
        "orders.json": await db.scalars(select(Order).where(Order.tenant_id == tenant_id)),
        "order_items.json": await db.scalars(select(OrderItem).where(OrderItem.order_id.in_(order_ids))),
        "escalations.json": await db.scalars(select(Escalation).where(Escalation.tenant_id == tenant_id)),
        "invoices.json": await db.scalars(select(SalesInvoice).where(SalesInvoice.tenant_id == tenant_id)),
        "payments.json": await db.scalars(select(CustomerPayment).where(CustomerPayment.tenant_id == tenant_id)),
        "payment_allocations.json": await db.scalars(select(PaymentAllocation).where(
            PaymentAllocation.payment_id.in_(select(CustomerPayment.id).where(CustomerPayment.tenant_id == tenant_id)))),
        "conversations.json": await db.scalars(select(Conversation).where(Conversation.tenant_id == tenant_id)),
        "messages.json": await db.scalars(select(Message).where(Message.conversation_id.in_(conv_ids))),
        "product_aliases.json": await db.scalars(select(ProductAlias).where(ProductAlias.tenant_id == tenant_id)),
    }
    buf = io.BytesIO()
    counts = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, objs in tables.items():
            rows = _rows(list(objs))
            counts[name.removesuffix(".json")] = len(rows)
            zf.writestr(name, json.dumps(rows, ensure_ascii=False, indent=1))
        zf.writestr("README.txt", (
            f"Salesman data export for {tenant.name if tenant else tenant_id}\n"
            f"Created {datetime.now(timezone.utc).isoformat()}\n\n"
            "One JSON file per kind of record. Ids link the files together (order_items.order_id -> orders.id).\n"
            "Passwords, WhatsApp tokens and ERP keys are not included.\n"
        ))
    await _record(db, tenant_id, "export", actor_id=actor_id, detail={"records": counts})
    return buf.getvalue()


async def erase_customer(db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID, *,
                         actor_id: uuid.UUID | None = None) -> dict:
    from app.modules.accounts import service as accounts

    c = await db.scalar(select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id))
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    if c.name == ERASED and not c.whatsapp_number:
        raise HTTPException(status.HTTP_409_CONFLICT, "This customer's data was already erased")
    balance = (await accounts._balances(db, tenant_id, [c.id])).get(c.id, Decimal("0"))
    if balance != 0:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"The customer's balance is {balance:.2f}. Settle it (payment or credit note) before erasing.")
    digits = "".join(ch for ch in (c.whatsapp_number or "") if ch.isdigit())

    # conversations: by the customer's number
    convs = []
    if digits:
        convs = list(await db.scalars(select(Conversation).where(
            Conversation.tenant_id == tenant_id,
            func.regexp_replace(Conversation.customer_number, "[^0-9]", "", "g") == digits,
        )))
    conv_ids = [cv.id for cv in convs]
    messages = 0
    if conv_ids:
        messages = (await db.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))).rowcount or 0
        for cv in convs:
            cv.customer_number = f"erased-{cv.id.hex[:12]}"
            cv.customer_name = None

    order_filter = or_(Order.customer_id == c.id,
                       func.regexp_replace(Order.whatsapp_number, "[^0-9]", "", "g") == digits) if digits \
        else Order.customer_id == c.id
    orders = (await db.execute(update(Order).where(Order.tenant_id == tenant_id, order_filter).values(
        customer_name=ERASED, customer_company=None, whatsapp_number=None,
    ))).rowcount or 0
    await db.execute(update(Escalation).where(Escalation.tenant_id == tenant_id, Escalation.order_id.in_(
        select(Order.id).where(Order.customer_id == c.id))).values(customer_name=ERASED, whatsapp_number=None))
    aliases = (await db.execute(delete(ProductAlias).where(ProductAlias.customer_id == c.id))).rowcount or 0
    await db.execute(delete(ReorderNudge).where(ReorderNudge.customer_id == c.id))

    c.name, c.company, c.whatsapp_number, c.address = ERASED, None, None, None
    c.vat_number = c.cr_number = c.street = c.building_number = c.district = c.city = c.postal_code = None
    c.is_active = False
    invoices = await db.scalar(select(func.count()).select_from(SalesInvoice).where(SalesInvoice.customer_id == c.id))
    await db.commit()
    detail = {"orders": orders, "messages_deleted": messages, "conversations": len(convs), "aliases_deleted": aliases,
              "invoices_kept": invoices or 0}
    await _record(db, tenant_id, "erase_customer", actor_id=actor_id, subject_id=c.id, detail=detail)
    return detail


async def apply_retention(db: AsyncSession, tenant_id: uuid.UUID, *, now: datetime | None = None) -> int:
    days = await db.scalar(select(AgentSettings.message_retention_days).where(AgentSettings.tenant_id == tenant_id))
    if not days:
        return 0
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    deleted = (await db.execute(delete(Message).where(
        Message.tenant_id == tenant_id, Message.created_at < cutoff,
    ))).rowcount or 0
    await db.commit()
    if deleted:
        await _record(db, tenant_id, "retention", detail={"messages_deleted": deleted, "older_than_days": days})
    return deleted


async def apply_retention_all(db: AsyncSession) -> int:
    total = 0
    for tid in list(await db.scalars(select(AgentSettings.tenant_id).where(AgentSettings.message_retention_days.is_not(None)))):
        try:
            total += await apply_retention(db, tid)
        except Exception:  # noqa: BLE001 -- one business must not stop the others
            await db.rollback()
    return total


async def list_requests(db: AsyncSession, tenant_id: uuid.UUID, limit: int = 100) -> list[dict]:
    rows = (await db.execute(
        select(DataRequest, User.email).outerjoin(User, User.id == DataRequest.requested_by)
        .where(DataRequest.tenant_id == tenant_id).order_by(DataRequest.created_at.desc()).limit(limit)
    )).all()
    return [{"id": r.id, "kind": r.kind, "subject_id": r.subject_id, "requested_by": email, "detail": r.detail,
             "created_at": r.created_at} for r, email in rows]
