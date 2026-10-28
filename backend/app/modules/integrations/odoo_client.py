"""A small client for Odoo's external API.

Two transports, one interface:

- JSON-2 (Odoo 19 and later): POST /json/2/<model>/<method> with
  "Authorization: bearer <API key>". The only API left in Odoo 20.
- JSON-RPC (Odoo 16-19): POST /jsonrpc, execute_kw with a user id from
  common.authenticate. The API key is used as the password.

Every call is made by name -- call(model, method, ids=[...], context={...},
**named_arguments) -- which both transports support (except JSON-RPC's
create, which takes its values positionally; create() handles that), so the
connector code never cares which one is in use.

Errors:
- OdooAuthError: wrong URL, database, user or API key.
- OdooError: Odoo refused the request (a validation rule, a missing record,
  access rights). Retrying the same request won't help; the message is shown
  to the business.
- OdooUnavailable: the server could not be reached, timed out, or answered
  with a gateway or overload error. The job queue retries it.
"""
import ipaddress
import logging
import socket
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from app.config import settings

logger = logging.getLogger("salesman.integrations")

TIMEOUT_SECONDS = 45
USER_AGENT = "Salesman/1.0 (+https://salesman.app)"

# tests replace this with an httpx.MockTransport
TRANSPORT: httpx.AsyncBaseTransport | None = None

_TRANSIENT_NAMES = ("SerializationFailure", "LockNotAvailable", "concurrent update", "could not serialize")


class OdooError(Exception):
    def __init__(self, message: str, name: str | None = None):
        super().__init__(message)
        self.name = name or "odoo.exceptions.UserError"
        self.message = message


class OdooAuthError(OdooError):
    pass


class OdooUnavailable(Exception):
    pass


def normalise_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if url and "://" not in url:
        url = "https://" + url
    for suffix in ("/odoo", "/web", "/web/login"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url


def check_url(url: str) -> str:
    """Only public http(s) addresses: a business must not be able to make our server call its own network."""
    url = normalise_url(url)
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise OdooAuthError("Enter the Odoo address, e.g. https://yourcompany.odoo.com")
    if settings.ERP_ALLOW_PRIVATE_URLS:
        return url
    if parts.scheme != "https":
        raise OdooAuthError("Use the https:// address of your Odoo.")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return url  # can't be resolved here; the request itself will fail with a clear message
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise OdooAuthError("That address points to a private network. Use your Odoo's public address.")
    return url


def _clean(message: str | None) -> str:
    return (message or "").strip().splitlines()[0][:500] if message else "Odoo refused the request"


@dataclass
class OdooClient:
    url: str
    database: str | None
    username: str | None
    api_key: str
    api: str | None = None              # json2 | jsonrpc; None = detect
    version: str | None = None
    _uid: int | None = None
    _http: httpx.AsyncClient | None = None
    _fields: dict = field(default_factory=dict)

    # ---- lifecycle --------------------------------------------------------------------------
    async def __aenter__(self) -> "OdooClient":
        self.url = check_url(self.url)
        # redirects are not followed: they could lead to an address check_url would refuse
        self._http = httpx.AsyncClient(transport=TRANSPORT, timeout=TIMEOUT_SECONDS, follow_redirects=False,
                                       headers={"User-Agent": USER_AGENT})
        if self.api is None:
            await self.detect()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._http is not None:
            await self._http.aclose()

    async def _send(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            resp = await self._http.request(method, self.url + path, **kw)
        except httpx.HTTPError as exc:
            raise OdooUnavailable(f"Odoo could not be reached ({exc.__class__.__name__})") from exc
        if resp.status_code in (429, 502, 503, 504):
            raise OdooUnavailable(f"Odoo is busy or restarting (HTTP {resp.status_code})")
        if resp.is_redirect:
            target = resp.headers.get("location", "")
            raise OdooAuthError(f"Odoo sent us to another address ({target[:120]}). Use that address instead.")
        return resp

    # ---- detection ----------------------------------------------------------------------------
    async def detect(self) -> str:
        """Pick JSON-2 when the server has it (Odoo 19+), else JSON-RPC."""
        resp = await self._send("GET", "/web/version")
        major = None
        if resp.status_code == 200:
            try:
                info = resp.json()
                self.version = str(info.get("version") or "")
                major = int((info.get("version_info") or [0])[0])
            except (ValueError, TypeError, IndexError):
                major = None
        if major is not None and major >= 19:
            self.api = "json2"
            try:
                await self.call("res.users", "context_get")
                return self.api
            except OdooError as exc:
                if isinstance(exc, OdooAuthError) or not self.username:
                    raise
                # JSON-2 switched off on this server: fall back to JSON-RPC
        self.api = "jsonrpc"
        if not self.version:
            info = await self._rpc("common", "version")
            self.version = str(info.get("server_version") or "")
        await self._login()
        return self.api

    # ---- JSON-RPC ----------------------------------------------------------------------------
    async def _rpc(self, service: str, method: str, *args):
        resp = await self._send("POST", "/jsonrpc", json={
            "jsonrpc": "2.0", "method": "call", "params": {"service": service, "method": method, "args": list(args)}, "id": 1,
        })
        if resp.status_code == 404:
            raise OdooAuthError("This address doesn't look like an Odoo server (no /jsonrpc). Check the URL.")
        try:
            data = resp.json()
        except ValueError as exc:
            if resp.status_code >= 500:
                raise OdooUnavailable(f"Odoo answered HTTP {resp.status_code}") from exc
            raise OdooError(f"Odoo answered HTTP {resp.status_code} without a readable reply") from exc
        if "error" in data:
            err = (data["error"] or {}).get("data") or {}
            name = err.get("name") or ""
            message = _clean(err.get("message") or (data["error"] or {}).get("message"))
            if "AccessDenied" in name:
                raise OdooAuthError("Odoo refused the login: check the user and API key.", name)
            if any(t in name or t in message for t in _TRANSIENT_NAMES):
                raise OdooUnavailable(message)
            if self.database and "does not exist" in message and self.database in message:
                raise OdooAuthError(f"There is no database called '{self.database}' on this server.", name)
            raise OdooError(message, name)
        return data.get("result")

    async def _login(self) -> None:
        if not self.database:
            raise OdooAuthError("This Odoo version needs the database name.")
        if not self.username:
            raise OdooAuthError("This Odoo version needs the login (email) of the user the API key belongs to.")
        uid = await self._rpc("common", "authenticate", self.database, self.username, self.api_key, {})
        if not uid:
            raise OdooAuthError("Odoo refused the login: check the database, user and API key.")
        self._uid = int(uid)

    # ---- JSON-2 ------------------------------------------------------------------------------
    async def _json2(self, model: str, method: str, body: dict):
        headers = {"Authorization": f"bearer {self.api_key}", "Content-Type": "application/json; charset=utf-8"}
        if self.database:
            headers["X-Odoo-Database"] = self.database
        resp = await self._send("POST", f"/json/2/{model}/{method}", json=body, headers=headers)
        if resp.status_code == 200:
            return resp.json() if resp.content.strip() else None
        try:
            err = resp.json()
        except ValueError:
            err = {}
        name = err.get("name") or ""
        message = _clean(err.get("message"))
        if resp.status_code == 401 or "Unauthorized" in name:
            raise OdooAuthError("Odoo refused the API key. Create a new one in Odoo (Preferences > Account Security).", name)
        if resp.status_code == 404 and not err:
            raise OdooError(f"Odoo has no '{model}' model or '{method}' method (is the app installed?)", "NotFound")
        if any(t in name or t in message for t in _TRANSIENT_NAMES):
            raise OdooUnavailable(message)
        if resp.status_code >= 500 and not err:
            raise OdooUnavailable(f"Odoo answered HTTP {resp.status_code}")
        raise OdooError(message, name)

    # ---- the interface -----------------------------------------------------------------------
    async def call(self, model: str, method: str, *, ids: list[int] | None = None, context: dict | None = None, **kwargs):
        if self.api == "json2":
            body = dict(kwargs)
            if ids is not None:
                body["ids"] = ids
            if context:
                body["context"] = context
            return await self._json2(model, method, body)
        args = [ids] if ids is not None else []
        if context:
            kwargs = {**kwargs, "context": context}
        return await self._execute_kw(model, method, args, kwargs)

    async def _execute_kw(self, model: str, method: str, args: list, kwargs: dict):
        if self._uid is None:
            await self._login()
        return await self._rpc("object", "execute_kw", self.database, self._uid, self.api_key, model, method, args, kwargs)

    async def search_read(self, model: str, domain: list, fields: list[str], *, context: dict | None = None,
                          limit: int | None = None, offset: int = 0, order: str | None = None) -> list[dict]:
        kw: dict = {"domain": domain, "fields": fields}
        if limit:
            kw["limit"] = limit
        if offset:
            kw["offset"] = offset
        if order:
            kw["order"] = order
        return await self.call(model, "search_read", context=context, **kw) or []

    async def search_read_all(self, model: str, domain: list, fields: list[str], *, context: dict | None = None,
                              page: int = 500) -> list[dict]:
        out, offset = [], 0
        while True:
            rows = await self.search_read(model, domain, fields, context=context, limit=page, offset=offset, order="id")
            out.extend(rows)
            if len(rows) < page:
                return out
            offset += page

    async def read(self, model: str, ids: list[int], fields: list[str], *, context: dict | None = None) -> list[dict]:
        if not ids:
            return []
        return await self.call(model, "read", ids=ids, fields=fields, context=context) or []

    async def create(self, model: str, vals: dict, *, context: dict | None = None) -> int:
        if self.api == "json2":
            result = await self.call(model, "create", vals_list=[vals], context=context)
        else:  # JSON-RPC's create only takes its values positionally
            result = await self._execute_kw(model, "create", [[vals]], {"context": context} if context else {})
        return int(result[0] if isinstance(result, list) else result)

    async def write(self, model: str, ids: list[int], vals: dict, *, context: dict | None = None) -> None:
        await self.call(model, "write", ids=ids, vals=vals, context=context)

    async def fields(self, model: str) -> set[str]:
        if model not in self._fields:
            info = await self.call(model, "fields_get", attributes=["type"])
            self._fields[model] = set(info or {})
        return self._fields[model]