"""An in-memory Dynamics 365 Business Central (API v2.0) plus the Microsoft token endpoint, for the connector tests."""
import itertools
import json
import re
import uuid
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

TENANT, ENV, CLIENT_ID, SECRET = "acme.onmicrosoft.com", "Production", "11111111-2222-3333-4444-555555555555", "shh"
VAT = 0.15

_term = re.compile(r"^\s*(?:contains\((\w+),\s*'((?:[^']|'')*)'\)|(\w+)\s+eq\s+(?:'((?:[^']|'')*)'|(true|false)|(-?\d+(?:\.\d+)?)))\s*$")


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
        elif m.group(4) is not None:
            if str(row.get(m.group(3))) != m.group(4).replace("''", "'"):
                return False
        elif m.group(5) is not None:
            if bool(row.get(m.group(3))) != (m.group(5) == "true"):
                return False
        elif float(row.get(m.group(3)) or 0) != float(m.group(6)):
            return False
    return True


def _id() -> str:
    return str(uuid.uuid4())


class FakeBc:
    def __init__(self):
        self.down = False
        self.tokens: set[str] = set()
        self.token_calls = 0
        self._no = itertools.count(1001)
        self.company = _id()
        self.locations = {_id(): ("RUH", "Riyadh warehouse"), _id(): ("JED", "Jeddah warehouse")}
        self.journal = _id()
        self.income = _id()
        self.items = {}
        for number, name, price, cost, inv in (("TOM-5", "Tomatoes 5kg box", 100.0, 70.0, 160),
                                               ("ONI-10", "Onions 10kg sack", 55.0, 30.0, 80)):
            iid = _id()
            self.items[iid] = {"id": iid, "number": number, "displayName": name, "displayName2": None, "type": "Inventory",
                               "blocked": False, "unitPrice": price, "unitCost": cost, "inventory": inv}
        self.customers: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.invoices: dict[str, dict] = {}
        self.memos: dict[str, dict] = {}
        self.payments: dict[str, dict] = {}   # journal lines

    def item(self, number: str) -> dict:
        return next(i for i in self.items.values() if i["number"] == number)

    @staticmethod
    def _err(status: int, code: str, message: str) -> httpx.Response:
        return httpx.Response(status, json={"error": {"code": code, "message": message}})

    def _total(self, lines: list[dict]) -> float:
        return round(sum(ln["quantity"] * ln["unitPrice"] for ln in lines) * (1 + VAT), 2)

    def _post_invoice(self, inv: dict) -> None:
        inv["status"] = "Open"
        inv["totalAmountIncludingTax"] = self._total(inv["_lines"])
        for ln in inv["_lines"]:
            if ln.get("lineType") != "Account":
                self.items[ln["itemId"]]["inventory"] -= ln["quantity"]
        self.customers[inv["customerId"]]["balanceDue"] += inv["totalAmountIncludingTax"]

    def _list(self, rows, query) -> httpx.Response:
        rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows if _matches(r, query.get("$filter"))]
        if "$top" in query:
            rows = rows[: int(query["$top"])]
        return httpx.Response(200, json={"value": rows})

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("connection refused")
        url = urlsplit(str(request.url))
        if url.hostname == "login.microsoftonline.com":
            form = parse_qs(request.content.decode())
            self.token_calls += 1
            if unquote(url.path) != f"/{TENANT}/oauth2/v2.0/token" or form.get("client_id") != [CLIENT_ID] \
                    or form.get("client_secret") != [SECRET]:
                return httpx.Response(401, json={"error": "invalid_client",
                                                 "error_description": "AADSTS7000215: Invalid client secret provided."})
            token = f"tok{self.token_calls}"
            self.tokens.add(token)
            return httpx.Response(200, json={"access_token": token, "expires_in": 3599, "token_type": "Bearer"})
        if request.headers.get("authorization", "").removeprefix("Bearer ") not in self.tokens:
            return self._err(401, "Unauthorized", "The credentials provided are incorrect")
        prefix = f"/v2.0/{TENANT}/{ENV}/api/v2.0/"
        path = unquote(url.path)
        assert path.startswith(prefix), path
        path = path[len(prefix):]
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        body = json.loads(request.content) if request.content else {}
        if path == "companies":
            return self._list([{"id": self.company, "name": "CRONUS SA", "displayName": "Al Rayyan Trading"}], query)
        m = re.match(rf"^companies\({self.company}\)/(.+)$", path)
        if not m:
            return self._err(404, "BadRequest_NotFound", "The company was not found")
        segs = re.findall(r"(\w+(?:\.\w+)*)(?:\(([\w-]+)\))?", m.group(1))
        method = request.method

        if segs[0][0] == "companyInformation":
            return self._list([{"id": _id(), "displayName": "Al Rayyan Trading", "currencyCode": "SAR"}], query)
        if segs[0][0] == "locations":
            return self._list([{"id": k, "code": c, "displayName": n} for k, (c, n) in self.locations.items()], query)
        if segs[0][0] == "taxGroups":
            return self._list([{"id": _id(), "code": "VAT15", "displayName": "Standard VAT 15%", "taxType": "VAT"},
                               {"id": _id(), "code": "VAT0", "displayName": "Zero rated", "taxType": "VAT"}], query)
        if segs[0][0] == "accounts":
            return self._list([{"id": self.income, "number": "40100", "displayName": "Sales returns", "category": "Income",
                                "blocked": False}], query)
        if segs[0][0] == "items":
            return self._list(self.items.values(), query)

        if segs[0][0] == "customerPaymentJournals":
            if len(segs) == 1 and not segs[0][1]:
                return self._list([{"id": self.journal, "code": "CASHRCPT", "displayName": "Cash receipts"}], query)
            if segs[0][1] != self.journal:
                return self._err(404, "BadRequest_NotFound", "Journal not found")
            line_id = segs[1][1]
            if method == "POST":
                if body["customerId"] not in self.customers:
                    return self._err(400, "BadRequest", "Customer does not exist")
                row = {**body, "id": _id(), "journalId": self.journal}
                self.payments[row["id"]] = row
                return httpx.Response(201, json=row)
            if method == "DELETE":
                return httpx.Response(204) if self.payments.pop(line_id, None) else self._err(404, "NotFound", "Gone")
            return self._list(self.payments.values(), query)

        if segs[0][0] == "customers":
            cid = segs[0][1]
            if method == "POST":
                row = {**body, "id": _id(), "number": f"C{next(self._no)}", "balanceDue": 0.0}
                self.customers[row["id"]] = row
                return httpx.Response(201, json=row)
            if method == "PATCH":
                if request.headers.get("if-match") is None:
                    return self._err(400, "BadRequest", "If-Match header is required")
                self.customers[cid].update(body)
                return httpx.Response(200, json=self.customers[cid])
            if cid:
                row = self.customers.get(cid)
                return httpx.Response(200, json=row) if row else self._err(404, "NotFound", "Customer not found")
            return self._list(self.customers.values(), query)

        table = {"salesOrders": self.orders, "salesInvoices": self.invoices, "salesCreditMemos": self.memos}[segs[0][0]]
        doc_id = segs[0][1]
        if len(segs) == 1:
            if method == "POST":
                if body.get("customerId") not in self.customers:
                    return self._err(400, "BadRequest", "Customer does not exist")
                row = {**body, "id": _id(), "number": f"{segs[0][0][:3].upper()}{next(self._no)}", "status": "Draft",
                       "totalAmountIncludingTax": 0.0, "_lines": []}
                table[row["id"]] = row
                return httpx.Response(201, json={k: v for k, v in row.items() if k != "_lines"})
            if method == "DELETE":
                if doc_id not in table:
                    return self._err(404, "NotFound", "Gone")
                if table[doc_id].get("status") == "Shipped":
                    return self._err(400, "BadRequest", "You cannot delete the order, it has been shipped")
                del table[doc_id]
                return httpx.Response(204)
            if method == "PATCH":
                table[doc_id].update(body)
                return httpx.Response(200, json={k: v for k, v in table[doc_id].items() if k != "_lines"})
            if doc_id:
                row = table.get(doc_id)
                return httpx.Response(200, json={k: v for k, v in row.items() if k != "_lines"}) if row \
                    else self._err(404, "NotFound", "Not found")
            return self._list(table.values(), query)
        doc = table[doc_id]
        sub = segs[1][0]
        if sub.endswith("Lines"):
            if method == "POST":
                if body.get("lineType") == "Account":
                    line = {**body, "id": _id()}
                    doc["_lines"].append(line)
                    return httpx.Response(201, json=line)
                if body["itemId"] not in self.items:
                    return self._err(400, "BadRequest", "Item does not exist")
                line = {**body, "id": _id()}
                doc["_lines"].append(line)
                return httpx.Response(201, json=line)
            return self._list(doc["_lines"], query)
        if sub == "Microsoft.NAV.shipAndInvoice":
            inv = {"id": _id(), "number": f"PSI{next(self._no)}", "customerId": doc["customerId"],
                   "externalDocumentNumber": doc["externalDocumentNumber"], "orderNumber": doc["number"],
                   "_lines": [dict(ln) for ln in doc["_lines"]]}
            self._post_invoice(inv)
            self.invoices[inv["id"]] = inv
            doc["status"] = "Shipped"
            return httpx.Response(204)
        if sub == "Microsoft.NAV.post":
            if doc["status"] != "Draft":
                return self._err(400, "BadRequest", "Already posted")
            if table is self.invoices:
                self._post_invoice(doc)
            else:
                doc["status"] = "Open"
                doc["totalAmountIncludingTax"] = self._total(doc["_lines"])
                self.customers[doc["customerId"]]["balanceDue"] -= doc["totalAmountIncludingTax"]
            return httpx.Response(204)
        return self._err(404, "NotFound", f"Unknown {sub}")
