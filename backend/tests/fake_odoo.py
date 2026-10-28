"""An in-memory Odoo for tests: just enough of JSON-2 and JSON-RPC, sales, stock and accounting.

It behaves like the real thing where the connector depends on it (checked
against Odoo 19 with tests/test_odoo_live.py): confirming a sales order
reserves stock, validating its delivery takes the stock out, posting an
invoice or a payment creates a receivable line, js_assign_outstanding_line
matches the smaller of the two open amounts, cancelling a payment undoes its
matches, and a partner's `credit` is what is still owed.
"""
import json
from collections import defaultdict
from decimal import Decimal

import httpx

KEY = "test-api-key"


def q2(x) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01")))


class FakeOdoo:
    def __init__(self, version: int = 19):
        self.version = version
        self.down = False                 # True: every request fails to connect
        self.redirect_to: str | None = None   # set: every request is redirected there
        self.calls: list[tuple[str, str]] = []
        self.db: dict[str, dict[int, dict]] = defaultdict(dict)
        self.seq = defaultdict(int)
        self.stock: dict[tuple[int, int], float] = defaultdict(float)      # (warehouse, product) -> on hand
        self.reserved: dict[tuple[int, int], float] = defaultdict(float)
        self.matches: list[dict] = []     # {line, invoice, amount}
        self._seed()

    # ---- data -------------------------------------------------------------------------------
    def add(self, model: str, **vals) -> int:
        self.seq[model] += 1
        rid = self.seq[model]
        self.db[model][rid] = {"id": rid, **vals}
        return rid

    def _seed(self):
        sa = self.add("res.country", code="SA", name="Saudi Arabia")
        self.country_sa = sa
        self.company = self.add("res.company", name="Al Rayyan Fresh Trading", currency_id=[1, "SAR"], vat="300000000000003")
        self.wh_ruh = self.add("stock.warehouse", name="Riyadh Warehouse", code="RUH", company_id=[self.company, "x"])
        self.wh_jed = self.add("stock.warehouse", name="Jeddah Warehouse", code="JED", company_id=[self.company, "x"])
        self.sales_journal = self.add("account.journal", name="Sales", type="sale", code="INV", company_id=[self.company, "x"])
        self.bank = self.add("account.journal", name="Bank", type="bank", code="BNK1", company_id=[self.company, "x"])
        self.cash = self.add("account.journal", name="Cash", type="cash", code="CSH1", company_id=[self.company, "x"])
        self.tax15 = self.add("account.tax", name="15%", amount=15.0, price_include=False, company_id=[self.company, "x"],
                              type_tax_use="sale", amount_type="percent")
        self.tax0 = self.add("account.tax", name="0% Exports", amount=0.0, price_include=False, company_id=[self.company, "x"],
                             type_tax_use="sale", amount_type="percent")
        self.add("res.lang", code="en_US", name="English", active=True)
        self.add("res.lang", code="ar_001", name="Arabic", active=True)
        self.products = {}
        for sku, en, ar, price, cost, ruh, jed in [
            ("TOM-5", "Tomatoes 5 kg", "طماطم 5 كجم", 100.0, 62.5, 120, 40),
            ("MAN-4", "Mangoes 4 kg", "مانجو 4 كجم", 40.0, 25.0, 300, 0),
            ("CUC-10", "Cucumbers 10 kg", "خيار 10 كجم", 55.5, 30.0, 0, 15),
        ]:
            tmpl = self.add("product.template", name=en)
            pid = self.add("product.product", default_code=sku, name=en, name_ar=ar, lst_price=price, standard_price=cost,
                           sale_ok=True, is_storable=True, type="consu", company_id=False, product_tmpl_id=[tmpl, en], active=True)
            self.products[sku] = pid
            self.stock[(self.wh_ruh, pid)] = ruh
            self.stock[(self.wh_jed, pid)] = jed
        self.add("product.product", default_code=False, name="No code item", lst_price=9.0, standard_price=0, sale_ok=True,
                 is_storable=True, type="consu", company_id=False, product_tmpl_id=[99, "x"], active=True)
        self.add("product.product", default_code="SRV-1", name="Delivery fee", lst_price=10.0, standard_price=0, sale_ok=True,
                 is_storable=False, type="service", company_id=False, product_tmpl_id=[98, "x"], active=True)
        self.pricelist = self.add("product.pricelist", name="Jeddah prices", currency_id=[1, "SAR"], company_id=False)
        self.add("product.pricelist.item", pricelist_id=[self.pricelist, "x"], applied_on="0_product_variant",
                 product_id=[self.products["TOM-5"], "x"], product_tmpl_id=False, compute_price="fixed", fixed_price=95.0,
                 min_quantity=0.0, date_start=False, date_end=False)
        self.add("product.pricelist.item", pricelist_id=[self.pricelist, "x"], applied_on="3_global", product_id=False,
                 product_tmpl_id=False, compute_price="percentage", fixed_price=0, min_quantity=0.0, date_start=False, date_end=False)

    # ---- helpers ----------------------------------------------------------------------------
    def _value(self, model: str, rec: dict, field: str, ctx: dict):
        if model == "product.product" and field == "free_qty":
            wh = ctx.get("warehouse_id") or ctx.get("warehouse")
            whs = [wh] if wh else [self.wh_ruh, self.wh_jed]
            return sum(self.stock[(w, rec["id"])] - self.reserved[(w, rec["id"])] for w in whs)
        if model == "product.product" and field == "name" and str(ctx.get("lang", "")).startswith("ar"):
            return rec.get("name_ar") or rec["name"]
        if model == "res.partner" and field == "credit":
            return q2(sum(line["amount_residual"] for line in self.db["account.move.line"].values()
                          if line["partner_id"] == rec["id"] and line["live"]))
        if field == "account_id.account_type":
            return "asset_receivable"
        return rec.get(field, False)

    def _match(self, model, rec, leaf, ctx) -> bool:
        field, op, value = leaf
        have = self._value(model, rec, field, ctx)
        if isinstance(have, list) and have and isinstance(have[0], int) and field.endswith("_id"):
            have = have[0]
        if op == "=":
            return have == value
        if op == "!=":
            return have != value
        if op == "in":
            return have in value
        if op == "ilike":
            return str(value).lower() in str(have or "").lower()
        raise AssertionError(f"fake odoo: unsupported operator {op}")

    def search(self, model, domain, ctx) -> list[dict]:
        return [r for r in self.db[model].values() if all(self._match(model, r, leaf, ctx) for leaf in domain)]

    def _out(self, model, rec, fields, ctx):
        return {"id": rec["id"], **{f: self._value(model, rec, f, ctx) for f in fields if f != "id"}}

    def credit(self, partner_id: int) -> float:
        return self._value("res.partner", {"id": partner_id}, "credit", {})

    # ---- methods ----------------------------------------------------------------------------
    def execute(self, model: str, method: str, ids, ctx: dict, kw: dict):
        self.calls.append((model, method))
        if method == "context_get":
            return {"lang": "en_US", "uid": 2}
        if method == "fields_get":
            fields = {"sale.order.line": ["tax_ids", "product_id"], "account.payment": ["memo"],
                      "product.product": ["is_storable", "free_qty"], "res.partner": ["vat", "company_registry"]}.get(model, [])
            return {f: {"type": "char"} for f in fields}
        if method == "search_read":
            rows = self.search(model, kw.get("domain", []), ctx)
            rows = rows[kw.get("offset", 0):]
            if kw.get("limit"):
                rows = rows[: kw["limit"]]
            return [self._out(model, r, kw.get("fields", []), ctx) for r in rows]
        if method == "read":
            return [self._out(model, self.db[model][i], kw.get("fields", []), ctx) for i in ids if i in self.db[model]]
        if method == "create":
            return [self._create(model, vals) for vals in kw["vals_list"]]
        if method == "write":
            for i in ids:
                self.db[model][i].update(kw["vals"])
            return True
        handler = getattr(self, f"m_{model.replace('.', '_')}_{method}", None)
        if handler is None:
            raise AssertionError(f"fake odoo: {model}.{method} not implemented")
        return handler(ids, ctx, kw)

    def _create(self, model, vals):
        vals = dict(vals)
        if model == "sale.order":
            lines = vals.pop("order_line", [])
            so = self.add(model, state="draft", name=f"S{self.seq[model] + 1:05d}", picking_ids=[], order_line=[], **vals)
            for _, _, lv in lines:
                lid = self.add("sale.order.line", order_id=so, qty_invoiced=0.0, qty_delivered=0.0,
                               product_id=[lv["product_id"], "x"], **{k: v for k, v in lv.items() if k != "product_id"})
                self.db[model][so]["order_line"].append(lid)
            return so
        if model == "account.move":
            lines = vals.pop("invoice_line_ids", [])
            untaxed = tax = 0.0
            for _, _, lv in lines:
                sub = q2(lv["quantity"] * lv["price_unit"])
                rate = sum(self.db["account.tax"][t]["amount"] for t in lv["tax_ids"][0][2])
                untaxed, tax = untaxed + sub, tax + q2(sub * rate / 100)
                for sol in (lv.get("sale_line_ids") or [[6, 0, []]])[0][2]:
                    self.db["sale.order.line"][sol]["qty_invoiced"] += lv["quantity"]
            total = q2(untaxed + tax)
            return self.add(model, state="draft", name="/", amount_untaxed=q2(untaxed), amount_tax=q2(tax), amount_total=total,
                            amount_residual=total, payment_state="not_paid", lines=lines, **vals)
        if model == "account.payment":
            return self.add(model, state="draft", name="/", move_id=False, **vals)
        if model == "res.partner":
            return self.add(model, **vals)
        raise AssertionError(f"fake odoo: create on {model} not implemented")

    def _receivable(self, move_id, partner, amount):
        return self.add("account.move.line", move_id=move_id, partner_id=partner, amount_residual=q2(amount),
                        reconciled=False, live=True)

    def m_sale_order_action_confirm(self, ids, ctx, kw):
        for i in ids:
            so = self.db["sale.order"][i]
            so["state"] = "sale"
            wh = so["warehouse_id"]
            moves = []
            for lid in so["order_line"]:
                line = self.db["sale.order.line"][lid]
                pid = line["product_id"][0]
                free = self.stock[(wh, pid)] - self.reserved[(wh, pid)]
                take = max(min(line["product_uom_qty"], free), 0)
                self.reserved[(wh, pid)] += take
                moves.append({"product": pid, "qty": take, "line": lid})
            pk = self.add("stock.picking", name=f"{'RUH' if wh == self.wh_ruh else 'JED'}/OUT/{self.seq['stock.picking'] + 1:05d}",
                          state="assigned", picking_type_code="outgoing", warehouse=wh, moves=moves, sale_id=i)
            so["picking_ids"].append(pk)
        return True

    def m_stock_picking_button_validate(self, ids, ctx, kw):
        for i in ids:
            pk = self.db["stock.picking"][i]
            for mv in pk["moves"]:
                self.reserved[(pk["warehouse"], mv["product"])] -= mv["qty"]
                self.stock[(pk["warehouse"], mv["product"])] -= mv["qty"]
                self.db["sale.order.line"][mv["line"]]["qty_delivered"] += mv["qty"]
            pk["state"] = "done"
        return True

    def m_sale_order_action_cancel(self, ids, ctx, kw):
        for i in ids:
            so = self.db["sale.order"][i]
            for pk_id in so["picking_ids"]:
                pk = self.db["stock.picking"][pk_id]
                if pk["state"] == "done":
                    raise FakeError("odoo.exceptions.UserError", "You cannot cancel an order that has been delivered.")
                for mv in pk["moves"]:
                    self.reserved[(pk["warehouse"], mv["product"])] -= mv["qty"]
                pk["state"] = "cancel"
            so["state"] = "cancel"
        return True

    def m_account_move_action_post(self, ids, ctx, kw):
        for i in ids:
            mv = self.db["account.move"][i]
            if mv["state"] != "draft":
                raise FakeError("odoo.exceptions.UserError", f"The entry {mv['name']} (id {i}) must be in draft.")
            refund = mv["move_type"] == "out_refund"
            mv["state"] = "posted"
            mv["name"] = f"{'RINV' if refund else 'INV'}/2026/{i:05d}"
            self._receivable(i, mv["partner_id"], -mv["amount_total"] if refund else mv["amount_total"])
        return False

    def m_account_payment_action_post(self, ids, ctx, kw):
        for i in ids:
            p = self.db["account.payment"][i]
            p["state"] = "in_process"
            p["name"] = f"P{'BNK' if p['journal_id'] == self.bank else 'CSH'}1/2026/{i:05d}"
            move = self.add("account.move", state="posted", name=p["name"], move_type="entry", amount_total=p["amount"],
                            amount_residual=0, partner_id=p["partner_id"])
            p["move_id"] = [move, p["name"]]
            self._receivable(move, p["partner_id"], -p["amount"])
        return None

    def m_account_move_js_assign_outstanding_line(self, ids, ctx, kw):
        inv = self.db["account.move"][ids[0]]
        line = self.db["account.move.line"][kw["line_id"]]
        inv_line = next(r for r in self.db["account.move.line"].values() if r["move_id"] == inv["id"])
        amount = q2(min(inv["amount_residual"], -line["amount_residual"]))
        if amount <= 0:
            return None
        inv["amount_residual"] = q2(inv["amount_residual"] - amount)
        inv_line["amount_residual"] = q2(inv_line["amount_residual"] - amount)
        line["amount_residual"] = q2(line["amount_residual"] + amount)
        line["reconciled"] = line["amount_residual"] == 0
        inv["payment_state"] = "paid" if inv["amount_residual"] == 0 else "partial"
        self.matches.append({"line": line["id"], "invoice": inv["id"], "amount": amount})
        return None

    def m_account_payment_action_draft(self, ids, ctx, kw):
        for i in ids:
            p = self.db["account.payment"][i]
            move = p["move_id"][0]
            for line in [r for r in self.db["account.move.line"].values() if r["move_id"] == move]:
                for m in [m for m in self.matches if m["line"] == line["id"]]:
                    inv = self.db["account.move"][m["invoice"]]
                    inv_line = next(r for r in self.db["account.move.line"].values() if r["move_id"] == inv["id"])
                    inv["amount_residual"] = q2(inv["amount_residual"] + m["amount"])
                    inv_line["amount_residual"] = q2(inv_line["amount_residual"] + m["amount"])
                    inv["payment_state"] = "partial" if inv["amount_residual"] < inv["amount_total"] else "not_paid"
                    self.matches.remove(m)
                line["live"] = False
            p["state"] = "draft"
        return None

    def m_account_payment_action_cancel(self, ids, ctx, kw):
        for i in ids:
            self.db["account.payment"][i]["state"] = "canceled"
        return None

    # ---- transport --------------------------------------------------------------------------
    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        if self.redirect_to:
            return httpx.Response(301, headers={"location": self.redirect_to})
        path = request.url.path
        if path == "/web/version":
            if self.version < 19:
                return httpx.Response(404, text="Not Found")
            return httpx.Response(200, json={"version": f"{self.version}.0", "version_info": [self.version, 0, 0, "final", 0, ""]})
        if path.startswith("/json/2/"):
            if self.version < 19:
                return httpx.Response(404, text="Not Found")
            if request.headers.get("authorization") != f"bearer {KEY}":
                return httpx.Response(401, json={"name": "werkzeug.exceptions.Unauthorized", "message": "Invalid apikey"})
            _, _, _, model, method = path.split("/")
            body = json.loads(request.content or b"{}")
            ids, ctx = body.pop("ids", None), body.pop("context", {}) or {}
            try:
                result = self.execute(model, method, ids, ctx, body)
                return httpx.Response(200, content=json.dumps(result), headers={"Content-Type": "application/json"})
            except FakeError as exc:
                return httpx.Response(422, json={"name": exc.name, "message": exc.message})
        if path == "/jsonrpc":
            params = json.loads(request.content)["params"]
            try:
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": self._rpc(params)})
            except FakeError as exc:
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {
                    "code": 200, "message": "Odoo Server Error", "data": {"name": exc.name, "message": exc.message}}})
        return httpx.Response(404, text="Not Found")

    def _rpc(self, params):
        service, method, args = params["service"], params["method"], params["args"]
        if service == "common" and method == "version":
            return {"server_version": f"{self.version}.0", "server_version_info": [self.version, 0, 0, "final", 0, ""]}
        if service == "common" and method == "authenticate":
            db, login, key, _ = args
            return 2 if key == KEY and login == "admin" else False
        db, uid, key, model, method, pos, kw = args
        if key != KEY:
            raise FakeError("odoo.exceptions.AccessDenied", "Access Denied")
        kw = dict(kw)
        ctx = kw.pop("context", {}) or {}
        if method == "create":
            kw = {"vals_list": pos[0]}
            return self.execute(model, method, None, ctx, kw)
        ids = pos[0] if pos else None
        return self.execute(model, method, ids, ctx, kw)


class FakeError(Exception):
    def __init__(self, name, message):
        super().__init__(message)
        self.name, self.message = name, message