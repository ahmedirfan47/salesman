"""Customer accounts: invoices, payments, credit notes, balances and credit control.

The rules, in one place:

- An order gets one tax invoice, issued automatically when the order is
  delivered (or when it is confirmed, if the business prefers). Walk-in
  orders are invoiced too, but only orders for a known customer go on an
  account.
- Invoices are never edited, voided or deleted. A mistake or a return is
  corrected with a credit note against the invoice.
- A payment pays the invoice it names first, then the customer's oldest open
  invoices. Whatever is left stays on account and pays the next invoice.
- Every invoice, credit note, opening balance, payment and payment reversal
  writes one line to the customer's ledger (AccountEntry). The balance is the
  sum of that ledger; statements are read straight from it.
- New orders are held for approval when the customer is on hold, has an
  invoice overdue past the grace period, or would go over their credit limit.
- Once a branch is connected to ZATCA, each invoice and credit note is signed
  as an e-invoice in the same transaction that issues it (app.modules.zatca).
"""
import logging
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.branches import in_scope
from app.db.models.accounts import (
    AccountEntry, AccountSettings, CustomerPayment, DocumentCounter, PaymentAllocation, SalesInvoice,
)
from app.db.models.customer import Customer
from app.db.models.order import Order
from app.db.models.tenant import Tenant
from app.modules.zatca import service as zatca

logger = logging.getLogger("salesman.accounts")

CENT = Decimal("0.01")
ZERO = Decimal("0")
PAYMENT_METHODS = ("cash", "bank_transfer", "cheque", "card", "other")
# orders that can be invoiced
LIVE_ORDER_STATUSES = ("confirmed", "preparing", "dispatched", "delivered", "completed")
# orders still on their way to the customer: until they are invoiced they count towards
# credit exposure. Delivered orders are invoiced on delivery, so a delivered order with
# no invoice is history from before accounts were switched on and is not counted.
IN_FLIGHT_STATUSES = ("confirmed", "preparing", "dispatched")
_PREFIX = {"invoice": "INV", "credit_note": "CN", "opening_balance": "OB", "payment": "RCPT"}
AGING_BUCKETS = ("current", "days_1_30", "days_31_60", "days_61_90", "days_90_plus")


def money(value) -> Decimal:
    return Decimal(str(value if value is not None else 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def tenant_today(tenant: Tenant | None) -> date:
    """Today's date where the business is (tenants.timezone, e.g. Asia/Riyadh)."""
    try:
        tz = ZoneInfo(tenant.timezone) if tenant and tenant.timezone else timezone.utc
    except ZoneInfoNotFoundError:
        tz = timezone.utc
    return datetime.now(tz).date()


async def _today(db: AsyncSession, tenant_id: uuid.UUID) -> date:
    return tenant_today(await db.get(Tenant, tenant_id))


# ---- settings -------------------------------------------------------------------------------

async def get_settings(db: AsyncSession, tenant_id: uuid.UUID) -> AccountSettings:
    """The business's account settings, created with sensible defaults on first use."""
    row = await db.scalar(select(AccountSettings).where(AccountSettings.tenant_id == tenant_id))
    if row is None:
        tenant = await db.get(Tenant, tenant_id)
        row = AccountSettings(
            tenant_id=tenant_id, currency="SAR", vat_rate=Decimal("15.00"), prices_include_vat=False,
            invoice_on="delivered", default_payment_terms_days=30, default_credit_limit=None,
            hold_over_limit=True, hold_when_overdue=True, overdue_grace_days=0,
            seller_name=tenant.name if tenant else None,
        )
        db.add(row)
        await db.flush()
    return row


async def update_settings(db: AsyncSession, tenant_id: uuid.UUID, data: dict) -> AccountSettings:
    row = await get_settings(db, tenant_id)
    if "invoice_on" in data and data["invoice_on"] not in (None, "delivered", "confirmed"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invoices are issued on 'confirmed' or 'delivered'")
    for key, value in data.items():
        if key in ("default_credit_limit",):
            setattr(row, key, value)  # None clears the default limit
        elif value is not None:
            setattr(row, key, value.upper() if key == "currency" else value)
    await db.commit()
    await db.refresh(row)
    return row


def terms_for(customer: Customer | None, settings: AccountSettings) -> int:
    if customer is not None and customer.payment_terms_days is not None:
        return customer.payment_terms_days
    return settings.default_payment_terms_days


def limit_for(customer: Customer | None, settings: AccountSettings) -> Decimal | None:
    if customer is not None and customer.credit_limit is not None:
        return money(customer.credit_limit)
    return money(settings.default_credit_limit) if settings.default_credit_limit is not None else None


# ---- numbering ------------------------------------------------------------------------------

async def next_number(db: AsyncSession, tenant_id: uuid.UUID, kind: str) -> str:
    """Gap-free per-business numbering: INV-000001, CN-000001, OB-000001, RCPT-000001.

    The counter row is locked until the transaction commits, so two documents
    issued at once can never share a number (and a rolled-back document frees
    its number again).
    """
    await db.execute(
        insert(DocumentCounter).values(tenant_id=tenant_id, kind=kind, last_value=0)
        .on_conflict_do_nothing(index_elements=["tenant_id", "kind"])
    )
    counter = await db.scalar(
        select(DocumentCounter)
        .where(DocumentCounter.tenant_id == tenant_id, DocumentCounter.kind == kind)
        .with_for_update()
    )
    counter.last_value += 1
    return f"{_PREFIX[kind]}-{counter.last_value:06d}"


# ---- VAT ------------------------------------------------------------------------------------

def price_lines(items: list[dict], vat_rate: Decimal, prices_include_vat: bool) -> tuple[list[dict], Decimal, Decimal, Decimal]:
    """Turn [{sku, name, quantity, unit_price}] into invoice lines with VAT.

    VAT is worked out per line and rounded to the halala, then summed.
    Returns (lines, subtotal excl. VAT, VAT, total incl. VAT).
    """
    rate = Decimal(str(vat_rate))
    lines, subtotal, vat_total = [], ZERO, ZERO
    for item in items:
        qty = Decimal(str(item["quantity"]))
        price = Decimal(str(item["unit_price"]))
        if prices_include_vat:
            gross = money(price * qty)
            net = money(gross / (1 + rate / 100))
            vat = gross - net
            unit_net = (price / (1 + rate / 100)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        else:
            net = money(price * qty)
            vat = money(net * rate / 100)
            unit_net = price
        lines.append({
            "sku": item.get("sku"),
            "name": item.get("name") or item.get("sku") or "Item",
            "quantity": str(qty.normalize()) if qty == qty.to_integral() else str(qty),
            "unit_price": str(unit_net),
            "net": str(net),
            "vat_rate": str(rate),
            "vat": str(vat),
            "total": str(net + vat),
        })
        subtotal += net
        vat_total += vat
    return lines, money(subtotal), money(vat_total), money(subtotal + vat_total)


def with_vat(amount: Decimal, settings: AccountSettings) -> Decimal:
    """An order total (priced from the price list) as it will be invoiced."""
    amount = money(amount)
    if settings.prices_include_vat:
        return amount
    return money(amount * (1 + Decimal(str(settings.vat_rate)) / 100))


def _seller(settings: AccountSettings) -> dict:
    return {
        "name": settings.seller_name, "name_ar": settings.seller_name_ar,
        "vat_number": settings.seller_vat_number, "cr_number": settings.seller_cr_number,
        "address": settings.seller_address, "street": settings.seller_street,
        "building_number": settings.seller_building_number, "district": settings.seller_district,
        "city": settings.seller_city, "postal_code": settings.seller_postal_code,
    }


def _buyer(customer: Customer | None, order: Order | None) -> dict:
    if customer is not None:
        return zatca.buyer_snapshot(customer)
    return {
        "name": (order.customer_name if order else None) or "Walk-in customer",
        "company": order.customer_company if order else None,
        "vat_number": None, "address": None, "phone": order.whatsapp_number if order else None,
    }


def _refresh_status(inv: SalesInvoice) -> None:
    if inv.kind == "credit_note":
        inv.status = "issued"
    elif inv.balance_due <= 0:
        inv.status = "paid"
    elif money(inv.amount_paid) + money(inv.amount_credited) > 0:
        inv.status = "partially_paid"
    else:
        inv.status = "open"


def _entry(inv_or_pay, kind: str, description: str, *, debit=ZERO, credit=ZERO, entry_date: date) -> AccountEntry:
    is_invoice = isinstance(inv_or_pay, SalesInvoice)
    return AccountEntry(
        tenant_id=inv_or_pay.tenant_id, branch_id=inv_or_pay.branch_id, customer_id=inv_or_pay.customer_id,
        entry_date=entry_date, kind=kind, document_number=inv_or_pay.number,
        invoice_id=inv_or_pay.id if is_invoice else None,
        payment_id=None if is_invoice else inv_or_pay.id,
        description=description[:255], debit=money(debit), credit=money(credit),
    )


# ---- lookups --------------------------------------------------------------------------------

async def get_customer(db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID,
                       scope: uuid.UUID | None = None, *, lock: bool = False) -> Customer:
    q = select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id)
    if lock:
        q = q.with_for_update()
    c = await db.scalar(q)
    if c is None or not in_scope(scope, c.branch_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    return c


async def get_invoice(db: AsyncSession, tenant_id: uuid.UUID, invoice_id: uuid.UUID,
                      scope: uuid.UUID | None = None) -> SalesInvoice:
    inv = await db.scalar(select(SalesInvoice).where(SalesInvoice.id == invoice_id, SalesInvoice.tenant_id == tenant_id))
    if inv is None or not in_scope(scope, inv.branch_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    return inv


async def invoice_for_order(db: AsyncSession, order_id: uuid.UUID) -> SalesInvoice | None:
    return await db.scalar(
        select(SalesInvoice).where(SalesInvoice.order_id == order_id, SalesInvoice.kind == "invoice")
    )


async def find_invoice_by_number(db: AsyncSession, tenant_id: uuid.UUID, number: str) -> SalesInvoice | None:
    return await db.scalar(
        select(SalesInvoice).where(SalesInvoice.tenant_id == tenant_id, func.upper(SalesInvoice.number) == number.strip().upper())
    )


# ---- invoices -------------------------------------------------------------------------------

async def issue_invoice_for_order(
    db: AsyncSession, order: Order, *, actor_id: uuid.UUID | None = None, commit: bool = True,
) -> SalesInvoice:
    """Issue the order's tax invoice (once). Returns the existing one if already issued."""
    existing = await invoice_for_order(db, order.id)
    if existing is not None:
        return existing
    if order.status not in LIVE_ORDER_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, f"An order that is '{order.status.replace('_', ' ')}' can't be invoiced")
    if not order.items:
        raise HTTPException(status.HTTP_409_CONFLICT, "This order has no items to invoice")

    settings = await get_settings(db, order.tenant_id)
    customer = None
    if order.customer_id:
        customer = await db.get(Customer, order.customer_id)
    today = await _today(db, order.tenant_id)
    lines, subtotal, vat, total = price_lines(
        [{"sku": i.sku, "name": i.product_name, "quantity": i.quantity, "unit_price": i.unit_price} for i in order.items],
        settings.vat_rate, settings.prices_include_vat,
    )
    inv = SalesInvoice(
        tenant_id=order.tenant_id, branch_id=order.branch_id, customer_id=customer.id if customer else None,
        order_id=order.id, kind="invoice", number=await next_number(db, order.tenant_id, "invoice"),
        issue_date=today, issued_at=datetime.now(timezone.utc),
        due_date=today + timedelta(days=terms_for(customer, settings)),
        currency=order.currency or settings.currency, lines=lines, subtotal=subtotal, vat_amount=vat, total=total,
        amount_paid=ZERO, amount_credited=ZERO, status="open",
        seller=_seller(settings), buyer=_buyer(customer, order), created_by=actor_id,
    )
    db.add(inv)
    await db.flush()
    if customer is not None:
        db.add(_entry(inv, "invoice", f"Invoice for order {order.order_number}", debit=total, entry_date=today))
        await db.flush()
        await apply_unallocated(db, order.tenant_id, customer.id)
    await zatca.stamp_safely(db, inv)
    if commit:
        await db.commit()
        await db.refresh(inv)
    return inv


async def after_order_event(db: AsyncSession, order: Order, event: str, *, actor_id: uuid.UUID | None = None) -> None:
    """Called by the orders module after an order is confirmed, delivered or cancelled.

    Issues the invoice when the business's chosen moment arrives (delivery
    always issues one if it hasn't been yet), and credits it in full if an
    invoiced order is cancelled. Never breaks the order flow: a failure here
    is logged and the invoice can be issued again from the dashboard.
    """
    try:
        if event == "cancelled":
            inv = await invoice_for_order(db, order.id)
            if inv is not None and money(inv.total) - money(inv.amount_credited) > 0:
                await issue_credit_note(db, order.tenant_id, inv.id, amount=None,
                                        reason=f"Order {order.order_number} cancelled", actor_id=actor_id)
            return
        settings = await get_settings(db, order.tenant_id)
        if event == "delivered" or (event == "confirmed" and settings.invoice_on == "confirmed"):
            await issue_invoice_for_order(db, order, actor_id=actor_id)
        else:
            await db.commit()  # persist settings created on first use
    except Exception:  # noqa: BLE001
        logger.exception("could not invoice order", extra={"ctx_order_id": str(order.id), "ctx_event": event})
        await db.rollback()


async def add_opening_balance(
    db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID, *, amount: Decimal, as_of: date | None,
    due_date: date | None, note: str | None, actor_id: uuid.UUID | None, scope: uuid.UUID | None = None,
) -> SalesInvoice:
    """What a customer already owed before the business moved to Salesman."""
    amount = money(amount)
    if amount <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "An opening balance must be more than zero. Record money the customer is owed as a payment.")
    customer = await get_customer(db, tenant_id, customer_id, scope, lock=True)
    settings = await get_settings(db, tenant_id)
    as_of = as_of or await _today(db, tenant_id)
    inv = SalesInvoice(
        tenant_id=tenant_id, branch_id=customer.branch_id, customer_id=customer.id, order_id=None,
        kind="opening_balance", number=await next_number(db, tenant_id, "opening_balance"),
        issue_date=as_of, issued_at=datetime.now(timezone.utc), due_date=due_date or as_of,
        currency=settings.currency, lines=[], subtotal=amount, vat_amount=ZERO, total=amount,
        amount_paid=ZERO, amount_credited=ZERO, status="open",
        seller=_seller(settings), buyer=_buyer(customer, None), notes=note, created_by=actor_id,
    )
    db.add(inv)
    await db.flush()
    db.add(_entry(inv, "opening_balance", note or "Opening balance", debit=amount, entry_date=as_of))
    await db.flush()
    await apply_unallocated(db, tenant_id, customer.id)
    await db.commit()
    await db.refresh(inv)
    return inv


async def issue_credit_note(
    db: AsyncSession, tenant_id: uuid.UUID, invoice_id: uuid.UUID, *, amount: Decimal | None, reason: str,
    actor_id: uuid.UUID | None = None, scope: uuid.UUID | None = None,
) -> SalesInvoice:
    """Credit an invoice in full (amount=None) or in part (amount incl. VAT).

    The credit first reduces what is still owed on that invoice. If the
    invoice was already paid, the payment it no longer needs is freed and
    pays the customer's other open invoices (or stays on account).
    """
    inv = await get_invoice(db, tenant_id, invoice_id, scope)
    inv = await db.scalar(select(SalesInvoice).where(SalesInvoice.id == inv.id).with_for_update())
    if inv.kind == "credit_note":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A credit note can't be credited")
    creditable = money(inv.total) - money(inv.amount_credited)
    if creditable <= 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "This invoice has already been credited in full")
    full = amount is None
    amount = creditable if full else money(amount)
    if amount <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The credit amount must be more than zero")
    if amount > creditable:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"At most {inv.currency} {creditable:,.2f} can still be credited on {inv.number}")

    total = money(inv.total)
    if full and money(inv.amount_credited) == 0 and inv.lines:
        lines, subtotal, vat = inv.lines, money(inv.subtotal), money(inv.vat_amount)
    else:
        vat = money(amount * money(inv.vat_amount) / total) if total > 0 else ZERO
        subtotal = amount - vat
        rate = (money(inv.vat_amount) / money(inv.subtotal) * 100).quantize(CENT) if money(inv.subtotal) > 0 else ZERO
        lines = [{
            "sku": None, "name": f"Credit against {inv.number}: {reason}"[:200], "quantity": "1",
            "unit_price": str(subtotal), "net": str(subtotal), "vat_rate": str(rate), "vat": str(vat), "total": str(amount),
        }]

    today = await _today(db, tenant_id)
    note = SalesInvoice(
        tenant_id=tenant_id, branch_id=inv.branch_id, customer_id=inv.customer_id, order_id=inv.order_id,
        kind="credit_note", number=await next_number(db, tenant_id, "credit_note"), original_invoice_id=inv.id,
        issue_date=today, issued_at=datetime.now(timezone.utc), due_date=today, currency=inv.currency,
        lines=lines, subtotal=subtotal, vat_amount=vat, total=amount, amount_paid=ZERO, amount_credited=ZERO,
        status="issued", seller=inv.seller, buyer=inv.buyer, reason=reason[:255], created_by=actor_id,
    )
    db.add(note)
    await db.flush()

    owed_before = inv.balance_due
    inv.amount_credited = money(inv.amount_credited) + amount
    # credit beyond what was still owed frees payments already allocated to this invoice
    excess = amount - owed_before
    if excess > 0:
        await _release_allocations(db, inv, excess)
    _refresh_status(inv)

    if inv.customer_id is not None:
        db.add(_entry(note, "credit_note", f"Credit note against {inv.number}: {reason}", credit=amount, entry_date=today))
        await db.flush()
        await apply_unallocated(db, tenant_id, inv.customer_id)
    await zatca.stamp_safely(db, note)
    await db.commit()
    await db.refresh(note)
    return note


async def _release_allocations(db: AsyncSession, inv: SalesInvoice, amount: Decimal) -> None:
    """Take up to `amount` of payments off an invoice (newest first) and put it back on account."""
    allocations = list(await db.scalars(
        select(PaymentAllocation).where(PaymentAllocation.invoice_id == inv.id)
        .order_by(PaymentAllocation.created_at.desc()).with_for_update()
    ))
    for alloc in allocations:
        if amount <= 0:
            break
        take = min(money(alloc.amount), amount)
        payment = await db.get(CustomerPayment, alloc.payment_id)
        payment.unallocated = money(payment.unallocated) + take
        inv.amount_paid = money(inv.amount_paid) - take
        alloc.amount = money(alloc.amount) - take
        if alloc.amount <= 0:
            await db.delete(alloc)
        amount -= take
    await db.flush()


# ---- payments -------------------------------------------------------------------------------

async def _allocate(db: AsyncSession, payment: CustomerPayment, inv: SalesInvoice, amount: Decimal) -> Decimal:
    amount = min(money(amount), money(payment.unallocated), inv.balance_due)
    if amount <= 0:
        return ZERO
    db.add(PaymentAllocation(tenant_id=payment.tenant_id, payment_id=payment.id, invoice_id=inv.id, amount=amount))
    payment.unallocated = money(payment.unallocated) - amount
    inv.amount_paid = money(inv.amount_paid) + amount
    _refresh_status(inv)
    return amount


async def _open_invoices(db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID, *, lock: bool = False) -> list[SalesInvoice]:
    q = (
        select(SalesInvoice)
        .where(
            SalesInvoice.tenant_id == tenant_id, SalesInvoice.customer_id == customer_id,
            SalesInvoice.kind != "credit_note", SalesInvoice.status.in_(("open", "partially_paid")),
        )
        .order_by(SalesInvoice.due_date, SalesInvoice.issue_date, SalesInvoice.number)
    )
    if lock:
        q = q.with_for_update()
    return list(await db.scalars(q))


async def apply_unallocated(db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> None:
    """Use money on account to pay the customer's oldest open invoices."""
    payments = list(await db.scalars(
        select(CustomerPayment)
        .where(
            CustomerPayment.tenant_id == tenant_id, CustomerPayment.customer_id == customer_id,
            CustomerPayment.voided_at.is_(None), CustomerPayment.unallocated > 0,
        )
        .order_by(CustomerPayment.paid_on, CustomerPayment.created_at)
        .with_for_update()
    ))
    if not payments:
        return
    invoices = await _open_invoices(db, tenant_id, customer_id, lock=True)
    for payment in payments:
        for inv in invoices:
            if money(payment.unallocated) <= 0:
                break
            if inv.balance_due > 0:
                await _allocate(db, payment, inv, inv.balance_due)
    await db.flush()


async def record_payment(
    db: AsyncSession, tenant_id: uuid.UUID, *, customer_id: uuid.UUID | None, invoice_id: uuid.UUID | None,
    amount: Decimal, method: str, reference: str | None, paid_on: date | None, notes: str | None,
    actor_id: uuid.UUID | None, scope: uuid.UUID | None = None,
) -> CustomerPayment:
    amount = money(amount)
    if amount <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The amount must be more than zero")
    if method not in PAYMENT_METHODS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Payment method must be one of: {', '.join(PAYMENT_METHODS)}")
    if customer_id is None and invoice_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose a customer or an invoice")

    inv = await get_invoice(db, tenant_id, invoice_id, scope) if invoice_id else None
    if inv is not None:
        if inv.kind == "credit_note":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A payment can't be recorded against a credit note")
        if customer_id is not None and inv.customer_id != customer_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That invoice belongs to another customer")
        customer_id = inv.customer_id
        if customer_id is None and amount > inv.balance_due:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"This walk-in invoice only has {inv.currency} {inv.balance_due:,.2f} left to pay")
    customer = await get_customer(db, tenant_id, customer_id, scope, lock=True) if customer_id else None

    settings = await get_settings(db, tenant_id)
    today = await _today(db, tenant_id)
    paid_on = paid_on or today
    if paid_on > today:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A payment can't be dated in the future")
    payment = CustomerPayment(
        tenant_id=tenant_id, branch_id=customer.branch_id if customer else inv.branch_id,
        customer_id=customer.id if customer else None, number=await next_number(db, tenant_id, "payment"),
        amount=amount, currency=inv.currency if inv else settings.currency, method=method,
        reference=(reference or None), paid_on=paid_on, notes=notes, unallocated=amount, created_by=actor_id,
    )
    db.add(payment)
    await db.flush()
    if customer is not None:
        label = method.replace("_", " ")
        db.add(_entry(payment, "payment", f"Payment received ({label}{f', ref {reference}' if reference else ''})",
                      credit=amount, entry_date=paid_on))
    if inv is not None:
        locked = await db.scalar(select(SalesInvoice).where(SalesInvoice.id == inv.id).with_for_update())
        await _allocate(db, payment, locked, amount)
    if customer is not None:
        await db.flush()
        await apply_unallocated(db, tenant_id, customer.id)
    await db.commit()
    await db.refresh(payment)
    return payment


async def void_payment(
    db: AsyncSession, tenant_id: uuid.UUID, payment_id: uuid.UUID, *, reason: str,
    actor_id: uuid.UUID | None = None, scope: uuid.UUID | None = None,
) -> CustomerPayment:
    """Reverse a payment recorded by mistake (e.g. a bounced cheque). The invoices it paid reopen."""
    payment = await db.scalar(
        select(CustomerPayment).where(CustomerPayment.id == payment_id, CustomerPayment.tenant_id == tenant_id)
        .with_for_update()
    )
    if payment is None or not in_scope(scope, payment.branch_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    if payment.voided_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This payment has already been reversed")
    allocations = list(await db.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id)))
    for alloc in allocations:
        inv = await db.scalar(select(SalesInvoice).where(SalesInvoice.id == alloc.invoice_id).with_for_update())
        inv.amount_paid = money(inv.amount_paid) - money(alloc.amount)
        _refresh_status(inv)
        await db.delete(alloc)
    payment.voided_at = datetime.now(timezone.utc)
    payment.void_reason = reason[:255]
    payment.unallocated = ZERO
    if payment.customer_id is not None:
        db.add(_entry(payment, "payment_void", f"Payment {payment.number} reversed: {reason}",
                      debit=payment.amount, entry_date=await _today(db, tenant_id)))
        await db.flush()
        await apply_unallocated(db, tenant_id, payment.customer_id)
    await db.commit()
    await db.refresh(payment)
    return payment


# ---- balances, aging and credit control -------------------------------------------------------

def aging_of(invoices: list[SalesInvoice], today: date) -> dict[str, Decimal]:
    buckets = {b: ZERO for b in AGING_BUCKETS}
    for inv in invoices:
        due = inv.balance_due
        if due <= 0:
            continue
        late = (today - inv.due_date).days
        if late <= 0:
            buckets["current"] += due
        elif late <= 30:
            buckets["days_1_30"] += due
        elif late <= 60:
            buckets["days_31_60"] += due
        elif late <= 90:
            buckets["days_61_90"] += due
        else:
            buckets["days_90_plus"] += due
    return buckets


async def _balances(db: AsyncSession, tenant_id: uuid.UUID, customer_ids: list[uuid.UUID] | None = None) -> dict:
    q = (
        select(AccountEntry.customer_id, func.coalesce(func.sum(AccountEntry.debit - AccountEntry.credit), 0))
        .where(AccountEntry.tenant_id == tenant_id)
        .group_by(AccountEntry.customer_id)
    )
    if customer_ids is not None:
        q = q.where(AccountEntry.customer_id.in_(customer_ids))
    return {cid: money(total) for cid, total in await db.execute(q)}


async def _uninvoiced(db: AsyncSession, tenant_id: uuid.UUID, customer_ids: list[uuid.UUID] | None = None) -> dict:
    """Order totals (price-list amounts) for orders on their way that have no invoice yet."""
    invoiced = select(SalesInvoice.order_id).where(SalesInvoice.kind == "invoice", SalesInvoice.order_id.is_not(None))
    q = (
        select(Order.customer_id, func.coalesce(func.sum(Order.total_amount), 0))
        .where(
            Order.tenant_id == tenant_id, Order.customer_id.is_not(None),
            Order.status.in_(IN_FLIGHT_STATUSES), Order.id.not_in(invoiced),
        )
        .group_by(Order.customer_id)
    )
    if customer_ids is not None:
        q = q.where(Order.customer_id.in_(customer_ids))
    return {cid: money(total) for cid, total in await db.execute(q)}


async def _unapplied(db: AsyncSession, tenant_id: uuid.UUID, customer_ids: list[uuid.UUID] | None = None) -> dict:
    q = (
        select(CustomerPayment.customer_id, func.coalesce(func.sum(CustomerPayment.unallocated), 0))
        .where(CustomerPayment.tenant_id == tenant_id, CustomerPayment.voided_at.is_(None),
               CustomerPayment.customer_id.is_not(None))
        .group_by(CustomerPayment.customer_id)
    )
    if customer_ids is not None:
        q = q.where(CustomerPayment.customer_id.in_(customer_ids))
    return {cid: money(total) for cid, total in await db.execute(q)}


async def _open_by_customer(db: AsyncSession, tenant_id: uuid.UUID, customer_ids: list[uuid.UUID] | None = None) -> dict:
    q = select(SalesInvoice).where(
        SalesInvoice.tenant_id == tenant_id, SalesInvoice.customer_id.is_not(None),
        SalesInvoice.kind != "credit_note", SalesInvoice.status.in_(("open", "partially_paid")),
    ).order_by(SalesInvoice.due_date)
    if customer_ids is not None:
        q = q.where(SalesInvoice.customer_id.in_(customer_ids))
    out: dict = defaultdict(list)
    for inv in await db.scalars(q):
        out[inv.customer_id].append(inv)
    return out


def _summary(customer: Customer, settings: AccountSettings, today: date, *, balance: Decimal,
             uninvoiced: Decimal, unapplied: Decimal, open_invoices: list[SalesInvoice]) -> dict:
    aging = aging_of(open_invoices, today)
    grace = settings.overdue_grace_days
    overdue = [i for i in open_invoices if i.balance_due > 0 and (today - i.due_date).days > 0]
    blocking = [i for i in overdue if (today - i.due_date).days > grace]
    limit = limit_for(customer, settings)
    exposure = balance + with_vat(uninvoiced, settings)
    return {
        "customer_id": customer.id,
        "name": customer.name,
        "company": customer.company,
        "branch_id": customer.branch_id,
        "whatsapp_number": customer.whatsapp_number,
        "currency": settings.currency,
        "balance": balance,
        "uninvoiced": with_vat(uninvoiced, settings),
        "exposure": exposure,
        "credit_limit": limit,
        "available_credit": (limit - exposure) if limit is not None else None,
        "over_limit": limit is not None and exposure > limit,
        "payment_terms_days": terms_for(customer, settings),
        "on_hold": customer.on_hold,
        "overdue": sum((i.balance_due for i in overdue), ZERO),
        "oldest_overdue_days": max(((today - i.due_date).days for i in overdue), default=0),
        "blocking_overdue": sum((i.balance_due for i in blocking), ZERO),
        "unapplied": unapplied,
        "open_invoices": len(open_invoices),
        "aging": aging,
    }


async def account_summary(db: AsyncSession, tenant_id: uuid.UUID, customer: Customer) -> dict:
    settings = await get_settings(db, tenant_id)
    today = await _today(db, tenant_id)
    ids = [customer.id]
    return _summary(
        customer, settings, today,
        balance=(await _balances(db, tenant_id, ids)).get(customer.id, ZERO),
        uninvoiced=(await _uninvoiced(db, tenant_id, ids)).get(customer.id, ZERO),
        unapplied=(await _unapplied(db, tenant_id, ids)).get(customer.id, ZERO),
        open_invoices=(await _open_by_customer(db, tenant_id, ids)).get(customer.id, []),
    )


async def list_accounts(db: AsyncSession, tenant_id: uuid.UUID, scope: uuid.UUID | None = None) -> tuple[list[dict], dict]:
    """Every customer's account in scope, plus totals for the receivables overview."""
    settings = await get_settings(db, tenant_id)
    today = await _today(db, tenant_id)
    q = select(Customer).where(Customer.tenant_id == tenant_id)
    if scope is not None:
        q = q.where(Customer.branch_id == scope)
    customers = list(await db.scalars(q.order_by(Customer.name)))
    ids = [c.id for c in customers]
    balances, uninvoiced, unapplied, opened = (
        await _balances(db, tenant_id, ids), await _uninvoiced(db, tenant_id, ids),
        await _unapplied(db, tenant_id, ids), await _open_by_customer(db, tenant_id, ids),
    )
    rows = [
        _summary(c, settings, today, balance=balances.get(c.id, ZERO), uninvoiced=uninvoiced.get(c.id, ZERO),
                 unapplied=unapplied.get(c.id, ZERO), open_invoices=opened.get(c.id, []))
        for c in customers
    ]
    totals = {
        "currency": settings.currency,
        "receivable": sum((r["balance"] for r in rows if r["balance"] > 0), ZERO),
        "overdue": sum((r["overdue"] for r in rows), ZERO),
        "customers_overdue": sum(1 for r in rows if r["overdue"] > 0),
        "customers_over_limit": sum(1 for r in rows if r["over_limit"]),
        "customers_on_hold": sum(1 for r in rows if r["on_hold"]),
        "unapplied": sum((r["unapplied"] for r in rows), ZERO),
        "aging": {b: sum((r["aging"][b] for r in rows), ZERO) for b in AGING_BUCKETS},
    }
    await db.commit()  # settings may have been created on first use
    return rows, totals


async def credit_check(db: AsyncSession, tenant_id: uuid.UUID, customer: Customer, order_amount: Decimal) -> list[dict]:
    """Why a new order for this customer must wait for approval (empty list = it may go through).

    `order_amount` is the order total at price-list prices (VAT is added here
    when the price list excludes it).
    """
    settings = await get_settings(db, tenant_id)
    summary = await account_summary(db, tenant_id, customer)
    reasons: list[dict] = []
    ccy = settings.currency
    if customer.on_hold:
        reasons.append({"type": "on_hold", "message": "Account is on hold"})
    if settings.hold_when_overdue and summary["blocking_overdue"] > 0:
        reasons.append({
            "type": "overdue", "amount": str(summary["overdue"]), "days": summary["oldest_overdue_days"],
            "message": f"{ccy} {summary['overdue']:,.2f} overdue (oldest {summary['oldest_overdue_days']} days)",
        })
    limit = summary["credit_limit"]
    if settings.hold_over_limit and limit is not None:
        after = summary["exposure"] + with_vat(order_amount, settings)
        if after > limit:
            reasons.append({
                "type": "over_limit", "limit": str(limit), "exposure": str(summary["exposure"]),
                "after_order": str(after),
                "message": f"Order would take the account to {ccy} {after:,.2f}, over its {ccy} {limit:,.2f} credit limit",
            })
    return reasons


# ---- lists and statements ---------------------------------------------------------------------

async def list_invoices(
    db: AsyncSession, tenant_id: uuid.UUID, *, scope: uuid.UUID | None = None, customer_id: uuid.UUID | None = None,
    status_: str | None = None, kind: str | None = None, limit: int = 200,
) -> list[SalesInvoice]:
    q = select(SalesInvoice).where(SalesInvoice.tenant_id == tenant_id)
    if scope is not None:
        q = q.where(SalesInvoice.branch_id == scope)
    if customer_id is not None:
        q = q.where(SalesInvoice.customer_id == customer_id)
    if kind:
        q = q.where(SalesInvoice.kind == kind)
    if status_ == "unpaid":
        q = q.where(SalesInvoice.status.in_(("open", "partially_paid")))
    elif status_ == "overdue":
        q = q.where(SalesInvoice.status.in_(("open", "partially_paid")),
                    SalesInvoice.due_date < await _today(db, tenant_id))
    elif status_:
        q = q.where(SalesInvoice.status == status_)
    return list(await db.scalars(q.order_by(SalesInvoice.issued_at.desc()).limit(limit)))


async def list_payments(
    db: AsyncSession, tenant_id: uuid.UUID, *, scope: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None, limit: int = 200,
) -> list[CustomerPayment]:
    q = select(CustomerPayment).where(CustomerPayment.tenant_id == tenant_id)
    if scope is not None:
        q = q.where(CustomerPayment.branch_id == scope)
    if customer_id is not None:
        q = q.where(CustomerPayment.customer_id == customer_id)
    return list(await db.scalars(q.order_by(CustomerPayment.paid_on.desc(), CustomerPayment.created_at.desc()).limit(limit)))


async def allocations_for_invoice(db: AsyncSession, invoice_id: uuid.UUID) -> list[tuple[PaymentAllocation, CustomerPayment]]:
    rows = await db.execute(
        select(PaymentAllocation, CustomerPayment)
        .join(CustomerPayment, CustomerPayment.id == PaymentAllocation.payment_id)
        .where(PaymentAllocation.invoice_id == invoice_id)
        .order_by(CustomerPayment.paid_on)
    )
    return list(rows.all())


async def statement(
    db: AsyncSession, tenant_id: uuid.UUID, customer: Customer, *, start: date | None, end: date | None,
) -> dict:
    """Opening balance, every ledger line in the period with a running balance, closing balance and aging."""
    settings = await get_settings(db, tenant_id)
    today = await _today(db, tenant_id)
    end = end or today
    start = start or (end - timedelta(days=90))
    if start > end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The start date must be before the end date")
    opening = money(await db.scalar(
        select(func.coalesce(func.sum(AccountEntry.debit - AccountEntry.credit), 0)).where(
            AccountEntry.tenant_id == tenant_id, AccountEntry.customer_id == customer.id, AccountEntry.entry_date < start,
        )
    ))
    entries = list(await db.scalars(
        select(AccountEntry).where(
            AccountEntry.tenant_id == tenant_id, AccountEntry.customer_id == customer.id,
            AccountEntry.entry_date >= start, AccountEntry.entry_date <= end,
        ).order_by(AccountEntry.entry_date, AccountEntry.created_at)
    ))
    running, lines = opening, []
    for e in entries:
        running = running + money(e.debit) - money(e.credit)
        lines.append({
            "date": e.entry_date, "kind": e.kind, "document_number": e.document_number,
            "description": e.description, "debit": money(e.debit), "credit": money(e.credit), "balance": running,
            "invoice_id": e.invoice_id, "payment_id": e.payment_id,
        })
    summary = await account_summary(db, tenant_id, customer)
    await db.commit()
    return {
        "customer": {
            "id": customer.id, "name": customer.name, "company": customer.company,
            "vat_number": customer.vat_number, "address": customer.address, "phone": customer.whatsapp_number,
        },
        "seller": _seller(settings),
        "currency": settings.currency,
        "start": start, "end": end, "generated_on": today,
        "opening_balance": opening,
        "total_debits": sum((ln["debit"] for ln in lines), ZERO),
        "total_credits": sum((ln["credit"] for ln in lines), ZERO),
        "closing_balance": running,
        "lines": lines,
        "summary": summary,
        "footer": settings.invoice_footer,
    }