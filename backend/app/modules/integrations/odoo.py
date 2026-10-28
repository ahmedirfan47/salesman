"""Odoo connector.

Who owns what (the business chose this):
- Odoo owns products, prices and stock. Every few minutes each branch's price
  list and stock are refreshed from its Odoo warehouse (and price list, if one
  is chosen). Products are matched on Odoo's Internal Reference = Salesman SKU.
- Salesman owns customers, orders, invoices, credit notes and payments, and
  sends them to Odoo:
    order confirmed  -> confirmed sales order (reserves the stock in Odoo)
    order delivered  -> the sales order's delivery is validated
    order cancelled  -> the sales order is cancelled
    invoice          -> posted customer invoice, linked to the sales order lines
    credit note      -> posted credit note, matched against its invoice
    payment          -> posted customer payment, matched against the invoices
                        Salesman applied it to
    payment reversed -> the Odoo payment is cancelled
- Everything is idempotent: a record is looked up by its Salesman number
  before it is created, so a retry after a timeout never makes a duplicate.

Salesman already signs and reports invoices to ZATCA. Use an Odoo sales
journal that is not connected to ZATCA, so nothing is reported twice.
"""
import logging
import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import String, and_, cast, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import CustomerPayment, PaymentAllocation, SalesInvoice
from app.db.models.branch import Branch
from app.db.models.customer import Customer
from app.db.models.integration import IntegrationConnection, IntegrationLink
from app.db.models.inventory import Inventory
from app.db.models.order import Order
from app.db.models.order_item import OrderItem
from app.db.models.product import Product
from app.db.models.product_price import ProductPrice
from app.modules.accounts import service as accounts
from app.modules.integrations import store
from app.modules.integrations.odoo_client import OdooClient
from app.modules.pricing import service as pricing
from app.schemas.pricing import PriceLineIn, PriceListCreate

logger = logging.getLogger("salesman.integrations")

CENT = Decimal("0.01")
PAYMENT_METHODS = accounts.PAYMENT_METHODS
LIVE_ORDER = ("confirmed", "preparing", "dispatched", "delivered", "completed")
PENDING_ORDER = ("confirmed", "preparing", "dispatched")
SYNC_LABEL = "Prices and stock"


class SyncProblem(Exception):
    """Something the business has to fix (in Salesman or Odoo) before this can be sent."""


class Skip(Exception):
    """Nothing to send. quiet=True: don't even list it."""

    def __init__(self, message: str, quiet: bool = False):
        super().__init__(message)
        self.quiet = quiet


@dataclass
class Result:
    status: str = "ok"            # ok | warning
    message: str | None = None
    external_ref: str | None = None


def rate_key(rate) -> str:
    return str(Decimal(str(rate)).quantize(CENT))


def _ctx(s: dict, **extra) -> dict:
    return {"allowed_company_ids": [s["company_id"]], **extra}


def _m2o(value) -> int | None:
    return value[0] if isinstance(value, (list, tuple)) and value else (value or None)


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


# ---- discovery and settings ------------------------------------------------------------------

async def discover(client: OdooClient) -> dict:
    """Everything the mapping screen needs, read live from Odoo."""
    companies = await client.search_read("res.company", [], ["name", "currency_id", "vat"])
    warehouses = await client.search_read("stock.warehouse", [], ["name", "code", "company_id"])
    pricelists = await client.search_read("product.pricelist", [], ["name", "currency_id", "company_id"])
    journals = await client.search_read("account.journal", [["type", "in", ["sale", "bank", "cash"]]],
                                        ["name", "type", "code", "company_id"])
    taxes = await client.search_read("account.tax", [["type_tax_use", "=", "sale"], ["amount_type", "=", "percent"]],
                                     ["name", "amount", "price_include", "company_id"])
    langs = await client.search_read("res.lang", [["active", "=", True]], ["code", "name"])

    sol = await client.fields("sale.order.line")
    pay = await client.fields("account.payment")
    prod = await client.fields("product.product")
    partner = await client.fields("res.partner")
    if "is_storable" in prod:
        storable = "is_storable"
    elif "detailed_type" in prod:
        storable = "detailed_type"
    else:
        storable = "type"
    arabic = next((lang["code"] for lang in langs if lang["code"].startswith("ar")), None)
    return {
        "version": client.version, "api": client.api,
        "companies": [{"id": c["id"], "name": c["name"], "currency": (c.get("currency_id") or [0, ""])[1]} for c in companies],
        "warehouses": [{"id": w["id"], "name": w["name"], "code": w["code"], "company_id": _m2o(w["company_id"])} for w in warehouses],
        "pricelists": [{"id": p["id"], "name": p["name"], "currency": (p.get("currency_id") or [0, ""])[1],
                        "company_id": _m2o(p.get("company_id"))} for p in pricelists],
        "journals": [{"id": j["id"], "name": j["name"], "type": j["type"], "code": j["code"],
                      "company_id": _m2o(j["company_id"])} for j in journals],
        "taxes": [{"id": t["id"], "name": t["name"], "amount": t["amount"], "price_include": bool(t.get("price_include")),
                   "company_id": _m2o(t["company_id"])} for t in taxes],
        "fields": {
            "sale_line_tax": "tax_ids" if "tax_ids" in sol else "tax_id",
            "payment_memo": "memo" if "memo" in pay else "ref",
            "storable": storable,
            "partner_cr": "company_registry" if "company_registry" in partner else None,
            "partner_sa": sorted(f for f in partner if f.startswith("l10n_sa_")),
            "arabic_lang": arabic,
        },
    }


def _pick_warehouse(branch: Branch, warehouses: list[dict]) -> int | None:
    if not warehouses:
        return None
    words = {w.lower() for w in re.findall(r"\w+", f"{branch.name} {branch.city or ''}") if len(w) > 2}
    for wh in warehouses:
        if words & {w.lower() for w in re.findall(r"\w+", f"{wh['name']} {wh['code']}")}:
            return wh["id"]
    return warehouses[0]["id"]


def defaults(options: dict, branches: list[Branch], acct, current: dict | None = None) -> dict:
    """A complete first mapping, so the owner only has to check it."""
    current = dict(current or {})
    companies = options["companies"]
    company = next((c for c in companies if c["id"] == current.get("company_id")), None) \
        or next((c for c in companies if c["currency"] == acct.currency), None) or (companies[0] if companies else None)
    co = company["id"] if company else None

    def of_company(rows):
        return [r for r in rows if r.get("company_id") in (co, None)]

    journals = of_company(options["journals"])
    sale_j = next((j["id"] for j in journals if j["type"] == "sale"), None)
    cash_j = next((j["id"] for j in journals if j["type"] == "cash"), None)
    bank_j = next((j["id"] for j in journals if j["type"] == "bank"), None)
    taxes = {}
    for rate in {rate_key(acct.vat_rate), rate_key(0)}:
        match = [t for t in of_company(options["taxes"]) if rate_key(t["amount"]) == rate]
        exact = [t for t in match if t["price_include"] == bool(acct.prices_include_vat)]
        if exact or match:
            taxes[rate] = (exact or match)[0]["id"]
    warehouses = of_company(options["warehouses"])
    branch_map = dict(current.get("branches") or {})
    for b in branches:
        if str(b.id) not in branch_map and b.is_active:
            branch_map[str(b.id)] = {"warehouse_id": _pick_warehouse(b, warehouses), "pricelist_id": None}
    out = {
        "company_id": co,
        "company_currency": company["currency"] if company else acct.currency,
        "sales_journal_id": sale_j,
        "taxes": taxes,
        "payment_journals": {m: (cash_j if m == "cash" else bank_j) or cash_j or bank_j for m in PAYMENT_METHODS},
        "branches": branch_map,
        "push_orders": True,
        "validate_deliveries": True,
        "push_invoices": True,
        "push_payments": True,
        "pull_catalog": True,
        "pull_interval_minutes": 15,
        "walkin_partner_id": None,
    }
    out.update({k: v for k, v in current.items() if v is not None and k in out and k != "branches"})
    out["fields"] = options["fields"]
    return out


def problems(s: dict, branches: list[Branch], acct, options: dict | None = None) -> list[str]:
    """What must be fixed before the connection can be switched on."""
    out = []
    if not s.get("company_id"):
        out.append("Choose the Odoo company.")
    if s.get("push_invoices") and not s.get("sales_journal_id"):
        out.append("Choose the Odoo sales journal for invoices.")
    if (s.get("push_invoices") or s.get("push_orders")) and rate_key(acct.vat_rate) not in (s.get("taxes") or {}):
        out.append(f"Choose the Odoo sales tax for VAT {rate_key(acct.vat_rate)}%.")
    if options and s.get("taxes"):
        by_id = {t["id"]: t for t in options.get("taxes", [])}
        for rate, tax_id in s["taxes"].items():
            tax = by_id.get(tax_id)
            if tax and tax["price_include"] != bool(acct.prices_include_vat):
                out.append(
                    f"The Odoo tax '{tax['name']}' {'includes' if tax['price_include'] else 'excludes'} VAT, but your "
                    f"Salesman prices {'include' if acct.prices_include_vat else 'exclude'} it. Choose a matching tax."
                )
    if s.get("push_payments"):
        missing = [m for m in PAYMENT_METHODS if not (s.get("payment_journals") or {}).get(m)]
        if missing:
            out.append("Choose an Odoo journal for payments by " + ", ".join(m.replace("_", " ") for m in missing) + ".")
    unmapped = [b.name for b in branches if b.is_active and not ((s.get("branches") or {}).get(str(b.id)) or {}).get("warehouse_id")]
    if unmapped and (s.get("pull_catalog") or s.get("push_orders")):
        out.append("Choose an Odoo warehouse for: " + ", ".join(unmapped) + ".")
    return out


# ---- customers ------------------------------------------------------------------------------

async def _country_sa(client: OdooClient) -> int | None:
    rows = await client.search_read("res.country", [["code", "=", "SA"]], ["id"], limit=1)
    return rows[0]["id"] if rows else None


async def _partner_vals(client: OdooClient, s: dict, customer: Customer) -> dict:
    f = s.get("fields") or {}
    street = " ".join(x for x in (customer.building_number, customer.street) if x) or customer.address
    vals = {
        "name": customer.company or customer.name,
        "is_company": bool(customer.company or customer.vat_number or customer.cr_number),
        "phone": customer.whatsapp_number or False,
        "vat": customer.vat_number or False,
        "street": street or False,
        "street2": customer.district or False,
        "city": customer.city or False,
        "zip": customer.postal_code or False,
        "customer_rank": 1,
    }
    if customer.company and customer.name and customer.name != customer.company:
        vals["comment"] = f"Contact: {customer.name}"
    country = await _country_sa(client)
    if country:
        vals["country_id"] = country
    if f.get("partner_cr") and customer.cr_number:
        vals[f["partner_cr"]] = customer.cr_number
    sa = set(f.get("partner_sa") or [])
    if "l10n_sa_edi_building_number" in sa and customer.building_number:
        vals["l10n_sa_edi_building_number"] = customer.building_number
    if "l10n_sa_additional_identification_scheme" in sa and customer.cr_number:
        vals["l10n_sa_additional_identification_scheme"] = "CRN"
        vals["l10n_sa_additional_identification_number"] = customer.cr_number
    return vals


async def _find_partner(client: OdooClient, customer: Customer) -> int | None:
    if customer.vat_number:
        rows = await client.search_read("res.partner", [["vat", "=", customer.vat_number]], ["id"], limit=1)
        if rows:
            return rows[0]["id"]
    digits = _digits(customer.whatsapp_number)
    if len(digits) >= 9:
        rows = await client.search_read("res.partner", [["phone", "ilike", digits[-9:]]], ["id", "phone"], limit=10)
        for row in rows:
            if _digits(row.get("phone")).endswith(digits[-9:]):
                return row["id"]
    return None


async def ensure_partner(db: AsyncSession, conn: IntegrationConnection, client: OdooClient,
                         customer: Customer | None) -> int:
    s = conn.settings
    if customer is None:
        if s.get("walkin_partner_id"):
            return int(s["walkin_partner_id"])
        found = await client.search_read("res.partner", [["name", "=", "Walk-in customers (Salesman)"]], ["id"], limit=1)
        pid = found[0]["id"] if found else await client.create(
            "res.partner", {"name": "Walk-in customers (Salesman)", "customer_rank": 1, "is_company": True},
        )
        conn.settings = {**s, "walkin_partner_id": pid}
        await db.flush()
        return pid
    link = await store.get_link(db, conn, "customer", customer.id)
    if link is not None:
        return int(link.external_id)
    pid = await _find_partner(client, customer)
    if pid is None:
        pid = await client.create("res.partner", await _partner_vals(client, s, customer))
    await store.save_link(db, conn, "customer", customer.id, pid, external_ref=customer.company or customer.name)
    return pid


async def push_customer(db: AsyncSession, conn: IntegrationConnection, client: OdooClient, customer: Customer) -> Result:
    """Keep a customer already in Odoo up to date (new customers go over with their first order)."""
    link = await store.get_link(db, conn, "customer", customer.id)
    if link is None:
        raise Skip("Sent with the customer's first order or invoice", quiet=True)
    await client.write("res.partner", [int(link.external_id)], await _partner_vals(client, conn.settings, customer))
    return Result(external_ref=customer.company or customer.name)


# ---- products -------------------------------------------------------------------------------

async def product_id_for(db: AsyncSession, conn: IntegrationConnection, client: OdooClient, sku: str | None) -> int | None:
    if not sku:
        return None
    link = await store.get_link(db, conn, "product", sku)
    if link is not None:
        return int(link.external_id)
    rows = await client.search_read(
        "product.product", [["default_code", "=", sku], ["company_id", "in", [conn.settings["company_id"], False]]],
        ["id"], context=_ctx(conn.settings), limit=1,
    )
    if not rows:
        return None
    await store.save_link(db, conn, "product", sku, rows[0]["id"])
    return rows[0]["id"]


def _tax(s: dict, rate) -> int:
    tax_id = (s.get("taxes") or {}).get(rate_key(rate))
    if not tax_id:
        raise SyncProblem(f"No Odoo sales tax is chosen for VAT {rate_key(rate)}%. Choose one under Integrations.")
    return int(tax_id)


# ---- orders ---------------------------------------------------------------------------------

def _connected_after(conn: IntegrationConnection, when: datetime | None) -> bool:
    return conn.connected_at is None or when is None or when >= conn.connected_at


async def push_order(db: AsyncSession, conn: IntegrationConnection, client: OdooClient, order: Order) -> Result:
    s = conn.settings
    link = await store.get_link(db, conn, "order", order.id)
    if link is not None:
        return Result(external_ref=link.external_ref, message="Already in Odoo")
    if not s.get("push_orders"):
        raise Skip("Sending orders to Odoo is switched off", quiet=True)
    if order.status not in LIVE_ORDER:
        raise Skip(f"The order is {order.status.replace('_', ' ')}", quiet=True)
    if not _connected_after(conn, order.confirmed_at or order.created_at):
        raise Skip("Confirmed before Odoo was connected", quiet=True)
    wh = ((s.get("branches") or {}).get(str(order.branch_id)) or {}).get("warehouse_id")
    if not wh:
        raise SyncProblem("This branch isn't linked to an Odoo warehouse. Choose one under Integrations.")
    acct = await accounts.get_settings(db, order.tenant_id)
    tax = _tax(s, acct.vat_rate)
    customer = await db.get(Customer, order.customer_id) if order.customer_id else None
    partner = await ensure_partner(db, conn, client, customer)
    tax_field = (s.get("fields") or {}).get("sale_line_tax", "tax_ids")

    lines, missing = [], []
    for item in order.items:
        pid = await product_id_for(db, conn, client, item.sku)
        if pid is None:
            missing.append(item.sku)
            continue
        lines.append([0, 0, {"product_id": pid, "product_uom_qty": item.quantity, "price_unit": float(item.unit_price),
                             tax_field: [[6, 0, [tax]]], "name": item.product_name}])
    if missing:
        raise SyncProblem("These products have no matching Internal Reference in Odoo: " + ", ".join(missing))

    ctx = _ctx(s)
    found = await client.search_read("sale.order", [["client_order_ref", "=", order.order_number], ["partner_id", "=", partner],
                                                    ["state", "!=", "cancel"]], ["id", "state"], context=ctx, limit=1)
    if found:
        so_id = found[0]["id"]
        state = found[0]["state"]
    else:
        so_id = await client.create("sale.order", {
            "partner_id": partner, "company_id": s["company_id"], "warehouse_id": wh,
            "client_order_ref": order.order_number, "order_line": lines,
            "note": f"From Salesman order {order.order_number}",
        }, context=ctx)
        state = "draft"
    if state in ("draft", "sent"):
        await client.call("sale.order", "action_confirm", ids=[so_id], context=ctx)
    so = (await client.read("sale.order", [so_id], ["name", "order_line"], context=ctx))[0]
    so_lines = await client.read("sale.order.line", so["order_line"], ["product_id"], context=ctx)
    by_product = {_m2o(line["product_id"]): line["id"] for line in so_lines}
    sku_lines = {}
    for item in order.items:
        pid = await product_id_for(db, conn, client, item.sku)
        if pid in by_product:
            sku_lines[item.sku] = by_product[pid]
    await store.save_link(db, conn, "order", order.id, so_id, external_ref=so["name"], extra={"lines": sku_lines})
    return Result(external_ref=so["name"])


async def deliver_order(db: AsyncSession, conn: IntegrationConnection, client: OdooClient, order: Order) -> Result:
    s = conn.settings
    link = await store.get_link(db, conn, "order", order.id)
    if link is None:
        if s.get("push_orders") and _connected_after(conn, order.confirmed_at or order.created_at):
            await push_order(db, conn, client, order)
            link = await store.get_link(db, conn, "order", order.id)
        if link is None:
            raise Skip("This order isn't in Odoo", quiet=True)
    if not s.get("validate_deliveries"):
        raise Skip("Validating deliveries in Odoo is switched off", quiet=True)
    ctx = _ctx(s)
    so = (await client.read("sale.order", [int(link.external_id)], ["picking_ids"], context=ctx))[0]
    pickings = await client.read("stock.picking", so["picking_ids"], ["name", "state", "picking_type_code"], context=ctx)
    open_ = [p for p in pickings if p["state"] not in ("done", "cancel") and p.get("picking_type_code", "outgoing") == "outgoing"]
    wizard = False
    for p in open_:
        res = await client.call("stock.picking", "button_validate", ids=[p["id"]], context=_ctx(
            s, skip_backorder=True, picking_ids_not_to_backorder=[p["id"]], cancel_backorder=True,
            skip_sms=True, skip_expired=True, skip_immediate=True,
        ))
        wizard = wizard or isinstance(res, dict)
    after = await client.read("stock.picking", [p["id"] for p in open_], ["name", "state"], context=ctx)
    still_open = [p["name"] for p in after if p["state"] != "done"]
    if still_open or wizard:
        return Result("warning", "Validate the delivery in Odoo: " + ", ".join(still_open or [link.external_ref or ""]),
                      link.external_ref)
    return Result(external_ref=", ".join(p["name"] for p in after) or link.external_ref)


async def cancel_order(db: AsyncSession, conn: IntegrationConnection, client: OdooClient, order: Order) -> Result:
    link = await store.get_link(db, conn, "order", order.id)
    if link is None:
        raise Skip("This order isn't in Odoo", quiet=True)
    ctx = _ctx(conn.settings, disable_cancel_warning=True)
    state = (await client.read("sale.order", [int(link.external_id)], ["state"], context=ctx))[0]["state"]
    if state != "cancel":
        await client.call("sale.order", "action_cancel", ids=[int(link.external_id)], context=ctx)
    return Result(external_ref=link.external_ref)


# ---- invoices and credit notes --------------------------------------------------------------

def _price_unit(line: dict, prices_include_vat: bool) -> float:
    qty = Decimal(str(line["quantity"])) or Decimal(1)
    if prices_include_vat:
        return float((Decimal(str(line["total"])) / qty).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
    return float(Decimal(str(line["unit_price"])))


async def _move_lines(db, conn, client, inv: SalesInvoice, acct, sale_lines: dict) -> list:
    out = []
    for line in inv.lines or []:
        vals = {
            "name": str(line.get("name") or line.get("sku") or "Item")[:500],
            "quantity": float(Decimal(str(line["quantity"]))),
            "price_unit": _price_unit(line, acct.prices_include_vat),
            "tax_ids": [[6, 0, [_tax(conn.settings, line.get("vat_rate", acct.vat_rate))]]],
        }
        pid = await product_id_for(db, conn, client, line.get("sku"))
        if pid:
            vals["product_id"] = pid
        if line.get("sku") in sale_lines:
            vals["sale_line_ids"] = [[6, 0, [sale_lines[line["sku"]]]]]
        out.append([0, 0, vals])
    return out


async def _post(client: OdooClient, move_id: int, ctx: dict) -> dict:
    move = (await client.read("account.move", [move_id], ["state"], context=ctx))[0]
    if move["state"] == "draft":
        await client.call("account.move", "action_post", ids=[move_id], context=ctx)
    return (await client.read("account.move", [move_id], ["name", "state", "amount_total", "amount_residual"], context=ctx))[0]


async def push_invoice(db: AsyncSession, conn: IntegrationConnection, client: OdooClient, inv: SalesInvoice) -> Result:
    s = conn.settings
    if inv.kind not in ("invoice", "credit_note"):
        raise Skip("Opening balances stay in Odoo as they are", quiet=True)
    if not s.get("push_invoices"):
        raise Skip("Sending invoices to Odoo is switched off", quiet=True)
    if not _connected_after(conn, inv.issued_at):
        raise Skip("Issued before Odoo was connected", quiet=True)
    link = await store.get_link(db, conn, "invoice", inv.id)
    if link is not None:
        await apply_allocations(db, conn, client, invoice_ids=[inv.id])
        return Result(external_ref=link.external_ref, message="Already in Odoo")

    acct = await accounts.get_settings(db, inv.tenant_id)
    customer = await db.get(Customer, inv.customer_id) if inv.customer_id else None
    partner = await ensure_partner(db, conn, client, customer)
    ctx = _ctx(s)
    refund = inv.kind == "credit_note"
    original = await db.get(SalesInvoice, inv.original_invoice_id) if refund and inv.original_invoice_id else None
    original_link = await store.get_link(db, conn, "invoice", original.id) if original is not None else None

    sale_lines, origin = {}, None
    if inv.order_id and not refund:
        order = await db.get(Order, inv.order_id)
        order_link = await store.get_link(db, conn, "order", inv.order_id)
        if order_link is None and order is not None and s.get("push_orders") and order.status in LIVE_ORDER \
                and _connected_after(conn, order.confirmed_at or order.created_at):
            try:
                await push_order(db, conn, client, order)
            except (Skip, SyncProblem):
                pass  # the invoice still goes to Odoo, just not linked to a sales order
            order_link = await store.get_link(db, conn, "order", inv.order_id)
        if order_link is not None:
            sale_lines, origin = (order_link.extra or {}).get("lines") or {}, order_link.external_ref
    move_type = "out_refund" if refund else "out_invoice"
    found = await client.search_read("account.move", [["move_type", "=", move_type], ["ref", "=", inv.number],
                                                      ["partner_id", "=", partner], ["state", "!=", "cancel"]],
                                     ["id"], context=ctx, limit=1)
    if found:
        move_id = found[0]["id"]
    else:
        vals = {
            "move_type": move_type, "partner_id": partner, "company_id": s["company_id"], "journal_id": s["sales_journal_id"],
            "invoice_date": inv.issue_date.isoformat(), "ref": inv.number, "payment_reference": inv.number,
            "invoice_line_ids": await _move_lines(db, conn, client, inv, acct, sale_lines),
        }
        if not refund:
            vals.update({"invoice_date_due": inv.due_date.isoformat(), "invoice_payment_term_id": False})
            if origin:
                vals["invoice_origin"] = origin
        else:
            if original is not None:
                vals["invoice_origin"] = original.number
            if original_link is not None:
                vals["reversed_entry_id"] = int(original_link.external_id)
        move_id = await client.create("account.move", vals, context=ctx)
    move = await _post(client, move_id, ctx)
    await store.save_link(db, conn, "invoice", inv.id, move_id, external_ref=move["name"], extra={"kind": inv.kind})

    result = Result(external_ref=move["name"])
    if abs(Decimal(str(move["amount_total"])) - Decimal(str(inv.total))) > Decimal("0.005"):
        result = Result("warning", f"Odoo's total is {move['amount_total']:.2f}, Salesman's is {inv.total:.2f}. "
                                   "Check the tax and rounding settings in Odoo.", move["name"])
    if refund and original_link is not None:
        await _match_refund(client, ctx, move_id, int(original_link.external_id))
    await apply_allocations(db, conn, client, invoice_ids=[inv.id])
    return result


async def _receivable_lines(client: OdooClient, ctx: dict, move_id: int) -> list[dict]:
    return await client.search_read(
        "account.move.line", [["move_id", "=", move_id], ["account_id.account_type", "=", "asset_receivable"],
                              ["reconciled", "=", False]], ["id", "amount_residual"], context=ctx,
    )


async def _match_refund(client: OdooClient, ctx: dict, refund_id: int, invoice_id: int) -> None:
    """A credit note first reduces what is still owed on its invoice (as in Salesman)."""
    inv = (await client.read("account.move", [invoice_id], ["amount_residual", "state"], context=ctx))[0]
    if inv["state"] != "posted" or not inv["amount_residual"]:
        return
    lines = await _receivable_lines(client, ctx, refund_id)
    if lines:
        await client.call("account.move", "js_assign_outstanding_line", ids=[invoice_id], line_id=lines[0]["id"], context=ctx)


# ---- payments -------------------------------------------------------------------------------

async def push_payment(db: AsyncSession, conn: IntegrationConnection, client: OdooClient, pay: CustomerPayment) -> Result:
    s = conn.settings
    if not s.get("push_payments"):
        raise Skip("Sending payments to Odoo is switched off", quiet=True)
    if not _connected_after(conn, pay.created_at):
        raise Skip("Recorded before Odoo was connected", quiet=True)
    if pay.voided_at is not None and await store.get_link(db, conn, "payment", pay.id) is None:
        raise Skip("Reversed before it was sent", quiet=True)
    link = await store.get_link(db, conn, "payment", pay.id)
    if link is not None:
        await apply_allocations(db, conn, client, payment_ids=[pay.id])
        return Result(external_ref=link.external_ref, message="Already in Odoo")
    journal = (s.get("payment_journals") or {}).get(pay.method)
    if not journal:
        raise SyncProblem(f"No Odoo journal is chosen for {pay.method.replace('_', ' ')} payments.")
    customer = await db.get(Customer, pay.customer_id) if pay.customer_id else None
    partner = await ensure_partner(db, conn, client, customer)
    memo = (s.get("fields") or {}).get("payment_memo", "memo")
    ctx = _ctx(s)
    found = await client.search_read("account.payment", [[memo, "=", pay.number], ["partner_id", "=", partner]],
                                     ["id", "state"], context=ctx)
    found = [p for p in found if p["state"] not in ("cancel", "canceled", "cancelled")]
    if found:
        pay_id = found[0]["id"]
    else:
        pay_id = await client.create("account.payment", {
            "payment_type": "inbound", "partner_type": "customer", "partner_id": partner, "amount": float(pay.amount),
            "date": pay.paid_on.isoformat(), "journal_id": int(journal), memo: pay.number, "company_id": s["company_id"],
        }, context=ctx)
    row = (await client.read("account.payment", [pay_id], ["name", "state", "move_id"], context=ctx))[0]
    if row["state"] == "draft":
        await client.call("account.payment", "action_post", ids=[pay_id], context=ctx)
        row = (await client.read("account.payment", [pay_id], ["name", "state", "move_id"], context=ctx))[0]
    await store.save_link(db, conn, "payment", pay.id, pay_id, external_ref=row["name"],
                          extra={"move_id": _m2o(row.get("move_id"))})
    result = Result(external_ref=row["name"])
    unmatched = await apply_allocations(db, conn, client, payment_ids=[pay.id])
    if unmatched:
        result = Result("warning", unmatched, row["name"])
    return result


async def void_payment(db: AsyncSession, conn: IntegrationConnection, client: OdooClient, pay: CustomerPayment) -> Result:
    link = await store.get_link(db, conn, "payment", pay.id)
    if link is None:
        raise Skip("This payment isn't in Odoo", quiet=True)
    ctx = _ctx(conn.settings)
    state = (await client.read("account.payment", [int(link.external_id)], ["state"], context=ctx))[0]["state"]
    if state not in ("cancel", "canceled", "cancelled"):
        if state != "draft":
            await client.call("account.payment", "action_draft", ids=[int(link.external_id)], context=ctx)
        await client.call("account.payment", "action_cancel", ids=[int(link.external_id)], context=ctx)
    await store.save_link(db, conn, "payment", pay.id, link.external_id, extra={"voided": True})
    return Result(external_ref=link.external_ref)


async def apply_allocations(db: AsyncSession, conn: IntegrationConnection, client: OdooClient, *,
                            payment_ids: list[uuid.UUID] | None = None, invoice_ids: list[uuid.UUID] | None = None) -> str | None:
    """Match Odoo payments to the invoices Salesman applied them to. Returns a note when some can't be matched."""
    cond = []
    if payment_ids:
        cond.append(PaymentAllocation.payment_id.in_(payment_ids))
    if invoice_ids:
        cond.append(PaymentAllocation.invoice_id.in_(invoice_ids))
    if not cond:
        return None
    allocations = list(await db.scalars(
        select(PaymentAllocation).where(or_(*cond)).order_by(PaymentAllocation.created_at)
    ))
    ctx = _ctx(conn.settings)
    unmatched = 0
    for alloc in allocations:
        pair = f"{alloc.payment_id}:{alloc.invoice_id}"
        if await store.get_link(db, conn, "allocation", pair) is not None:
            continue
        pay_link = await store.get_link(db, conn, "payment", alloc.payment_id)
        inv_link = await store.get_link(db, conn, "invoice", alloc.invoice_id)
        if pay_link is None or inv_link is None or (pay_link.extra or {}).get("voided"):
            continue
        move_id = (pay_link.extra or {}).get("move_id")
        if not move_id:
            unmatched += 1
            continue
        lines = await _receivable_lines(client, ctx, int(move_id))
        if lines:
            await client.call("account.move", "js_assign_outstanding_line", ids=[int(inv_link.external_id)],
                              line_id=lines[0]["id"], context=ctx)
        await store.save_link(db, conn, "allocation", pair, lines[0]["id"] if lines else 0)
    if unmatched:
        return ("Odoo made this payment without a journal entry, so it can't be matched to its invoices "
                "automatically. Match it in Odoo, or set an outstanding receipts account on the journal.")
    return None


# ---- prices and stock -----------------------------------------------------------------------

def _storable_domain(s: dict) -> list:
    field = (s.get("fields") or {}).get("storable", "is_storable")
    if field == "is_storable":
        return [["is_storable", "=", True]]
    if field == "detailed_type":
        return [["detailed_type", "=", "product"]]
    return [["type", "=", "product"]]


async def _fixed_prices(client: OdooClient, ctx: dict, pricelist_id: int) -> tuple[dict, dict, int]:
    """Fixed prices from an Odoo price list: (by variant, by template, rules we can't follow)."""
    items = await client.search_read_all("product.pricelist.item", [["pricelist_id", "=", pricelist_id]], [
        "applied_on", "product_id", "product_tmpl_id", "compute_price", "fixed_price", "min_quantity", "date_start", "date_end",
    ], context=ctx)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    variants, templates, unsupported = {}, {}, 0
    for it in items:
        start, end = it.get("date_start"), it.get("date_end")
        if (start and str(start) > now) or (end and str(end) < now[:len(str(end))]):
            continue
        if (it.get("min_quantity") or 0) > 1:
            continue
        if it.get("compute_price") != "fixed":
            unsupported += 1
            continue
        if it["applied_on"] == "0_product_variant" and _m2o(it.get("product_id")):
            variants[_m2o(it["product_id"])] = it["fixed_price"]
        elif it["applied_on"] == "1_product" and _m2o(it.get("product_tmpl_id")):
            templates[_m2o(it["product_tmpl_id"])] = it["fixed_price"]
        else:
            unsupported += 1
    return variants, templates, unsupported


async def _pending(db: AsyncSession, conn: IntegrationConnection, branch_id: uuid.UUID) -> dict[str, int]:
    """Stock Salesman has promised that Odoo doesn't know about yet (orders not sent so far)."""
    sent = exists().where(and_(
        IntegrationLink.connection_id == conn.id, IntegrationLink.entity == "order",
        IntegrationLink.local_key == cast(Order.id, String),
    ))
    q = (
        select(OrderItem.sku, func.sum(OrderItem.quantity))
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.tenant_id == conn.tenant_id, Order.branch_id == branch_id, Order.status.in_(PENDING_ORDER), ~sent)
        .group_by(OrderItem.sku)
    )
    if conn.connected_at is not None:
        q = q.where(Order.confirmed_at >= conn.connected_at)
    return {sku: int(qty or 0) for sku, qty in await db.execute(q)}


async def _apply_branch(db: AsyncSession, conn: IntegrationConnection, branch: Branch, lines: list[PriceLineIn]) -> dict:
    rows = await db.execute(
        select(Product.sku, ProductPrice.unit_price, ProductPrice.currency)
        .join(ProductPrice, ProductPrice.product_id == Product.id)
        .where(ProductPrice.tenant_id == conn.tenant_id, ProductPrice.branch_id == branch.id, ProductPrice.effective_to.is_(None))
    )
    current = {sku: (Decimal(str(price)).quantize(CENT), cur) for sku, price, cur in rows}
    wanted = {ln.sku: (Decimal(str(ln.unit_price)).quantize(CENT), ln.currency) for ln in lines}
    if current != wanted:
        plist = await pricing.create_price_list(db, conn.tenant_id, PriceListCreate(source_filename="Odoo sync", lines=lines),
                                                branch_id=branch.id)
        await pricing.activate_price_list(db, conn.tenant_id, plist.id)
        return {"prices_changed": True, "stock_changed": len(lines)}
    stock = {pid: qty for pid, qty in await db.execute(
        select(Inventory.product_id, Inventory.quantity_on_hand).where(
            Inventory.tenant_id == conn.tenant_id, Inventory.branch_id == branch.id)
    )}
    products = {p.sku: p for p in await db.scalars(
        select(Product).where(Product.tenant_id == conn.tenant_id, Product.sku.in_(list(wanted)))
    )}
    changed = 0
    for ln in lines:
        product = products.get(ln.sku)
        if product is not None and stock.get(product.id, 0) != ln.quantity:
            await pricing._set_inventory(db, tenant_id=conn.tenant_id, branch_id=branch.id, product_id=product.id,
                                         new_quantity=ln.quantity, reason="erp_sync")
            changed += 1
    await db.commit()
    return {"prices_changed": False, "stock_changed": changed}


async def pull_catalog(db: AsyncSession, conn: IntegrationConnection, client: OdooClient) -> Result:
    s = conn.settings
    if not s.get("pull_catalog"):
        raise Skip("Fetching prices and stock from Odoo is switched off", quiet=True)
    ctx = _ctx(s, lang="en_US")
    domain = [["sale_ok", "=", True], ["default_code", "!=", False], ["company_id", "in", [s["company_id"], False]],
              *_storable_domain(s)]
    meta = await client.search_read_all("product.product", domain,
                                        ["default_code", "name", "lst_price", "standard_price", "product_tmpl_id"], context=ctx)
    if not meta:
        raise SyncProblem("Odoo has no products that can be sold, track stock and have an Internal Reference. "
                          "Nothing was changed in Salesman.")
    arabic = {}
    if (s.get("fields") or {}).get("arabic_lang"):
        for row in await client.search_read_all("product.product", domain, ["default_code", "name"],
                                                context={**ctx, "lang": s["fields"]["arabic_lang"]}):
            arabic[row["id"]] = row["name"]

    by_sku, duplicates = {}, []
    for row in meta:
        sku = str(row["default_code"]).strip()[:64]
        if not sku:
            continue
        if sku in by_sku:
            duplicates.append(sku)
            continue
        by_sku[sku] = row

    # products: names and costs follow Odoo
    existing = {p.sku: p for p in await db.scalars(
        select(Product).where(Product.tenant_id == conn.tenant_id, Product.sku.in_(list(by_sku)))
    )}
    for sku, row in by_sku.items():
        product = existing.get(sku)
        name_ar = arabic.get(row["id"])
        if product is not None:
            product.name_en = str(row["name"])[:255]
            if name_ar and name_ar != row["name"]:
                product.name_ar = str(name_ar)[:255]
            if row.get("standard_price"):
                product.cost_price = Decimal(str(row["standard_price"])).quantize(CENT)
                product.cost_currency = s.get("company_currency")
            product.is_active = True
        link = await store.get_link(db, conn, "product", sku)
        if link is None or link.external_id != str(row["id"]):
            await store.save_link(db, conn, "product", sku, row["id"], external_ref=row["name"])
    await db.commit()

    branches = {b.id: b for b in await db.scalars(select(Branch).where(Branch.tenant_id == conn.tenant_id, Branch.is_active.is_(True)))}
    summary, notes = [], []
    for branch_id, mapping in (s.get("branches") or {}).items():
        branch = branches.get(uuid.UUID(branch_id))
        if branch is None or not (mapping or {}).get("warehouse_id"):
            continue
        bctx = _ctx(s, warehouse_id=int(mapping["warehouse_id"]), warehouse=int(mapping["warehouse_id"]))
        stock = {r["id"]: r.get("free_qty", 0) for r in await client.search_read_all("product.product", domain, ["free_qty"], context=bctx)}
        currency = s.get("company_currency") or "SAR"
        variants, templates, unsupported = {}, {}, 0
        if mapping.get("pricelist_id"):
            variants, templates, unsupported = await _fixed_prices(client, ctx, int(mapping["pricelist_id"]))
            pl = await client.read("product.pricelist", [int(mapping["pricelist_id"])], ["currency_id"], context=ctx)
            if pl and pl[0].get("currency_id"):
                currency = pl[0]["currency_id"][1]
        pending = await _pending(db, conn, branch.id)
        lines = []
        for sku, row in by_sku.items():
            price = variants.get(row["id"], templates.get(_m2o(row.get("product_tmpl_id")), row["lst_price"]))
            qty = max(int(math.floor(stock.get(row["id"], 0) or 0)) - pending.get(sku, 0), 0)
            lines.append(PriceLineIn(
                sku=sku, unit_price=Decimal(str(price)).quantize(CENT), quantity=qty, currency=currency[:3],
                unit_cost=Decimal(str(row["standard_price"])).quantize(CENT) if row.get("standard_price") else None,
                name_en=str(row["name"])[:255], name_ar=(str(arabic[row["id"]])[:255] if arabic.get(row["id"]) else None),
            ))
        applied = await _apply_branch(db, conn, branch, lines)
        summary.append({"branch": branch.name, "products": len(lines), **applied})
        if unsupported:
            notes.append(f"{branch.name}: {unsupported} price rule(s) in the Odoo price list use percentages, formulas "
                         "or categories; those products use their sales price.")
    if duplicates:
        notes.append("Several Odoo products share the Internal Reference " + ", ".join(sorted(set(duplicates))[:10])
                     + "; only the first was used.")
    message = "; ".join(
        f"{x['branch']}: {x['products']} products, " + ("prices updated" if x["prices_changed"] else f"{x['stock_changed']} stock change(s)")
        for x in summary
    ) or "No branch is linked to an Odoo warehouse."
    return Result("warning" if notes else "ok", " ".join([message + "."] + notes))


# ---- balances -------------------------------------------------------------------------------

async def balances(db: AsyncSession, conn: IntegrationConnection, client: OdooClient) -> list[dict]:
    rows = list(await db.scalars(
        select(IntegrationLink).where(IntegrationLink.connection_id == conn.id, IntegrationLink.entity == "customer")
    ))
    if not rows:
        return []
    ids = [uuid.UUID(r.local_key) for r in rows]
    ours = await accounts._balances(db, conn.tenant_id, ids)
    customers = {c.id: c for c in await db.scalars(select(Customer).where(Customer.id.in_(ids)))}
    partners = {p["id"]: p for p in await client.read("res.partner", [int(r.external_id) for r in rows], ["credit"],
                                                      context=_ctx(conn.settings))}
    out = []
    for r in rows:
        cid = uuid.UUID(r.local_key)
        odoo = Decimal(str((partners.get(int(r.external_id)) or {}).get("credit") or 0)).quantize(CENT)
        mine = ours.get(cid, Decimal("0")).quantize(CENT)
        c = customers.get(cid)
        out.append({"customer_id": cid, "name": (c.company or c.name) if c else r.external_ref, "salesman": mine,
                    "odoo": odoo, "difference": mine - odoo, "partner_id": int(r.external_id)})
    out.sort(key=lambda x: -abs(x["difference"]))
    return out