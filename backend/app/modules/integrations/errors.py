"""Errors every ERP client raises, whatever the system behind it.

- ErpAuthError: wrong address, company, user or key. Shown to the business;
  pulls stop until the connection is checked again.
- ErpError: the ERP refused the request (a validation rule, a missing record,
  access rights). Retrying the same request won't help.
- ErpUnavailable: the server could not be reached, timed out, or answered
  with a gateway or overload error. The job queue retries it.
"""
import ipaddress
import socket
from urllib.parse import urlsplit

from app.config import settings


class ErpError(Exception):
    def __init__(self, message: str, name: str | None = None):
        super().__init__(message)
        self.name = name or "ErpError"
        self.message = message


class ErpAuthError(ErpError):
    pass


class ErpUnavailable(Exception):
    pass


def normalise_url(url: str, strip: tuple[str, ...] = ()) -> str:
    url = (url or "").strip().rstrip("/")
    if url and "://" not in url:
        url = "https://" + url
    for suffix in strip:
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url


def check_public_url(url: str, *, system: str, example: str, strip: tuple[str, ...] = ()) -> str:
    """Only public https addresses: a business must not be able to make our server call its own network."""
    url = normalise_url(url, strip)
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ErpAuthError(f"Enter the {system} address, e.g. {example}")
    if settings.ERP_ALLOW_PRIVATE_URLS:
        return url
    if parts.scheme != "https":
        raise ErpAuthError(f"Use the https:// address of your {system}.")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return url  # can't be resolved here; the request itself will fail with a clear message
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ErpAuthError(f"That address points to a private network. Use your {system}'s public address.")
    return url
