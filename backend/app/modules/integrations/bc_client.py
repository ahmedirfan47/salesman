"""A small client for Microsoft Dynamics 365 Business Central's API v2.0.

Authentication is OAuth 2.0 client credentials (a Microsoft Entra app
registration with the Business Central API permission, granted in BC under
"Microsoft Entra Applications"):
  POST https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token
The API lives at
  <api host>/v2.0/<tenant>/<environment>/api/v2.0/companies(<id>)/...

Errors map to the shared ERP errors (app.modules.integrations.errors).
"""
import logging
import time
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from app.modules.integrations.errors import ErpAuthError, ErpError, ErpUnavailable, check_public_url

logger = logging.getLogger("salesman.integrations")

TIMEOUT_SECONDS = 60
DEFAULT_API = "https://api.businesscentral.dynamics.com"
LOGIN_URL = "https://login.microsoftonline.com"
SCOPE = "https://api.businesscentral.dynamics.com/.default"
USER_AGENT = "Salesman/1.0 (+https://salesman.app)"

# tests replace this with an httpx.MockTransport
TRANSPORT: httpx.AsyncBaseTransport | None = None


def lit(value) -> str:
    """An OData string literal: quotes doubled."""
    return "'" + str(value).replace("'", "''") + "'"


def _message(resp: httpx.Response) -> tuple[str, str]:
    try:
        err = resp.json().get("error") or {}
    except ValueError:
        return f"Business Central answered HTTP {resp.status_code}", ""
    msg = str(err.get("message") or "Business Central refused the request").strip()
    return msg.splitlines()[0][:500], str(err.get("code") or "")


@dataclass
class BcClient:
    url: str                          # API host, normally https://api.businesscentral.dynamics.com
    database: str | None              # environment name, e.g. Production
    username: str | None              # app (client) id
    api_key: str                      # client secret
    tenant: str | None = None         # Microsoft Entra tenant id or domain
    company_id: str | None = None
    api: str | None = "api_v2"
    version: str | None = "v2.0"
    _http: httpx.AsyncClient | None = None
    _token: str | None = None
    _expires: float = 0

    async def __aenter__(self) -> "BcClient":
        self.url = check_public_url(self.url or DEFAULT_API, system="Business Central API",
                                    example=DEFAULT_API, strip=("/v2.0",))
        for value, what in ((self.tenant, "Microsoft Entra tenant ID or domain"), (self.database, "environment name"),
                            (self.username, "application (client) ID")):
            if not value:
                raise ErpAuthError(f"Enter the {what}.")
        self._http = httpx.AsyncClient(transport=TRANSPORT, timeout=TIMEOUT_SECONDS, follow_redirects=False,
                                       headers={"User-Agent": USER_AGENT})
        await self._authenticate()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._http is not None:
            await self._http.aclose()

    async def _authenticate(self) -> None:
        try:
            resp = await self._http.post(f"{LOGIN_URL}/{quote(self.tenant)}/oauth2/v2.0/token", data={
                "grant_type": "client_credentials", "client_id": self.username, "client_secret": self.api_key,
                "scope": SCOPE,
            })
        except httpx.HTTPError as exc:
            raise ErpUnavailable(f"Microsoft sign-in could not be reached ({exc.__class__.__name__})") from exc
        if resp.status_code >= 500:
            raise ErpUnavailable(f"Microsoft sign-in answered HTTP {resp.status_code}")
        if resp.status_code != 200:
            try:
                detail = (resp.json().get("error_description") or "").splitlines()[0][:300]
            except ValueError:
                detail = ""
            raise ErpAuthError("Microsoft refused the app's sign-in: check the tenant, client ID and secret. " + detail)
        data = resp.json()
        self._token = data["access_token"]
        self._expires = time.monotonic() + int(data.get("expires_in") or 3600) - 120

    @property
    def root(self) -> str:
        return f"{self.url}/v2.0/{quote(self.tenant)}/{quote(self.database)}/api/v2.0"

    def company_path(self, path: str) -> str:
        if not self.company_id:
            raise ErpError("Choose the Business Central company first.")
        return f"companies({self.company_id})/{path.lstrip('/')}"

    async def _send(self, method: str, path: str, *, retry: bool = True, **kw) -> httpx.Response:
        if time.monotonic() > self._expires:
            await self._authenticate()
        extra = kw.pop("headers", {})
        headers = {"Authorization": f"Bearer {self._token}", **extra}
        target = path if path.startswith("http") else f"{self.root}/{path.lstrip('/')}"
        try:
            resp = await self._http.request(method, target, headers=headers, **kw)
        except httpx.HTTPError as exc:
            raise ErpUnavailable(f"Business Central could not be reached ({exc.__class__.__name__})") from exc
        if resp.status_code == 401 and retry:
            await self._authenticate()
            return await self._send(method, path, retry=False, headers=extra, **kw)
        if resp.status_code in (429, 502, 503, 504):
            raise ErpUnavailable(f"Business Central is busy (HTTP {resp.status_code})")
        if resp.status_code in (401, 403):
            msg, _ = _message(resp)
            raise ErpAuthError(f"Business Central refused the app: {msg} "
                               "Check that the app is added under Microsoft Entra Applications with API permissions.")
        if resp.status_code >= 500:
            msg, _ = _message(resp)
            raise ErpUnavailable(f"Business Central answered HTTP {resp.status_code}: {msg}")
        return resp

    async def get(self, path: str, params: dict | None = None) -> dict | None:
        resp = await self._send("GET", path, params=params)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            msg, code = _message(resp)
            raise ErpError(msg, code)
        return resp.json()

    async def list(self, path: str, *, filter: str | None = None, select: str | None = None,
                   top: int | None = None) -> list[dict]:
        params = {}
        if filter:
            params["$filter"] = filter
        if select:
            params["$select"] = select
        if top:
            params["$top"] = top
        out, target = [], path
        while target:
            data = await self.get(target, params)
            if data is None:
                raise ErpError(f"Business Central has no '{path.split('/')[-1]}' (is the API available?)", "NotFound")
            out.extend(data.get("value") or [])
            if top and len(out) >= top:
                return out[:top]
            target, params = data.get("@odata.nextLink"), None
        return out

    async def first(self, path: str, filter: str) -> dict | None:
        rows = await self.list(path, filter=filter, top=1)
        return rows[0] if rows else None

    async def post(self, path: str, body: dict | None = None) -> dict | None:
        resp = await self._send("POST", path, json=body or {})
        if resp.status_code not in (200, 201, 204):
            msg, code = _message(resp)
            raise ErpError(msg, code)
        return resp.json() if resp.content.strip() else None

    async def patch(self, path: str, body: dict) -> dict | None:
        resp = await self._send("PATCH", path, json=body, headers={"If-Match": "*"})
        if resp.status_code not in (200, 204):
            msg, code = _message(resp)
            raise ErpError(msg, code)
        return resp.json() if resp.content.strip() else None

    async def delete(self, path: str) -> bool:
        """False when it was already gone."""
        resp = await self._send("DELETE", path, headers={"If-Match": "*"})
        if resp.status_code == 404:
            return False
        if resp.status_code not in (200, 204):
            msg, code = _message(resp)
            raise ErpError(msg, code)
        return True
