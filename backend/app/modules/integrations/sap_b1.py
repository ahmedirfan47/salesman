"""SAP Business One connector (Service Layer).

Who owns what -- the same split as Odoo:
- SAP owns items, prices and stock. Every few minutes each branch's price list
  and stock are refreshed from its SAP warehouse and price list. Items are
  matched on ItemCode = Salesman SKU. Stock is In Stock minus Committed, so
  open sales orders in SAP are never sold twice.
- Salesman owns customers, orders, invoices, credit notes and payments:
    order confirmed  -> sales order (Orders), NumAtCard = Salesman order number
    order delivered  -> delivery (DeliveryNotes) copied from the sales order
    order cancelled  -> the sales order is cancelled
    invoice          -> A/R invoice copied from the delivery or the order
    credit note      -> A/R credit memo copied from its invoice
    payment          -> incoming payment, applied to the invoices Salesman
                        applied it to
    payment reversed -> the incoming payment is cancelled
- Every document is looked up by its Salesman number (NumAtCard or Remarks)
  before it is created, so a retry after a timeout never makes a duplicate.

Customers are created as business partners with CardCode SM-<id>, unless one
with the same VAT number or phone number already exists.

Salesman already signs and reports invoices to ZATCA: switch off ZATCA
reporting in SAP for documents created through the Service Layer, so nothing
is reported twice.
"""
import logging
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import or_, select
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
from app.modules.integrations.sap_client import SapClient, key, path
from app.schemas.pricing import PriceLineIn

logger = logging.getLogger("salesman.integrations")

NAME = "SAP Business One"
PAYMENT_METHODS = accounts.PAYMENT_METHODS
CONNECT_FIELDS = {
    "url": {"label": "Service Layer address", "placeholder": "https://sap.yourcompany.com:50000"},
    "database": {"label": "Company database", "placeholder": "SBODEMOSA"},
    "username": {"label": "SAP user", "placeholder": "manager"},
    "api_key": {"label": "Password", "placeholder": "The SAP user's password"},
}
WALKIN_CODE = "SM-WALKIN"
_ARABIC = re.compile(r"[؀-ۿ]")


def open_client(url: str, database: str | None, username: str | None, key_: str, conn_settings: dict | None = None,
                *, api: str | None = None, version: str | None = None) -> SapClient:
    return SapClient(url, database, username, key_, version=version)


def clean_setting(key_: str, value):
    """SAP uses codes (strings) for warehouses, VAT groups and accounts, numbers for price lists."""
    if key_ == "taxes":
        return {rate_key(rate): str(code) for rate, code in value.items() if code}
    if key_ == "payment_journals":
        return {m: str(a) for m, a in value.items() if a and m in PAYMENT_METHODS}
    if key_ == "branches":
        return {str(b): {"warehouse_id": str(m["warehouse_id"]) if m.get("warehouse_id") else None,
                         "pricelist_id": int(m["pricelist_id"]) if m.get("pricelist_id") else None}
                for b, m in value.items()}
    if key_ == "sales_journal_id":
        return int(value) if value else None   # the default price list
    if key_ in ("company_id", "adjustment_account"):
        return str(value) if value else None
    return value


def _yes(v) -> bool:
    return v in ("tYES", True, "Y")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


# ---- discovery and settings ------------------------------------------------------------------

async def discover(client: SapClient) -> dict:
    info = await client.action("CompanyService_GetCompanyInfo") or {}
    admin = await client.action("CompanyService_GetAdminInfo") or {}
    currency = admin.get("LocalCurrency") or "SAR"
    warehouses = await client.get_all("Warehouses", select="WarehouseCode,WarehouseName,Inactive")
    pricelists = await client.get_all("PriceLists", select="PriceListNo,PriceListName,DefaultPrimeCurrency")
    vat = await client.get_all("VatGroups", select="Code,Name,Category,Inactive,VatGroups_Lines")
    accounts_ = await client.get_all("ChartOfAccounts", select="Code,Name,CashAccount,ActiveAccount",
                                     filter="CashAccount eq 'tYES'")
    revenue = await client.get_all("ChartOfAccounts", select="Code,Name",
                                   filter="ActiveAccount eq 'tYES' and AccountType eq 'at_Revenues'")
    taxes = []
    for g in vat:
        if g.get("Category") not in (None, "bovcOutputTax") or _yes(g.get("Inactive")):
            continue
        lines = sorted(g.get("VatGroups_Lines") or [], key=lambda x: str(x.get("Effectivefrom") or ""))
        rate = lines[-1].get("Rate") if lines else g.get("VatPercent", 0)
        taxes.append({"id": g["Code"], "name": f"{g['Code']} - {g.get('Name') or ''}".strip(" -"),
                      "amount": float(rate or 0), "price_include": False, "company_id": None})
    return {
        "version": client.version, "api": client.api,
        "companies": [{"id": client.database, "name": info.get("CompanyName") or client.database, "currency": currency}],
        "warehouses": [{"id": w["WarehouseCode"], "name": w.get("WarehouseName") or w["WarehouseCode"],
                        "code": w["WarehouseCode"], "company_id": None}
                       for w in warehouses if not _yes(w.get("Inactive"))],
        "pricelists": [{"id": p["PriceListNo"], "name": p.get("PriceListName") or str(p["PriceListNo"]),
                        "currency": p.get("DefaultPrimeCurrency") or currency, "company_id": None} for p in pricelists],
        "journals": [{"id": a["Code"], "name": f"{a['Code']} - {a.get('Name') or ''}", "type": "cash", "code": a["Code"],
                      "company_id": None} for a in accounts_ if a.get("ActiveAccount") != "tNO"],
        "taxes": taxes,
        "accounts": [{"id": a["Code"], "name": f"{a['Code']} - {a.get('Name') or ''}"} for a in revenue],
        "fields": {},
        # SAP has no sales journal choice: the "sales journal" slot holds the default price list
        "labels": {"sales_journal_id": "Default price list", "journals": "G/L account for payments by",
                   "warehouse": "SAP warehouse", "pricelist": "SAP price list",
                   "adjustment_account": "Revenue account for lines without an item (e.g. partial credit notes)"},
    }


def _pick_warehouse(branch: Branch, warehouses: list[dict]) -> str | None:
    if not warehouses:
        return None
    words = {w.lower() for w in re.findall(r"\w+", f"{branch.name} {branch.city or ''}") if len(w) > 2}
    for wh in warehouses:
        if words & {w.lower() for w in re.findall(r"\w+", f"{wh['name']} {wh['code']}")}:
            return wh["id"]
    return warehouses[0]["id"]


def defaults(options: dict, branches: list[Branch], acct, current: dict | None = None) -> dict:
    current = dict(current or {})
    company = options["companies"][0] if options["companies"] else None
    taxes = {}
    for rate in {rate_key(acct.vat_rate), rate_key(0)}:
        match = [t for t in options["taxes"] if rate_key(t["amount"]) == rate]
        if match:
            taxes[rate] = match[0]["id"]
    first_account = options["journals"][0]["id"] if options["journals"] else None
    branch_map = dict(current.get("branches") or {})
    for b in branches:
        if str(b.id) not in branch_map and b.is_active:
            branch_map[str(b.id)] = {"warehouse_id": _pick_warehouse(b, options["warehouses"]), "pricelist_id": None}
    out = {
        "company_id": company["id"] if company else None,
        "company_currency": company["currency"] if company else acct.currency,
        "sales_journal_id": options["pricelists"][0]["id"] if options["pricelists"] else None,
        "taxes": taxes,
        "payment_journals": {m: first_account for m in PAYMENT_METHODS} if first_account else {},
        "adjustment_account": options["accounts"][0]["id"] if options.get("accounts") else None,
        "branches": branch_map,
        "push_orders": True, "validate_deliveries": True, "push_invoices": True, "push_payments": True,
        "pull_catalog": True, "pull_interval_minutes": 15,
    }
    out.update({k: v for k, v in current.items() if v is not None and k in out and k != "branches"})
    out["fields"] = options.get("fields") or {}
    return out


def problems(s: dict, branches: list[Branch], acct, options: dict | None = None) -> list[str]:
    out = []
    if s.get("pull_catalog") and not s.get("sales_journal_id"):
        out.append("Choose the default SAP price list.")
    if (s.get("push_invoices") or s.get("push_orders")) and rate_key(acct.vat_rate) not in (s.get("taxes") or {}):
        out.append(f"Choose the SAP VAT group for VAT {rate_key(acct.vat_rate)}%.")
    if s.get("push_payments"):
        missing = [m for m in PAYMENT_METHODS if not (s.get("payment_journals") or {}).get(m)]
        if missing:
            out.append("Choose a SAP G/L account for payments by " + ", ".join(m.replace("_", " ") for m in missing) + ".")
    unmapped = [b.name for b in branches if b.is_active and not ((s.get("branches") or {}).get(str(b.id)) or {}).get("warehouse_id")]
    if unmapped and (s.get("pull_catalog") or s.get("push_orders")):
        out.append("Choose a SAP warehouse for: " + ", ".join(unmapped) + ".")
    return out


def _vat(s: dict, rate) -> str:
    code = (s.get("taxes") or {}).get(rate_key(rate))
    if not code:
        raise SyncProblem(f"No SAP VAT group is chosen for VAT {rate_key(rate)}%. Choose one under Integrations.")
    return str(code)


def _warehouse(s: dict, branch_id) -> str:
    wh = ((s.get("branches") or {}).get(str(branch_id)) or {}).get("warehouse_id")
    if not wh:
        raise SyncProblem("This branch isn't linked to a SAP warehouse. Choose one under Integrations.")
    return str(wh)


# ---- customers ------------------------------------------------------------------------------

def _partner_vals(customer: Customer) -> dict:
    street = " ".join(x for x in (customer.building_number, customer.street) if x) or customer.address
    vals = {
        "CardName": (customer.company or customer.name)[:100],
        "Phone1": (customer.whatsapp_number or "")[:20] or None,
        "FederalTaxID": customer.vat_number or None,
        "Notes": f"Contact: {customer.name}"[:100] if customer.company and customer.name != customer.company else None,
        "BPAddresses": [{
            "AddressName": "Main", "AddressType": "bo_BillTo", "Street": (street or "")[:100] or None,
            "Block": customer.district, "City": customer.city, "ZipCode": customer.postal_code, "Country": "SA",
            "BuildingFloorRoom": customer.building_number,
        }],
    }
    if customer.cr_number:
        vals["AdditionalID"] = customer.cr_number
    return {k: v for k, v in vals.items() if v is not None}


async def _find_partner(client: SapClient, customer: Customer) -> str | None:
    if customer.vat_number:
        row = await client.first("BusinessPartners", f"CardType eq 'cCustomer' and FederalTaxID eq {key(customer.vat_number)}",
                                 "CardCode")
        if row:
            return row["CardCode"]
    digits = _digits(customer.whatsapp_number)
    if len(digits) >= 9:
        rows = (await client.get("BusinessPartners", {
            "$filter": f"CardType eq 'cCustomer' and contains(Phone1, {key(digits[-9:])})", "$select": "CardCode,Phone1",
            "$top": 10,
        }) or {}).get("value") or []
        for row in rows:
            if _digits(row.get("Phone1")).endswith(digits[-9:]):
                return row["CardCode"]
    return None


async def ensure_partner(db: AsyncSession, conn: IntegrationConnection, client: SapClient, customer: Customer | None) -> str:
    if customer is None:
        if await client.get(path("BusinessPartners", WALKIN_CODE), {"$select": "CardCode"}) is None:
            await client.post("BusinessPartners", {"CardCode": WALKIN_CODE, "CardName": "Walk-in customers (Salesman)",
                                                   "CardType": "cCustomer"})
        return WALKIN_CODE
    link = await store.get_link(db, conn, "customer", customer.id)
    if link is not None:
        return link.external_id
    code = await _find_partner(client, customer)
    if code is None:
        code = "SM-" + customer.id.hex[:10].upper()
        if await client.get(path("BusinessPartners", code), {"$select": "CardCode"}) is None:
            await client.post("BusinessPartners", {"CardCode": code, "CardType": "cCustomer", **_partner_vals(customer)})
    await store.save_link(db, conn, "customer", customer.id, code, external_ref=customer.company or customer.name)
    return code


async def push_customer(db: AsyncSession, conn: IntegrationConnection, client: SapClient, customer: Customer) -> Result:
    link = await store.get_link(db, conn, "customer", customer.id)
    if link is None:
        raise Skip("Sent with the customer's first order or invoice", quiet=True)
    vals = _partner_vals(customer)
    vals.pop("BPAddresses", None)   # addresses are edited in SAP once the partner exists
    await client.patch(path("BusinessPartners", link.external_id), vals)
    return Result(external_ref=link.external_id)


async def item_code_for(db: AsyncSession, conn: IntegrationConnection, client: SapClient, sku: str | None) -> str | None:
    if not sku:
        return None
    link = await store.get_link(db, conn, "product", sku)
    if link is not None:
        return link.external_id
    row = await client.get(path("Items", sku), {"$select": "ItemCode"})
    if row is None:
        return None
    await store.save_link(db, conn, "product", sku, row["ItemCode"])
    return row["ItemCode"]


# ---- orders ---------------------------------------------------------------------------------

async def _find_doc(client: SapClient, entity: str, ref: str, card: str, field: str = "NumAtCard") -> dict | None:
    return await client.first(entity, f"{field} eq {key(ref)} and CardCode eq {key(card)} and Cancelled eq 'tNO'",
                              "DocEntry,DocNum,DocTotal,DocumentStatus,DocumentLines")


def _lines_by_sku(doc: dict) -> dict:
    return {line["ItemCode"]: line["LineNum"] for line in doc.get("DocumentLines") or [] if line.get("ItemCode")}


async def push_order(db: AsyncSession, conn: IntegrationConnection, client: SapClient, order: Order) -> Result:
    s = conn.settings
    link = await store.get_link(db, conn, "order", order.id)
    if link is not None:
        return Result(external_ref=link.external_ref, message="Already in SAP")
    if not s.get("push_orders"):
        raise Skip("Sending orders to SAP is switched off", quiet=True)
    if order.status not in LIVE_ORDER:
        raise Skip(f"The order is {order.status.replace('_', ' ')}", quiet=True)
    if not connected_after(conn, order.confirmed_at or order.created_at):
        raise Skip("Confirmed before SAP was connected", quiet=True)
    wh = _warehouse(s, order.branch_id)
    acct = await accounts.get_settings(db, order.tenant_id)
    vat = _vat(s, acct.vat_rate)
    customer = await db.get(Customer, order.customer_id) if order.customer_id else None
    card = await ensure_partner(db, conn, client, customer)

    lines, missing = [], []
    for item in order.items:
        code = await item_code_for(db, conn, client, item.sku)
        if code is None:
            missing.append(item.sku)
            continue
        price_field = "PriceAfterVAT" if acct.prices_include_vat else "UnitPrice"
        lines.append({"ItemCode": code, "Quantity": item.quantity, price_field: float(item.unit_price),
                      "WarehouseCode": wh, "VatGroup": vat})
    if missing:
        raise SyncProblem("These products have no matching item code in SAP: " + ", ".join(missing))

    doc = await _find_doc(client, "Orders", order.order_number, card)
    if doc is None:
        doc = await client.post("Orders", {
            "CardCode": card, "DocDate": _today(), "DocDueDate": _today(), "NumAtCard": order.order_number,
            "Comments": f"From Salesman order {order.order_number}", "DocumentLines": lines,
        })
    await store.save_link(db, conn, "order", order.id, doc["DocEntry"], external_ref=str(doc["DocNum"]),
                          extra={"lines": _lines_by_sku(doc)})
    return Result(external_ref=str(doc["DocNum"]))


async def deliver_order(db: AsyncSession, conn: IntegrationConnection, client: SapClient, order: Order) -> Result:
    s = conn.settings
    link = await store.get_link(db, conn, "order", order.id)
    if link is None:
        if s.get("push_orders") and connected_after(conn, order.confirmed_at or order.created_at):
            await push_order(db, conn, client, order)
            link = await store.get_link(db, conn, "order", order.id)
        if link is None:
            raise Skip("This order isn't in SAP", quiet=True)
    if not s.get("validate_deliveries"):
        raise Skip("Creating deliveries in SAP is switched off", quiet=True)
    done = await store.get_link(db, conn, "delivery", order.id)
    if done is not None:
        return Result(external_ref=done.external_ref, message="Already delivered in SAP")
    so = await client.get(path("Orders", int(link.external_id)), {"$select": "CardCode,DocumentStatus,DocumentLines"})
    if so is None:
        raise SyncProblem(f"Sales order {link.external_ref} was not found in SAP.")
    found = await _find_doc(client, "DeliveryNotes", order.order_number, so["CardCode"])
    if found is None:
        open_lines = [ln for ln in so.get("DocumentLines") or [] if ln.get("LineStatus", "bost_Open") == "bost_Open"]
        if not open_lines:
            raise Skip("Delivered in SAP with its invoice", quiet=True)
        found = await client.post("DeliveryNotes", {
            "CardCode": so["CardCode"], "DocDate": _today(), "NumAtCard": order.order_number,
            "Comments": f"Delivered in Salesman ({order.order_number})",
            "DocumentLines": [{"BaseType": 17, "BaseEntry": int(link.external_id), "BaseLine": ln["LineNum"]}
                              for ln in open_lines],
        })
    await store.save_link(db, conn, "delivery", order.id, found["DocEntry"], external_ref=str(found["DocNum"]),
                          extra={"lines": _lines_by_sku(found)})
    return Result(external_ref=str(found["DocNum"]))


async def cancel_order(db: AsyncSession, conn: IntegrationConnection, client: SapClient, order: Order) -> Result:
    link = await store.get_link(db, conn, "order", order.id)
    if link is None:
        raise Skip("This order isn't in SAP", quiet=True)
    so = await client.get(path("Orders", int(link.external_id)), {"$select": "Cancelled,DocumentStatus"})
    if so is not None and not _yes(so.get("Cancelled")):
        await client.action(path("Orders", int(link.external_id)) + "/Cancel")
    return Result(external_ref=link.external_ref)


# ---- invoices and credit notes --------------------------------------------------------------

async def _free_lines(db, conn, client, inv: SalesInvoice, acct, wh: str | None) -> tuple[list[dict], str]:
    """Lines not copied from another document: item lines, or a service document when a line has no item."""
    s = conn.settings
    if any(not line.get("sku") for line in inv.lines or []):
        account = s.get("adjustment_account")
        if not account:
            raise SyncProblem("Choose the SAP revenue account for lines without an item under Integrations.")
        return [{"ItemDescription": str(line.get("name") or inv.number)[:100], "AccountCode": account,
                 "LineTotal": float(money(line.get("net", line.get("unit_price")))),
                 "VatGroup": _vat(s, line.get("vat_rate", acct.vat_rate))} for line in inv.lines], "dDocument_Service"
    out = []
    price_field = "PriceAfterVAT" if acct.prices_include_vat else "UnitPrice"
    for line in inv.lines or []:
        qty = Decimal(str(line["quantity"])) or Decimal(1)
        price = (Decimal(str(line["total"])) / qty) if acct.prices_include_vat else Decimal(str(line["unit_price"]))
        vals = {"Quantity": float(qty), price_field: float(price.quantize(Decimal("0.0001"))),
                "VatGroup": _vat(s, line.get("vat_rate", acct.vat_rate))}
        code = await item_code_for(db, conn, client, line.get("sku"))
        if code is None:
            raise SyncProblem(f"{line.get('sku')} has no matching item code in SAP.")
        vals["ItemCode"] = code
        if wh:
            vals["WarehouseCode"] = wh
        out.append(vals)
    return out, "dDocument_Items"


def _based_lines(inv: SalesInvoice, base_type: int, base_entry: int, base_lines: dict) -> list[dict] | None:
    """Lines copied from a base document, or None when an invoice line has no match there."""
    out = []
    for line in inv.lines or []:
        num = base_lines.get(line.get("sku"))
        if num is None:
            return None
        out.append({"BaseType": base_type, "BaseEntry": base_entry, "BaseLine": num,
                    "Quantity": float(Decimal(str(line["quantity"])))})
    return out


async def push_invoice(db: AsyncSession, conn: IntegrationConnection, client: SapClient, inv: SalesInvoice) -> Result:
    s = conn.settings
    if inv.kind not in ("invoice", "credit_note"):
        raise Skip("Opening balances stay in SAP as they are", quiet=True)
    if not s.get("push_invoices"):
        raise Skip("Sending invoices to SAP is switched off", quiet=True)
    if not connected_after(conn, inv.issued_at):
        raise Skip("Issued before SAP was connected", quiet=True)
    link = await store.get_link(db, conn, "invoice", inv.id)
    if link is not None:
        return Result(external_ref=link.external_ref, message="Already in SAP")

    acct = await accounts.get_settings(db, inv.tenant_id)
    customer = await db.get(Customer, inv.customer_id) if inv.customer_id else None
    card = await ensure_partner(db, conn, client, customer)
    refund = inv.kind == "credit_note"
    entity = "CreditNotes" if refund else "Invoices"

    doc = await _find_doc(client, entity, inv.number, card)
    if doc is None:
        lines = None
        if refund and inv.original_invoice_id:
            original = await store.get_link(db, conn, "invoice", inv.original_invoice_id)
            if original is not None:
                lines = _based_lines(inv, 13, int(original.external_id), (original.extra or {}).get("lines") or {})
        elif inv.order_id:
            order = await db.get(Order, inv.order_id)
            if await store.get_link(db, conn, "order", inv.order_id) is None and order is not None \
                    and s.get("push_orders") and order.status in LIVE_ORDER \
                    and connected_after(conn, order.confirmed_at or order.created_at):
                try:
                    await push_order(db, conn, client, order)
                except (Skip, SyncProblem):
                    pass   # the invoice still goes to SAP, just not copied from the order
            base = await store.get_link(db, conn, "delivery", inv.order_id)
            base_type = 15
            if base is None:
                base, base_type = await store.get_link(db, conn, "order", inv.order_id), 17
            if base is not None:
                lines = _based_lines(inv, base_type, int(base.external_id), (base.extra or {}).get("lines") or {})
        doc_type = "dDocument_Items"
        if lines is None:
            wh = ((s.get("branches") or {}).get(str(inv.branch_id)) or {}).get("warehouse_id") if inv.branch_id else None
            lines, doc_type = await _free_lines(db, conn, client, inv, acct, wh)
        body = {"CardCode": card, "DocDate": inv.issue_date.isoformat(), "NumAtCard": inv.number, "DocType": doc_type,
                "Comments": f"Salesman {'credit note' if refund else 'invoice'} {inv.number}", "DocumentLines": lines}
        if not refund:
            body["DocDueDate"] = inv.due_date.isoformat()
        doc = await client.post(entity, body)
    await store.save_link(db, conn, "invoice", inv.id, doc["DocEntry"], external_ref=str(doc["DocNum"]),
                          extra={"kind": inv.kind, "lines": _lines_by_sku(doc)})
    result = Result(external_ref=str(doc["DocNum"]))
    if abs(money(doc.get("DocTotal")) - money(inv.total)) > Decimal("0.005"):
        result = Result("warning", f"SAP's total is {money(doc.get('DocTotal')):.2f}, Salesman's is {money(inv.total):.2f}. "
                                   "Check the VAT group and rounding settings in SAP.", str(doc["DocNum"]))
    note = await _unapplied_note(db, conn, invoice_ids=[inv.id])
    if note and result.status == "ok":
        result = Result("warning", note, result.external_ref)
    return result


# ---- payments -------------------------------------------------------------------------------

async def _allocations(db: AsyncSession, *, payment_ids=None, invoice_ids=None) -> list[PaymentAllocation]:
    cond = []
    if payment_ids:
        cond.append(PaymentAllocation.payment_id.in_(payment_ids))
    if invoice_ids:
        cond.append(PaymentAllocation.invoice_id.in_(invoice_ids))
    if not cond:
        return []
    return list(await db.scalars(select(PaymentAllocation).where(or_(*cond)).order_by(PaymentAllocation.created_at)))


async def _unapplied_note(db, conn, **kw) -> str | None:
    """SAP applies a payment to invoices only when the payment is created. A later match needs reconciling in SAP."""
    for alloc in await _allocations(db, **kw):
        if await store.get_link(db, conn, "allocation", f"{alloc.payment_id}:{alloc.invoice_id}") is not None:
            continue
        pay = await store.get_link(db, conn, "payment", alloc.payment_id)
        if pay is not None and not (pay.extra or {}).get("voided"):
            return (f"Payment {pay.external_ref} was recorded in SAP on account before this invoice reached SAP. "
                    "Match them in SAP (Internal Reconciliation).")
    return None


async def push_payment(db: AsyncSession, conn: IntegrationConnection, client: SapClient, pay: CustomerPayment) -> Result:
    s = conn.settings
    if not s.get("push_payments"):
        raise Skip("Sending payments to SAP is switched off", quiet=True)
    if not connected_after(conn, pay.created_at):
        raise Skip("Recorded before SAP was connected", quiet=True)
    link = await store.get_link(db, conn, "payment", pay.id)
    if pay.voided_at is not None and link is None:
        raise Skip("Reversed before it was sent", quiet=True)
    if link is not None:
        return Result(external_ref=link.external_ref, message="Already in SAP")
    account = (s.get("payment_journals") or {}).get(pay.method)
    if not account:
        raise SyncProblem(f"No SAP G/L account is chosen for {pay.method.replace('_', ' ')} payments.")
    customer = await db.get(Customer, pay.customer_id) if pay.customer_id else None
    card = await ensure_partner(db, conn, client, customer)

    applied, pairs, later = [], [], 0
    for alloc in await _allocations(db, payment_ids=[pay.id]):
        inv_link = await store.get_link(db, conn, "invoice", alloc.invoice_id)
        if inv_link is None or (inv_link.extra or {}).get("kind") == "credit_note":
            later += 1
            continue
        applied.append({"DocEntry": int(inv_link.external_id), "SumApplied": float(money(alloc.amount)),
                        "InvoiceType": "it_Invoice"})
        pairs.append(f"{alloc.payment_id}:{alloc.invoice_id}")

    doc = await _find_doc(client, "IncomingPayments", pay.number, card, field="Remarks")
    if doc is None:
        body = {"CardCode": card, "DocDate": pay.paid_on.isoformat(), "Remarks": pay.number,
                "JournalRemarks": f"Salesman {pay.number}"[:50], "PaymentInvoices": applied}
        if pay.method == "cash":
            body.update({"CashAccount": account, "CashSum": float(money(pay.amount))})
        else:
            body.update({"TransferAccount": account, "TransferSum": float(money(pay.amount)),
                         "TransferDate": pay.paid_on.isoformat(), "TransferReference": pay.number[:27]})
        doc = await client.post("IncomingPayments", body)
    for pair in pairs:
        await store.save_link(db, conn, "allocation", pair, doc["DocEntry"])
    await store.save_link(db, conn, "payment", pay.id, doc["DocEntry"], external_ref=str(doc["DocNum"]))
    if later:
        return Result("warning", "Part of this payment is for invoices not yet in SAP; it was recorded on account. "
                                 "Match it in SAP (Internal Reconciliation) once they arrive.", str(doc["DocNum"]))
    return Result(external_ref=str(doc["DocNum"]))


async def void_payment(db: AsyncSession, conn: IntegrationConnection, client: SapClient, pay: CustomerPayment) -> Result:
    link = await store.get_link(db, conn, "payment", pay.id)
    if link is None:
        raise Skip("This payment isn't in SAP", quiet=True)
    if not (link.extra or {}).get("voided"):
        row = await client.get(path("IncomingPayments", int(link.external_id)), {"$select": "Cancelled"})
        if row is not None and not _yes(row.get("Cancelled")):
            await client.action(path("IncomingPayments", int(link.external_id)) + "/Cancel")
        await store.save_link(db, conn, "payment", pay.id, link.external_id, extra={"voided": True})
    return Result(external_ref=link.external_ref)


# ---- prices and stock -----------------------------------------------------------------------

async def fetch_catalog(db: AsyncSession, conn: IntegrationConnection, client: SapClient) -> catalog.Catalog:
    s = conn.settings
    if not s.get("pull_catalog"):
        raise Skip("Fetching prices and stock from SAP is switched off", quiet=True)
    items = await client.get_all(
        "Items", select="ItemCode,ItemName,ForeignName,ItemPrices,ItemWarehouseInfoCollection",
        filter="SalesItem eq 'tYES' and InventoryItem eq 'tYES' and Valid eq 'tYES'", orderby="ItemCode",
    )
    if not items:
        raise SyncProblem("SAP has no items that are sales items, inventory items and active. Nothing was changed in Salesman.")
    currency = s.get("company_currency") or "SAR"
    products, rows = [], {}
    for it in items:
        sku = str(it.get("ItemCode") or "").strip()[:64]
        if not sku:
            continue
        foreign = it.get("ForeignName")
        whs = {w.get("WarehouseCode"): w for w in it.get("ItemWarehouseInfoCollection") or []}
        costs = [Decimal(str(w.get("StandardAveragePrice") or 0)) for w in whs.values() if w.get("StandardAveragePrice")]
        rows[sku] = (it, whs)
        products.append(catalog.CatalogProduct(
            sku=sku, external_id=sku, name_en=str(it.get("ItemName") or sku)[:255],
            name_ar=str(foreign)[:255] if foreign and _ARABIC.search(str(foreign)) else None,
            cost=costs[0] if costs else None,
        ))
    cat = catalog.Catalog(products=products, cost_currency=currency,
                          empty_message="No branch is linked to a SAP warehouse.", source="SAP sync")
    default_list = s.get("sales_journal_id")
    for branch, mapping in await catalog.mapped_branches(db, conn):
        plist = mapping.get("pricelist_id") or default_list
        promised = await catalog.pending(db, conn, branch.id)
        lines, unpriced = [], 0
        for p in products:
            it, whs = rows[p.sku]
            prices = {pr.get("PriceList"): pr for pr in it.get("ItemPrices") or []}
            pr = prices.get(int(plist)) if plist else None
            if pr is None or pr.get("Price") is None:
                unpriced += 1
                continue
            wh = whs.get(str(mapping["warehouse_id"])) or {}
            free = Decimal(str(wh.get("InStock") or 0)) - Decimal(str(wh.get("Committed") or 0))
            qty = max(int(free) - promised.get(p.sku, 0), 0)
            lines.append(PriceLineIn(
                sku=p.sku, unit_price=Decimal(str(pr["Price"])).quantize(CENT), quantity=qty,
                currency=(pr.get("Currency") or currency)[:3],
                unit_cost=Decimal(str(p.cost)).quantize(CENT) if p.cost else None, name_en=p.name_en, name_ar=p.name_ar,
            ))
        cat.branches.append((branch, lines))
        if unpriced:
            cat.notes.append(f"{branch.name}: {unpriced} item(s) have no price in SAP price list {plist} and were left out.")
    return cat


async def pull_catalog(db: AsyncSession, conn: IntegrationConnection, client: SapClient) -> Result:
    return await catalog.apply(db, conn, await fetch_catalog(db, conn, client))


# ---- balances -------------------------------------------------------------------------------

async def balances(db: AsyncSession, conn: IntegrationConnection, client: SapClient) -> list[dict]:
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
        bp = await client.get(path("BusinessPartners", r.external_id), {"$select": "CurrentAccountBalance"}) or {}
        cid = uuid.UUID(r.local_key)
        theirs = money(bp.get("CurrentAccountBalance"))
        mine = ours.get(cid, Decimal("0")).quantize(CENT)
        c = customers.get(cid)
        out.append({"customer_id": cid, "name": (c.company or c.name) if c else r.external_ref, "salesman": mine,
                    "odoo": theirs, "erp": theirs, "difference": mine - theirs, "partner_id": r.external_id})
    out.sort(key=lambda x: -abs(x["difference"]))
    return out

