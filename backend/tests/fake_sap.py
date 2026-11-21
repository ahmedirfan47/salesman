"""An in-memory SAP Business One Service Layer, just big enough for the connector tests.

It keeps items with per-warehouse stock (InStock / Committed), price lists,
VAT groups, business partners with balances, and the documents the connector
creates (sales orders, deliveries, invoices, credit memos, incoming payments),
copying base-document lines and moving stock and balances the way SAP does.
"""
import itertools
import json
import re
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

DB, USER, PASSWORD = "SBOACME", "manager", "s3cret"
RATES = {"S1": 15.0, "X0": 0.0}

_term = re.compile(r"^\s*(?:contains\((\w+),\s*'((?:[^']|'')*)'\)|(\w+)\s+eq\s+(?:'((?:[^']|'')*)'|(-?\d+(?:\.\d+)?)))\s*$")


def _matches(row: dict, expr: str | None) -> bool:
    if not expr:
        return True
    for part in re.split(r"\s+and\s+(?=(?:[^']*'[^']*')*[^']*$)", expr):
        m = _term.match(part)
        if not m:
            raise ValueError(f"unsupported filter {part!r}")
        if m.group(1):
            if m.group(2).replace("''", "'") not in str(row.get(m.group(1)) or ""):
                return False
        else:
            want = m.group(4).replace("''", "'") if m.group(4) is not None else float(m.group(5))
            have = row.get(m.group(3))
            if isinstance(want, float):
                if have is None or float(have) != want:
                    return False
            elif str(have) != want:
                return False
    return True


class FakeSap:
    def __init__(self):
        self.down = False
        self.sessions: set[str] = set()
        self.logins = 0
        self.expire_next = False
        self.page = 2
        self._ids = itertools.count(1)
        self.warehouses = {"RUH01": "Riyadh Main", "JED01": "Jeddah Store"}
        self.items = {}
        for code, name, foreign, prices, stock in (
            ("TOM-5", "Tomatoes 5kg box", "طماطم ٥ كجم", {1: 100.0, 2: 92.0}, {"RUH01": 120, "JED01": 40}),
            ("ONI-10", "Onions 10kg sack", None, {1: 55.0, 2: 50.0}, {"RUH01": 80, "JED01": 0}),
            ("POT-10", "Potatoes 10kg", None, {1: 48.0}, {"RUH01": 60, "JED01": 15}),
        ):
            self.items[code] = {
                "ItemCode": code, "ItemName": name, "ForeignName": foreign, "SalesItem": "tYES", "InventoryItem": "tYES",
                "Valid": "tYES",
                "ItemPrices": [{"PriceList": pl, "Price": p, "Currency": "SAR"} for pl, p in prices.items()],
                "ItemWarehouseInfoCollection": [
                    {"WarehouseCode": wh, "InStock": q, "Committed": 0, "StandardAveragePrice": 70.0}
                    for wh, q in stock.items()
                ],
            }
        self.partners: dict[str, dict] = {}
        self.docs: dict[str, dict[int, dict]] = {k: {} for k in
                                                 ("Orders", "DeliveryNotes", "Invoices", "CreditNotes", "IncomingPayments")}

    # ---- helpers ----------------------------------------------------------------------------
    def _wh(self, code: str, wh: str) -> dict:
        return next(w for w in self.items[code]["ItemWarehouseInfoCollection"] if w["WarehouseCode"] == wh)

    def stock(self, code: str, wh: str) -> tuple[float, float]:
        w = self._wh(code, wh)
        return w["InStock"], w["Committed"]

    @staticmethod
    def _err(status: int, message: str, code: int = -1) -> httpx.Response:
        return httpx.Response(status, json={"error": {"code": code, "message": {"lang": "en-us", "value": message}}})

    def _rows(self, entity: str) -> list[dict]:
        if entity == "Items":
            return list(self.items.values())
        if entity == "BusinessPartners":
            return list(self.partners.values())
        if entity == "Warehouses":
            return [{"WarehouseCode": k, "WarehouseName": v, "Inactive": "tNO"} for k, v in self.warehouses.items()]
        if entity == "PriceLists":
            return [{"PriceListNo": 1, "PriceListName": "Retail", "DefaultPrimeCurrency": "SAR"},
                    {"PriceListNo": 2, "PriceListName": "Wholesale", "DefaultPrimeCurrency": "SAR"}]
        if entity == "VatGroups":
            return [{"Code": k, "Name": f"Output VAT {int(v)}%", "Category": "bovcOutputTax", "Inactive": "tNO",
                     "VatGroups_Lines": [{"Effectivefrom": "2020-07-01", "Rate": v}]} for k, v in RATES.items()] + \
                   [{"Code": "I1", "Name": "Input VAT", "Category": "bovcInputTax", "Inactive": "tNO", "VatGroups_Lines": []}]
        if entity == "ChartOfAccounts":
            return [{"Code": "_SYS00000000011", "Name": "Cash on hand", "CashAccount": "tYES", "ActiveAccount": "tYES",
                     "AccountType": "at_Other"},
                    {"Code": "_SYS00000000012", "Name": "Al Rajhi Bank", "CashAccount": "tYES", "ActiveAccount": "tYES",
                     "AccountType": "at_Other"},
                    {"Code": "_SYS00000000401", "Name": "Sales returns and allowances", "CashAccount": "tNO",
                     "ActiveAccount": "tYES", "AccountType": "at_Revenues"}]
        return list(self.docs[entity].values())

    # ---- documents --------------------------------------------------------------------------
    def _line_from_base(self, line: dict) -> dict:
        base_entity = {17: "Orders", 15: "DeliveryNotes", 13: "Invoices"}[line["BaseType"]]
        base = self.docs[base_entity][line["BaseEntry"]]
        src = next(ln for ln in base["DocumentLines"] if ln["LineNum"] == line["BaseLine"])
        qty = line.get("Quantity", src["Quantity"])
        if base_entity in ("Orders", "DeliveryNotes"):
            src["LineStatus"] = "bost_Close"
        return {"ItemCode": src["ItemCode"], "Quantity": qty, "Price": src["Price"], "VatGroup": src["VatGroup"],
                "WarehouseCode": src.get("WarehouseCode"), "BaseType": line["BaseType"], "BaseEntry": line["BaseEntry"],
                "BaseLine": line["BaseLine"]}

    def _create(self, entity: str, body: dict) -> httpx.Response:
        card = body.get("CardCode")
        if card not in self.partners:
            return self._err(400, f"Invalid BP code '{card}'")
        entry = next(self._ids)
        doc = {**body, "DocEntry": entry, "DocNum": 1000 + entry, "Cancelled": "tNO", "DocumentStatus": "bost_Open"}
        if entity == "IncomingPayments":
            total = float(body.get("CashSum") or 0) + float(body.get("TransferSum") or 0)
            if not (body.get("CashAccount") or body.get("TransferAccount")):
                return self._err(400, "Specify the cash or transfer account")
            for pi in body.get("PaymentInvoices") or []:
                inv = self.docs["Invoices"][pi["DocEntry"]]
                inv["PaidToDate"] = inv.get("PaidToDate", 0) + pi["SumApplied"]
            doc["DocTotal"] = total
            self.partners[card]["CurrentAccountBalance"] -= total
            self.docs[entity][entry] = doc
            return httpx.Response(201, json=doc)
        lines = []
        for i, line in enumerate(body.get("DocumentLines") or []):
            if "BaseType" in line:
                ln = self._line_from_base(line)
            elif body.get("DocType") == "dDocument_Service":
                if not line.get("AccountCode"):
                    return self._err(400, "Specify a G/L account for service lines")
                ln = {"ItemCode": None, "Quantity": 1, "Price": line["LineTotal"], "VatGroup": line["VatGroup"],
                      "AccountCode": line["AccountCode"], "ItemDescription": line.get("ItemDescription")}
            else:
                if line["ItemCode"] not in self.items:
                    return self._err(400, f"Item '{line['ItemCode']}' not found")
                rate = RATES[line["VatGroup"]] / 100
                price = line["UnitPrice"] if "UnitPrice" in line else line["PriceAfterVAT"] / (1 + rate)
                ln = {"ItemCode": line["ItemCode"], "Quantity": line["Quantity"], "Price": round(price, 4),
                      "VatGroup": line["VatGroup"], "WarehouseCode": line.get("WarehouseCode") or "RUH01"}
            ln["LineNum"], ln["LineStatus"] = i, "bost_Open"
            lines.append(ln)
        doc["DocumentLines"] = lines
        doc["DocTotal"] = round(sum(ln["Quantity"] * ln["Price"] * (1 + RATES[ln["VatGroup"]] / 100) for ln in lines), 2)
        for ln in lines:
            if ln["ItemCode"] is None:
                continue
            w = self._wh(ln["ItemCode"], ln["WarehouseCode"])
            from_order = ln.get("BaseType") == 17
            if entity == "Orders":
                w["Committed"] += ln["Quantity"]
            elif entity == "DeliveryNotes" or (entity == "Invoices" and ln.get("BaseType") != 15):
                w["InStock"] -= ln["Quantity"]
                if from_order:
                    w["Committed"] -= ln["Quantity"]
            elif entity == "CreditNotes":
                w["InStock"] += ln["Quantity"]
        if entity == "Invoices":
            self.partners[card]["CurrentAccountBalance"] += doc["DocTotal"]
        if entity == "CreditNotes":
            self.partners[card]["CurrentAccountBalance"] -= doc["DocTotal"]
        self.docs[entity][entry] = doc
        return httpx.Response(201, json=doc)

    def _cancel(self, entity: str, entry: int) -> httpx.Response:
        doc = self.docs[entity].get(entry)
        if doc is None:
            return self._err(404, "No matching records found")
        if doc["Cancelled"] == "tYES":
            return self._err(400, "Document is already cancelled")
        if entity == "Orders":
            if any(ln["LineStatus"] == "bost_Close" for ln in doc["DocumentLines"]):
                return self._err(400, "Cannot cancel a document that has copied lines")
            for ln in doc["DocumentLines"]:
                self._wh(ln["ItemCode"], ln["WarehouseCode"])["Committed"] -= ln["Quantity"]
        if entity == "IncomingPayments":
            self.partners[doc["CardCode"]]["CurrentAccountBalance"] += doc["DocTotal"]
            for pi in doc.get("PaymentInvoices") or []:
                self.docs["Invoices"][pi["DocEntry"]]["PaidToDate"] -= pi["SumApplied"]
        doc["Cancelled"] = "tYES"
        return httpx.Response(204)

    # ---- transport --------------------------------------------------------------------------
    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("connection refused")
        url = urlsplit(str(request.url))
        assert url.path.startswith("/b1s/v1/"), url.path
        path = unquote(url.path[len("/b1s/v1/"):])
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        body = json.loads(request.content) if request.content else {}

        if path == "Login":
            self.logins += 1
            if (body.get("CompanyDB"), body.get("UserName"), body.get("Password")) != (DB, USER, PASSWORD):
                return self._err(401, "Fail to get DB Credentials from SLD", -304)
            token = f"sess{self.logins}"
            self.sessions.add(token)
            return httpx.Response(200, json={"SessionId": token, "Version": "1000190", "SessionTimeout": 30},
                                  headers={"set-cookie": f"B1SESSION={token}; path=/b1s"})
        cookie = request.headers.get("cookie", "")
        token = (re.search(r"B1SESSION=(\w+)", cookie) or [None, None])[1]
        if token not in self.sessions or self.expire_next:
            self.expire_next = False
            self.sessions.discard(token)
            return self._err(401, "Invalid session or session already timeout.", 301)
        if path == "Logout":
            self.sessions.discard(token)
            return httpx.Response(204)
        if path == "CompanyService_GetCompanyInfo":
            return httpx.Response(200, json={"CompanyName": "Al Rayyan Trading Co."})
        if path == "CompanyService_GetAdminInfo":
            return httpx.Response(200, json={"LocalCurrency": "SAR"})

        m = re.match(r"^(\w+)(?:\((?:'((?:[^']|'')*)'|(\d+))\))?(?:/(\w+))?$", path)
        assert m, path
        entity, skey, nkey, action = m.group(1), m.group(2), m.group(3), m.group(4)
        key = skey.replace("''", "'") if skey is not None else (int(nkey) if nkey else None)

        if request.method == "POST" and action == "Cancel":
            return self._cancel(entity, key)
        if request.method == "POST" and entity == "BusinessPartners":
            if body["CardCode"] in self.partners:
                return self._err(400, "This entry already exists in the following tables")
            self.partners[body["CardCode"]] = {**body, "CurrentAccountBalance": 0.0}
            return httpx.Response(201, json=self.partners[body["CardCode"]])
        if request.method == "POST":
            return self._create(entity, body)
        if request.method == "PATCH":
            row = self.partners.get(key)
            if row is None:
                return self._err(404, "No matching records found")
            row.update(body)
            return httpx.Response(204)

        # GET
        if key is not None:
            rows = {"Items": self.items, "BusinessPartners": self.partners}.get(entity) or self.docs.get(entity, {})
            row = rows.get(key)
            return httpx.Response(200, json=row) if row is not None else self._err(404, "No matching records found", -2028)
        rows = [r for r in self._rows(entity) if _matches(r, query.get("$filter"))]
        if query.get("$orderby"):
            rows.sort(key=lambda r: str(r.get(query["$orderby"].split()[0])))
        skip = int(query.get("$skip", 0))
        top = int(query["$top"]) if "$top" in query else None
        size = min(self.page, top) if top else self.page
        page = rows[skip: skip + size]
        out = {"value": page}
        if skip + size < len(rows) and not top:
            nxt = dict(query, **{"$skip": str(skip + size)})
            out["odata.nextLink"] = f"{entity}?" + "&".join(f"{k}={v}" for k, v in nxt.items())
        return httpx.Response(200, json=out)
