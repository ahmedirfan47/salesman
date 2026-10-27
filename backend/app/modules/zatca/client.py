"""HTTP client for ZATCA's Fatoora APIs (version V2).

Onboarding: compliance CSID -> compliance invoice checks -> production CSID.
Every day: clearance (standard invoices) and reporting (simplified ones).

Responses are returned as (http_status, json) and never raise for ZATCA's
own answers -- a 400 with validation errors is a normal outcome the caller
records. Network failures, timeouts, 429 and 5xx raise ZatcaUnavailable so
the job queue retries them with the same payload.
"""
import base64

import httpx

from app.config import settings

BASE_URLS = {
    "sandbox": "https://gw-fatoora.zatca.gov.sa/e-invoicing/developer-portal",
    "simulation": "https://gw-fatoora.zatca.gov.sa/e-invoicing/simulation",
    "production": "https://gw-fatoora.zatca.gov.sa/e-invoicing/core",
}

# tests replace this with an httpx.MockTransport
TRANSPORT: httpx.AsyncBaseTransport | None = None


class ZatcaUnavailable(Exception):
    """ZATCA could not be reached or is overloaded: try again later with the same document."""


def _auth(token: str, secret: str) -> str:
    return "Basic " + base64.b64encode(f"{token}:{secret}".encode()).decode()


async def _post(environment: str, path: str, *, body: dict, headers: dict, method: str = "POST") -> tuple[int, dict]:
    url = BASE_URLS[environment] + path
    base_headers = {
        "Accept": "application/json",
        "Accept-Language": "en",
        "Accept-Version": "V2",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(transport=TRANSPORT, timeout=settings.ZATCA_TIMEOUT_SECONDS) as client:
            resp = await client.request(method, url, json=body, headers={**base_headers, **headers})
    except httpx.HTTPError as exc:
        raise ZatcaUnavailable(f"ZATCA could not be reached: {exc.__class__.__name__}") from exc
    if resp.status_code == 429 or resp.status_code >= 500:
        raise ZatcaUnavailable(f"ZATCA answered {resp.status_code}: {resp.text[:300]}")
    try:
        data = resp.json()
    except ValueError:
        data = {"message": resp.text[:1000]}
    if not isinstance(data, dict):
        data = {"message": str(data)[:1000]}
    return resp.status_code, data


async def compliance_csid(environment: str, csr_b64: str, otp: str) -> tuple[int, dict]:
    return await _post(environment, "/compliance", body={"csr": csr_b64}, headers={"OTP": otp})


async def compliance_check(environment: str, token: str, secret: str, *, invoice_hash: str, uuid: str,
                           xml_b64: str) -> tuple[int, dict]:
    return await _post(
        environment, "/compliance/invoices",
        body={"invoiceHash": invoice_hash, "uuid": uuid, "invoice": xml_b64},
        headers={"Authorization": _auth(token, secret)},
    )


async def production_csid(environment: str, token: str, secret: str, compliance_request_id: str) -> tuple[int, dict]:
    return await _post(
        environment, "/production/csids", body={"compliance_request_id": compliance_request_id},
        headers={"Authorization": _auth(token, secret)},
    )


async def submit(environment: str, token: str, secret: str, *, flow: str, invoice_hash: str, uuid: str,
                 xml_b64: str) -> tuple[int, dict]:
    """Clear a standard document or report a simplified one."""
    path = "/invoices/clearance/single" if flow == "standard" else "/invoices/reporting/single"
    return await _post(
        environment, path,
        body={"invoiceHash": invoice_hash, "uuid": uuid, "invoice": xml_b64},
        headers={"Authorization": _auth(token, secret), "Clearance-Status": "1" if flow == "standard" else "0"},
    )


def messages(data: dict) -> tuple[list[dict], list[dict]]:
    """(errors, warnings) from a ZATCA answer, as [{"code", "message"}]."""
    results = data.get("validationResults") or {}
    def pick(items) -> list[dict]:
        return [{"code": m.get("code"), "message": m.get("message"), "category": m.get("category")}
                for m in items or [] if isinstance(m, dict)]
    errors = pick(results.get("errorMessages"))
    warnings = pick(results.get("warningMessages"))
    # onboarding endpoints answer {"errors": [...]} or {"code", "message"}
    if not errors and isinstance(data.get("errors"), list):
        errors = pick(data["errors"]) or [{"code": None, "message": str(e)} for e in data["errors"]]
    if not errors and data.get("code") and data.get("message") and "validationResults" not in data:
        errors = [{"code": data.get("code"), "message": data.get("message"), "category": None}]
    return errors, warnings