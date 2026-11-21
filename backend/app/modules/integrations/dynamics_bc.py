"""Microsoft Dynamics 365 Business Central connector (API v2.0).

Who owns what -- the same split as Odoo and SAP:
- Business Central owns items, prices and stock: every few minutes each
  branch gets the items' unit prices and stock. Items are matched on item
  No. = Salesman SKU. The standard API reports stock per company, not per
  location, so every branch linked to the same company sees the company's
  stock (less what that branch has promised); a note says so when several
  branches are linked.
- Salesman owns customers, orders, invoices, credit notes and payments:
    order confirmed  -> sales order, External Document No. = Salesman order
    order delivered  -> nothing yet: BC posts the shipment with the invoice
    order cancelled  -> the sales order is deleted (allowed while unshipped)
    invoice          -> when the invoice matches its order: the order is
                        shipped and invoiced in BC (shipAndInvoice); else a
                        posted sales invoice with the same lines
    credit note      -> posted sales credit memo, applied to its invoice
    payment          -> customer payment journal lines (one per invoice the
                        payment was applied to), ready to post in BC
    payment reversed -> the journal lines are removed if not yet posted
- Every document is looked up by its Salesman number first, so a retry never
  makes a duplicate.

Salesman already signs and reports invoices to ZATCA: switch off e-invoicing
for documents created through the API, so nothing is reported twice.
"""
import logging
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import CustomerPayment, PaymentAllocation, SalesInvoice
from app.db.models.branch import Branch
from app.db.models.customer import Customer
from app.db.models.integration import IntegrationConnection, IntegrationLink
from app.db.models.order import Order
from app.modules.accounts import service as accounts
from app.modules.integrations import catalog, store
from app.modules.integrations.base import (  # noqa: F401 -- re-exported for the service
    CENT, LIVE_ORDER, SYNC_LABEL, Result, Skip, SyncProblem, connected_after, money, rate_key,
)
from app.modules.integrations.bc_client import DEFAULT_API, BcClient, lit
from app.schemas.pricing import PriceLineIn

logger = logging.getLogger("salesman.integrations")

NAME = "Dynamics 365 Business Central"
PAYMENT_METHODS = accounts.PAYMENT_METHODS
CONNECT_FIELDS = {
    "tenant": {"label": "Microsoft Entra tenant ID or domain", "placeholder": "yourcompany.onmicrosoft.com"},
    "database": {"label": "Environment", "placeholder": "Production"},
    "username": {"label": "Application (client) ID", "placeholder": "00000000-0000-0000-0000-000000000000"},
    "api_key": {"label": "Client secret", "placeholder": "From the app registration in Microsoft Entra"},
    "url": {"label": "API address", "placeholder": DEFAULT_API, "default": DEFAULT_API, "advanced": True},
}
WALKIN_NAME = "Walk-in customers (Salesman)"


def open_client(url: str, database: str | None, username: str | None, key: str, conn_settings: dict | None = None,
                *, api: str | None = None, version: str | None = None) -> BcClient:
    s = conn_settings or {}
    return BcClient(url or DEFAULT_API, database, username, key, tenant=s.get("aad_tenant"),
                    company_id=s.get("company_id"))


def clean_setting(key: str, value):
    """Business Central ids are GUIDs (strings); tax groups are codes."""
    if key == "taxes":
        return {rate_key(rate): str(code) for rate, code in value.items() if code}
    if key == "payment_journals":
        return {m: str(j) for m, j in value.items() if j and m in PAYMENT_METHODS}
    if key == "branches":
        return {str(b): {"warehouse_id": str(m["warehouse_id"]) if m.get("warehouse_id") else None,
                         "pricelist_id": None} for b, m in value.items()}
    if key in ("company_id", "sales_journal_id", "adjustment_account"):
        return str(value) if value else None
    return value


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


# ---- discovery and settings ------------------------------------------------------------------

async def discover(client: BcClient) -> dict:
    companies = await client.list("companies")
    if not companies:
        return {"version": client.version, "api": client.api, "companies": [], "warehouses": [], "pricelists": [],
                "journals": [], "taxes": [], "fields": {}}
    if client.company_id not in {c["id"] for c in companies}:
        client.company_id = companies[0]["id"]
    info = (await client.list(client.company_path("companyInformation")) or [{}])[0]
    currency = info.get("currencyCode") or "SAR"
    locations = await client.list(client.company_path("locations"))
    tax_groups = await client.list(client.company_path("taxGroups"))
    journals = await client.list(client.company_path("customerPaymentJournals"))
    income = await client.list(client.company_path("accounts"), filter="category eq 'Income' and blocked eq false")
    taxes = []
    for t in tax_groups:
        found = re.search(r"(\d+(?:\.\d+)?)", f"{t.get('code', '')} {t.get('displayName', '')}")
        taxes.append({"id": t["code"], "name": f"{t['code']} - {t.get('displayName') or ''}".strip(" -"),
                      "amount": float(found.group(1)) if found else None, "price_include": False, "company_id": None})
    return {
        "version": client.version, "api": client.api,
        "companies": [{"id": c["id"], "name": c.get("displayName") or c.get("name"), "currency": currency
                       if c["id"] == client.company_id else None} for c in companies],
        "warehouses": [{"id": loc["id"], "name": loc.get("displayName") or loc["code"], "code": loc["code"], "company_id": None}
                       for loc in locations],
        "pricelists": [],
        "journals": [{"id": j["id"], "name": f"{j['code']} - {j.get('displayName') or ''}", "type": "bank",
                      "code": j["code"], "company_id": None} for j in journals],
        "taxes": taxes,
        "accounts": [{"id": a["id"], "name": f"{a['number']} - {a.get('displayName') or ''}"} for a in income],
        "fields": {},
        "labels": {"journals": "Payment journal for payments by", "warehouse": "Location",
                   "adjustment_account": "Income account for lines without an item (e.g. partial credit notes)",
                   "taxes": "Tax group (optional: items keep their own posting groups)"},
    }


def _pick_location(branch: Branch, locations: list[dict]) -> str | None:
    if not locations:
        return None
    words = {w.lower() for w in re.findall(r"\w+", f"{branch.name} {branch.city or ''}") if len(w) > 2}
    for loc in locations:
        if words & {w.lower() for w in re.findall(r"\w+", f"{loc['name']} {loc['code']}")}:
            return loc["id"]
    return locations[0]["id"]


def defaults(options: dict, branches: list[Branch], acct, current: dict | None = None) -> dict:
    current = dict(current or {})
    companies = options["companies"]
    company = next((c for c in companies if c["id"] == current.get("company_id")), None) or (companies[0] if companies else None)
    taxes = {}
    for rate in {rate_key(acct.vat_rate), rate_key(0)}:
        match = [t for t in options["taxes"] if t["amount"] is not None and rate_key(t["amount"]) == rate]
        if match:
            taxes[rate] = match[0]["id"]
    first_journal = options["journals"][0]["id"] if options["journals"] else None
    branch_map = dict(current.get("branches") or {})
    for b in branches:
        if str(b.id) not in branch_map and b.is_active:
            branch_map[str(b.id)] = {"warehouse_id": _pick_location(b, options["warehouses"]), "pricelist_id": None}
    out = {
        "company_id": company["id"] if company else None,
        "company_currency": (company or {}).get("currency") or acct.currency,
        "taxes": taxes,
        "payment_journals": {m: first_journal for m in PAYMENT_METHODS} if first_journal else {},
        "adjustment_account": options["accounts"][0]["id"] if options.get("accounts") else None,
        "branches": branch_map,
        "push_orders": True, "validate_deliveries": False, "push_invoices": True, "push_payments": True,
        "pull_catalog": True, "pull_interval_minutes": 15,
        "aad_tenant": current.get("aad_tenant"),
    }
    out.update({k: v for k, v in current.items() if v is not None and k in out and k != "branches"})
    out["fields"] = options.get("fields") or {}
    return out


def problems(s: dict, branches: list[Branch], acct, options: dict | None = None) -> list[str]:
    out = []
    if not s.get("company_id"):
        out.append("Choose the Business Central company.")
    if s.get("push_payments"):
        missing = [m for m in PAYMENT_METHODS if not (s.get("payment_journals") or {}).get(m)]
        if missing:
            out.append("Choose a Business Central payment journal for payments by "
                       + ", ".join(m.replace("_", " ") for m in missing) + ".")
    unmapped = [b.name for b in branches if b.is_active and not ((s.get("branches") or {}).get(str(b.id)) or {}).get("warehouse_id")]
    if unmapped and (s.get("pull_catalog") or s.get("push_orders")):
        out.append("Choose a Business Central location for: " + ", ".join(unmapped) + ".")
    return out


def _tax_code(s: dict, rate) -> str | None:
    return (s.get("taxes") or {}).get(rate_key(rate))


# ---- customers ------------------------------------------------------------------------------

def _customer_vals(customer: Customer) -> dict:
    street = " ".join(x for x in (customer.building_number, customer.street) if x) or customer.address
    vals = {
        "displayName": (customer.company or customer.name)[:100],
        "type": "Company" if (customer.company or customer.vat_number or customer.cr_number) else "Person",
        "phoneNumber": (customer.whatsapp_number or "")[:30] or None,
        "taxRegistrationNumber": customer.vat_number or None,
        "addressLine1": (street or "")[:100] or None,
        "addressLine2": (customer.district or "")[:50] or None,
        "city": (customer.city or "")[:30] or None,
        "postalCode": (customer.postal_code or "")[:20] or None,
        "country": "SA",
    }
    return {k: v for k, v in vals.items() if v is not None}


async def _find_customer(client: BcClient, customer: Customer) -> dict | None:
    if customer.vat_number:
        row = await client.first(client.company_path("customers"), f"taxRegistrationNumber eq {lit(customer.vat_number)}")
        if row:
            return row
    digits = _digits(customer.whatsapp_number)
    if len(digits) >= 9:
        for row in await client.list(client.company_path("customers"),
                                     filter=f"contains(phoneNumber,{lit(digits[-9:])})", top=10):
            if _digits(row.get("phoneNumber")).endswith(digits[-9:]):
                return row
    return None


async def ensure_customer(db: AsyncSession, conn: IntegrationConnection, client: BcClient, customer: Customer | None) -> str:
    s = conn.settings
    if customer is None:
        if s.get("walkin_partner_id"):
            return str(s["walkin_partner_id"])
        row = await client.first(client.company_path("customers"), f"displayName eq {lit(WALKIN_NAME)}") \
            or await client.post(client.company_path("customers"), {"displayName": WALKIN_NAME, "type": "Company"})
        conn.settings = {**s, "walkin_partner_id": row["id"]}
        await db.flush()
        return row["id"]
    link = await store.get_link(db, conn, "customer", customer.id)
    if link is not None:
        return link.external_id
    row = await _find_customer(client, customer) \
        or await client.post(client.company_path("customers"), _customer_vals(customer))
    await store.save_link(db, conn, "customer", customer.id, row["id"], external_ref=row.get("number"))
    return row["id"]


async def push_customer(db: AsyncSession, conn: IntegrationConnection, client: BcClient, customer: Customer) -> Result:
    link = await store.get_link(db, conn, "customer", customer.id)
    if link is None:
        raise Skip("Sent with the customer's first order or invoice", quiet=True)
    await client.patch(client.company_path(f"customers({link.external_id})"), _customer_vals(customer))
    return Result(external_ref=link.external_ref)


async def item_id_for(db: AsyncSession, conn: IntegrationConnection, client: BcClient, sku: str | None) -> str | None:
    if not sku:
        return None
    link = await store.get_link(db, conn, "product", sku)
    if link is not None:
        return link.external_id
    row = await client.first(client.company_path("items"), f"number eq {lit(sku)}")
    if row is None:
        return None
    await store.save_link(db, conn, "product", sku, row["id"])
    return row["id"]


# ---- orders ---------------------------------------------------------------------------------

async def _add_lines(client: BcClient, base: str, wanted: list[dict]) -> dict:
    """Add the lines not there yet (a retry after a timeout adds only what is missing). Returns {itemId: line id}."""
    have = {ln.get("itemId"): ln["id"] for ln in await client.list(base)}
    for line in wanted:
        if line["itemId"] not in have:
            row = await client.post(base, line)
            have[line["itemId"]] = row["id"]
    return have


async def push_order(db: AsyncSession, conn: IntegrationConnection, client: BcClient, order: Order) -> Result:
    s = conn.settings
    link = await store.get_link(db, conn, "order", order.id)
    if link is not None:
        return Result(external_ref=link.external_ref, message="Already in Business Central")
    if not s.get("push_orders"):
        raise Skip("Sending orders to Business Central is switched off", quiet=True)
    if order.status not in LIVE_ORDER:
        raise Skip(f"The order is {order.status.replace('_', ' ')}", quiet=True)
    if not connected_after(conn, order.confirmed_at or order.created_at):
        raise Skip("Confirmed before Business Central was connected", quiet=True)
    location = ((s.get("branches") or {}).get(str(order.branch_id)) or {}).get("warehouse_id")
    if not location:
        raise SyncProblem("This branch isn't linked to a Business Central location. Choose one under Integrations.")
    acct = await accounts.get_settings(db, order.tenant_id)
    customer = await db.get(Customer, order.customer_id) if order.customer_id else None
    cust_id = await ensure_customer(db, conn, client, customer)

    lines, missing, skus = [], [], {}
    for item in order.items:
        item_id = await item_id_for(db, conn, client, item.sku)
        if item_id is None:
            missing.append(item.sku)
            continue
        vals = {"lineType": "Item", "itemId": item_id, "quantity": item.quantity, "unitPrice": float(item.unit_price),
                "locationId": location}
        if _tax_code(s, acct.vat_rate):
            vals["taxCode"] = _tax_code(s, acct.vat_rate)
        lines.append(vals)
        skus[item_id] = item.sku
    if missing:
        raise SyncProblem("These products have no matching item No. in Business Central: " + ", ".join(missing))

    so = await client.first(client.company_path("salesOrders"), f"externalDocumentNumber eq {lit(order.order_number)}")
    if so is None:
        so = await client.post(client.company_path("salesOrders"), {
            "customerId": cust_id, "externalDocumentNumber": order.order_number, "orderDate": _today(),
            "pricesIncludeTax": bool(acct.prices_include_vat),
        })
    have = await _add_lines(client, client.company_path(f"salesOrders({so['id']})/salesOrderLines"), lines)
    await store.save_link(db, conn, "order", order.id, so["id"], external_ref=so.get("number"),
                          extra={"lines": {skus[i]: line_id for i, line_id in have.items() if i in skus},
                                 "quantities": {item.sku: item.quantity for item in order.items}})
    return Result(external_ref=so.get("number"))


async def deliver_order(db: AsyncSession, conn: IntegrationConnection, client: BcClient, order: Order) -> Result:
    if await store.get_link(db, conn, "order", order.id) is None:
        raise Skip("This order isn't in Business Central", quiet=True)
    raise Skip("Business Central posts the shipment together with the invoice", quiet=True)


async def cancel_order(db: AsyncSession, conn: IntegrationConnection, client: BcClient, order: Order) -> Result:
    link = await store.get_link(db, conn, "order", order.id)
    if link is None:
        raise Skip("This order isn't in Business Central", quiet=True)
    if not (link.extra or {}).get("cancelled"):
        await client.delete(client.company_path(f"salesOrders({link.external_id})"))
        await store.save_link(db, conn, "order", order.id, link.external_id, extra={"cancelled": True})
    return Result(external_ref=link.external_ref)


# ---- invoices and credit notes --------------------------------------------------------------

async def _document_lines(db, conn, client, inv: SalesInvoice, acct) -> list[dict]:
    out = []
    for line in inv.lines or []:
        if not line.get("sku"):
            account = conn.settings.get("adjustment_account")
            if not account:
                raise SyncProblem("Choose the Business Central income account for lines without an item under Integrations.")
            out.append({"lineType": "Account", "accountId": account, "description": str(line.get("name") or "")[:100],
                        "quantity": 1, "unitPrice": float(money(line.get("net", line.get("unit_price"))))})
            continue
        item_id = await item_id_for(db, conn, client, line.get("sku"))
        if item_id is None:
            raise SyncProblem(f"{line.get('sku') or line.get('name')} has no matching item No. in Business Central.")
        qty = Decimal(str(line["quantity"])) or Decimal(1)
        price = (Decimal(str(line["total"])) / qty) if acct.prices_include_vat else Decimal(str(line["unit_price"]))
        vals = {"lineType": "Item", "itemId": item_id, "quantity": float(qty),
                "unitPrice": float(price.quantize(Decimal("0.0001")))}
        code = _tax_code(conn.settings, line.get("vat_rate", acct.vat_rate))
        if code:
            vals["taxCode"] = code
        out.append(vals)
    return out


def _matches_order(inv: SalesInvoice, order_link: IntegrationLink) -> bool:
    ordered = (order_link.extra or {}).get("quantities") or {}
    invoiced = {}
    for line in inv.lines or []:
        invoiced[line.get("sku")] = invoiced.get(line.get("sku"), 0) + float(line["quantity"])
    return bool(ordered) and {k: float(v) for k, v in ordered.items()} == invoiced


async def push_invoice(db: AsyncSession, conn: IntegrationConnection, client: BcClient, inv: SalesInvoice) -> Result:
    s = conn.settings
    if inv.kind not in ("invoice", "credit_note"):
        raise Skip("Opening balances stay in Business Central as they are", quiet=True)
    if not s.get("push_invoices"):
        raise Skip("Sending invoices to Business Central is switched off", quiet=True)
    if not connected_after(conn, inv.issued_at):
        raise Skip("Issued before Business Central was connected", quiet=True)
    link = await store.get_link(db, conn, "invoice", inv.id)
    if link is not None:
        return Result(external_ref=link.external_ref, message="Already in Business Central")
    acct = await accounts.get_settings(db, inv.tenant_id)
    customer = await db.get(Customer, inv.customer_id) if inv.customer_id else None
    cust_id = await ensure_customer(db, conn, client, customer)
    refund = inv.kind == "credit_note"
    entity = "salesCreditMemos" if refund else "salesInvoices"
    note = None

    doc = await client.first(client.company_path(entity), f"externalDocumentNumber eq {lit(inv.number)}")
    if doc is None and not refund and inv.order_id:
        order = await db.get(Order, inv.order_id)
        order_link = await store.get_link(db, conn, "order", inv.order_id)
        if order_link is None and order is not None and s.get("push_orders") and order.status in LIVE_ORDER \
                and connected_after(conn, order.confirmed_at or order.created_at):
            try:
                await push_order(db, conn, client, order)
            except (Skip, SyncProblem):
                pass
            order_link = await store.get_link(db, conn, "order", inv.order_id)
        if order_link is not None and not (order_link.extra or {}).get("cancelled"):
            if _matches_order(inv, order_link):
                await client.patch(client.company_path(f"salesOrders({order_link.external_id})"),
                                   {"externalDocumentNumber": inv.number})
                await client.post(client.company_path(f"salesOrders({order_link.external_id})/Microsoft.NAV.shipAndInvoice"))
                doc = await client.first(client.company_path(entity), f"orderNumber eq {lit(order_link.external_ref)}")
                if doc is None:
                    raise SyncProblem(f"Business Central shipped and invoiced order {order_link.external_ref}, "
                                      "but the invoice could not be found. Check it in Business Central.")
            else:
                note = (f"The invoice differs from sales order {order_link.external_ref}, so the order was left open "
                        "in Business Central. Close or delete it there.")
    if doc is None:
        body = {"customerId": cust_id, "externalDocumentNumber": inv.number,
                "pricesIncludeTax": bool(acct.prices_include_vat)}
        if refund:
            body["creditMemoDate"] = inv.issue_date.isoformat()
            if inv.original_invoice_id:
                original = await store.get_link(db, conn, "invoice", inv.original_invoice_id)
                if original is not None:
                    body["invoiceId"] = original.external_id
        else:
            body.update({"invoiceDate": inv.issue_date.isoformat(), "dueDate": inv.due_date.isoformat()})
        doc = await client.post(client.company_path(entity), body)
        line_path = client.company_path(f"{entity}({doc['id']})/{'salesCreditMemoLines' if refund else 'salesInvoiceLines'}")
        for line in await _document_lines(db, conn, client, inv, acct):
            await client.post(line_path, line)
    if doc.get("status") in (None, "Draft"):
        await client.post(client.company_path(f"{entity}({doc['id']})/Microsoft.NAV.post"))
    doc = await client.get(client.company_path(f"{entity}({doc['id']})")) or doc
    await store.save_link(db, conn, "invoice", inv.id, doc["id"], external_ref=doc.get("number"), extra={"kind": inv.kind})
    if abs(money(doc.get("totalAmountIncludingTax")) - money(inv.total)) > Decimal("0.005"):
        return Result("warning", f"Business Central's total is {money(doc.get('totalAmountIncludingTax')):.2f}, "
                                 f"Salesman's is {money(inv.total):.2f}. Check the tax setup of these items.",
                      doc.get("number"))
    if note:
        return Result("warning", note, doc.get("number"))
    return Result(external_ref=doc.get("number"))


# ---- payments -------------------------------------------------------------------------------

async def push_payment(db: AsyncSession, conn: IntegrationConnection, client: BcClient, pay: CustomerPayment) -> Result:
    s = conn.settings
    if not s.get("push_payments"):
        raise Skip("Sending payments to Business Central is switched off", quiet=True)
    if not connected_after(conn, pay.created_at):
        raise Skip("Recorded before Business Central was connected", quiet=True)
    link = await store.get_link(db, conn, "payment", pay.id)
    if pay.voided_at is not None and link is None:
        raise Skip("Reversed before it was sent", quiet=True)
    if link is not None:
        return Result(external_ref=link.external_ref, message="Already in Business Central")
    journal = (s.get("payment_journals") or {}).get(pay.method)
    if not journal:
        raise SyncProblem(f"No Business Central payment journal is chosen for {pay.method.replace('_', ' ')} payments.")
    customer = await db.get(Customer, pay.customer_id) if pay.customer_id else None
    cust_id = await ensure_customer(db, conn, client, customer)
    base = client.company_path(f"customerPaymentJournals({journal})/customerPayments")

    parts, rest = [], money(pay.amount)
    for alloc in await db.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == pay.id)
                                  .order_by(PaymentAllocation.created_at)):
        inv_link = await store.get_link(db, conn, "invoice", alloc.invoice_id)
        if inv_link is None or (inv_link.extra or {}).get("kind") == "credit_note":
            continue
        parts.append((money(alloc.amount), inv_link.external_id))
        rest -= money(alloc.amount)
    if rest > 0:
        parts.append((rest, None))

    existing = {row.get("description"): row for row in
                await client.list(base, filter=f"documentNumber eq {lit(pay.number[:20])}")}
    ids = []
    for i, (amount, invoice_id) in enumerate(parts, start=1):
        desc = f"Salesman {pay.number} ({i}/{len(parts)})"[:100]
        row = existing.get(desc)
        if row is None:
            vals = {"customerId": cust_id, "postingDate": pay.paid_on.isoformat(), "documentNumber": pay.number[:20],
                    "description": desc, "amount": -float(amount)}   # a payment is a credit to the customer
            if invoice_id:
                vals["appliesToInvoiceId"] = invoice_id
            row = await client.post(base, vals)
        ids.append(row["id"])
    await store.save_link(db, conn, "payment", pay.id, ids[0], external_ref=pay.number,
                          extra={"journal": journal, "lines": ids})
    return Result(message="In the payment journal, ready to post in Business Central.", external_ref=pay.number)


async def void_payment(db: AsyncSession, conn: IntegrationConnection, client: BcClient, pay: CustomerPayment) -> Result:
    link = await store.get_link(db, conn, "payment", pay.id)
    if link is None:
        raise Skip("This payment isn't in Business Central", quiet=True)
    extra = link.extra or {}
    if extra.get("voided"):
        return Result(external_ref=link.external_ref)
    base = client.company_path(f"customerPaymentJournals({extra.get('journal')})/customerPayments")
    gone = [not await client.delete(f"{base}({line})") for line in extra.get("lines") or [link.external_id]]
    await store.save_link(db, conn, "payment", pay.id, link.external_id, extra={"voided": True})
    if any(gone):
        return Result("warning", "Some of this payment was already posted in Business Central. Reverse it there.",
                      link.external_ref)
    return Result(external_ref=link.external_ref)


# ---- prices and stock -----------------------------------------------------------------------

async def fetch_catalog(db: AsyncSession, conn: IntegrationConnection, client: BcClient) -> catalog.Catalog:
    s = conn.settings
    if not s.get("pull_catalog"):
        raise Skip("Fetching prices and stock from Business Central is switched off", quiet=True)
    items = await client.list(client.company_path("items"), filter="blocked eq false and type eq 'Inventory'")
    if not items:
        raise SyncProblem("Business Central has no unblocked inventory items. Nothing was changed in Salesman.")
    currency = s.get("company_currency") or "SAR"
    products, rows = [], {}
    for it in items:
        sku = str(it.get("number") or "").strip()[:64]
        if not sku:
            continue
        rows[sku] = it
        products.append(catalog.CatalogProduct(
            sku=sku, external_id=it["id"], name_en=str(it.get("displayName") or sku)[:255],
            name_ar=str(it["displayName2"])[:255] if it.get("displayName2") else None,
            cost=Decimal(str(it["unitCost"])) if it.get("unitCost") else None,
        ))
    cat = catalog.Catalog(products=products, cost_currency=currency,
                          empty_message="No branch is linked to a Business Central location.", source="Business Central sync")
    mapped = await catalog.mapped_branches(db, conn)
    for branch, _ in mapped:
        promised = await catalog.pending(db, conn, branch.id)
        lines = [PriceLineIn(
            sku=p.sku, unit_price=Decimal(str(rows[p.sku].get("unitPrice") or 0)).quantize(CENT),
            quantity=max(int(Decimal(str(rows[p.sku].get("inventory") or 0))) - promised.get(p.sku, 0), 0),
            currency=currency[:3], unit_cost=Decimal(str(p.cost)).quantize(CENT) if p.cost else None,
            name_en=p.name_en, name_ar=p.name_ar,
        ) for p in products]
        cat.branches.append((branch, lines))
    if len(mapped) > 1:
        cat.notes.append("Business Central reports stock for the whole company, so each branch shows the company's stock.")
    return cat


async def pull_catalog(db: AsyncSession, conn: IntegrationConnection, client: BcClient) -> Result:
    return await catalog.apply(db, conn, await fetch_catalog(db, conn, client))


# ---- balances -------------------------------------------------------------------------------

async def balances(db: AsyncSession, conn: IntegrationConnection, client: BcClient) -> list[dict]:
    rows = list(await db.scalars(
        select(IntegrationLink).where(IntegrationLink.connection_id == conn.id, IntegrationLink.entity == "customer")
    ))
    if not rows:
        return []
    ids = [uuid.UUID(r.local_key) for r in rows]
    ours = await accounts._balances(db, conn.tenant_id, ids)
    customers = {c.id: c for c in await db.scalars(select(Customer).where(Customer.id.in_(ids)))}
    out = []
    for r in rows:
        row = await client.get(client.company_path(f"customers({r.external_id})")) or {}
        cid = uuid.UUID(r.local_key)
        theirs = money(row.get("balanceDue"))
        mine = ours.get(cid, Decimal("0")).quantize(CENT)
        c = customers.get(cid)
        out.append({"customer_id": cid, "name": (c.company or c.name) if c else r.external_ref, "salesman": mine,
                    "odoo": theirs, "erp": theirs, "difference": mine - theirs, "partner_id": r.external_id})
    out.sort(key=lambda x: -abs(x["difference"]))
    return out
