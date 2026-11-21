"""A small client for SAP Business One's Service Layer (OData, /b1s/v1).

Login is POST /Login with the company database, user and password; the
session cookie is kept for the client's lifetime and renewed once if the
session times out. Lists are paged with odata.maxpagesize and nextLink.

Errors map to the shared ERP errors (app.modules.integrations.errors):
wrong login -> ErpAuthError, refused request -> ErpError, unreachable or
overloaded -> ErpUnavailable (retried by the job queue).
"""
import logging
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx

from app.modules.integrations.errors import ErpAuthError, ErpError, ErpUnavailable, check_public_url

logger = logging.getLogger("salesman.integrations")

TIMEOUT_SECONDS = 60
PAGE = 500
USER_AGENT = "Salesman/1.0 (+https://salesman.app)"

# tests replace this with an httpx.MockTransport
TRANSPORT: httpx.AsyncBaseTransport | None = None


def check_url(url: str) -> str:
    return check_public_url(url, system="SAP Service Layer", example="https://sap.yourcompany.com:50000",
                            strip=("/b1s/v1", "/b1s/v2", "/b1s"))


def key(value) -> str:
    """An OData key or string literal: quotes doubled."""
    return "'" + str(value).replace("'", "''") + "'"


def _message(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
    except ValueError:
        return f"SAP answered HTTP {resp.status_code}"
    msg = err.get("message")
    if isinstance(msg, dict):
        msg = msg.get("value")
    return (str(msg or "SAP refused the request").strip().splitlines() or ["SAP refused the request"])[0][:500]


@dataclass
class SapClient:
    url: str
    database: str | None
    username: str | None
    api_key: str                      # the user's password
    api: str | None = "service_layer"
    version: str | None = None
    _http: httpx.AsyncClient | None = None
    _logged_in: bool = False
    _cache: dict = field(default_factory=dict)

    async def __aenter__(self) -> "SapClient":
        self.url = check_url(self.url)
        if not self.database:
            raise ErpAuthError("Enter the SAP company database (e.g. SBODEMOSA).")
        if not self.username:
            raise ErpAuthError("Enter the SAP user name.")
        self._http = httpx.AsyncClient(transport=TRANSPORT, timeout=TIMEOUT_SECONDS, follow_redirects=False,
                                       headers={"User-Agent": USER_AGENT})
        await self.login()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._http is not None:
            if self._logged_in:
                try:
                    await self._http.post(self._base + "/Logout")
                except httpx.HTTPError:
                    pass
            await self._http.aclose()

    @property
    def _base(self) -> str:
        return self.url + "/b1s/v1"

    async def login(self) -> None:
        try:
            resp = await self._http.post(self._base + "/Login", json={
                "CompanyDB": self.database, "UserName": self.username, "Password": self.api_key,
            })
        except httpx.HTTPError as exc:
            raise ErpUnavailable(f"SAP could not be reached ({exc.__class__.__name__})") from exc
        if resp.status_code in (429, 502, 503, 504):
            raise ErpUnavailable(f"SAP is busy or restarting (HTTP {resp.status_code})")
        if resp.status_code == 404:
            raise ErpAuthError("This address doesn't look like a SAP Service Layer (no /b1s/v1/Login). Check the URL and port.")
        if resp.status_code != 200:
            raise ErpAuthError(f"SAP refused the login: {_message(resp)}")
        info = resp.json()
        self.version = str(info.get("Version") or "")
        self._logged_in = True

    async def _send(self, method: str, path: str, *, retry: bool = True, **kw) -> httpx.Response:
        try:
            resp = await self._http.request(method, self._base + "/" + path.lstrip("/"), **kw)
        except httpx.HTTPError as exc:
            raise ErpUnavailable(f"SAP could not be reached ({exc.__class__.__name__})") from exc
        if resp.status_code == 401 and retry:  # session timed out: log in again once
            await self.login()
            return await self._send(method, path, retry=False, **kw)
        if resp.status_code in (429, 502, 503, 504):
            raise ErpUnavailable(f"SAP is busy or restarting (HTTP {resp.status_code})")
        if resp.is_redirect:
            raise ErpAuthError("SAP sent us to another address. Use the Service Layer address directly.")
        if resp.status_code == 401:
            raise ErpAuthError("SAP refused the session: check the user and password.")
        if resp.status_code >= 500 and not resp.content:
            raise ErpUnavailable(f"SAP answered HTTP {resp.status_code}")
        return resp

    async def get(self, path: str, params: dict | None = None) -> dict | None:
        """One entity or one page. None when the entity doesn't exist."""
        resp = await self._send("GET", path, params=params)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise ErpError(_message(resp), str(resp.status_code))
        return resp.json()

    async def get_all(self, entity: str, *, select: str | None = None, filter: str | None = None,
                      orderby: str | None = None) -> list[dict]:
        params = {}
        if select:
            params["$select"] = select
        if filter:
            params["$filter"] = filter
        if orderby:
            params["$orderby"] = orderby
        out, path = [], entity
        headers = {"Prefer": f"odata.maxpagesize={PAGE}"}
        while path:
            resp = await self._send("GET", path, params=params, headers=headers)
            if resp.status_code != 200:
                raise ErpError(_message(resp), str(resp.status_code))
            data = resp.json()
            out.extend(data.get("value") or [])
            nxt = data.get("odata.nextLink") or data.get("@odata.nextLink")
            path, params = (nxt, None) if nxt else (None, None)
        return out

    async def first(self, entity: str, filter: str, select: str | None = None) -> dict | None:
        params = {"$filter": filter, "$top": 1}
        if select:
            params["$select"] = select
        data = await self.get(entity, params)
        rows = (data or {}).get("value") or []
        return rows[0] if rows else None

    async def post(self, path: str, body: dict | None = None) -> dict | None:
        resp = await self._send("POST", path, json=body or {})
        if resp.status_code not in (200, 201, 204):
            raise ErpError(_message(resp), str(resp.status_code))
        return resp.json() if resp.content.strip() else None

    async def patch(self, path: str, body: dict) -> None:
        resp = await self._send("PATCH", path, json=body)
        if resp.status_code not in (200, 204):
            raise ErpError(_message(resp), str(resp.status_code))

    async def action(self, path: str, body: dict | None = None) -> dict | None:
        """A bound or unbound action, e.g. Orders(12)/Cancel or CompanyService_GetCompanyInfo."""
        return await self.post(path, body)


def path(entity: str, key_value) -> str:
    """Entity path: Orders(12) for numbers, BusinessPartners('C001') for strings."""
    if isinstance(key_value, int) or (isinstance(key_value, str) and key_value.isdigit() and entity not in _STRING_KEYS):
        return f"{entity}({int(key_value)})"
    return f"{entity}({quote(key(key_value), safe=chr(39))})"


_STRING_KEYS = {"BusinessPartners", "Items", "Warehouses", "VatGroups"}
