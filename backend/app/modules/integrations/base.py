"""What every ERP connector shares: outcomes, rules about what is sent, and helpers."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.db.models.integration import IntegrationConnection

CENT = Decimal("0.01")
LIVE_ORDER = ("confirmed", "preparing", "dispatched", "delivered", "completed")
PENDING_ORDER = ("confirmed", "preparing", "dispatched")
SYNC_LABEL = "Prices and stock"


class SyncProblem(Exception):
    """Something the business has to fix (in Salesman or the ERP) before this can be sent."""


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


def money(x) -> Decimal:
    return Decimal(str(x or 0)).quantize(CENT)


def connected_after(conn: IntegrationConnection, when: datetime | None) -> bool:
    """Only records from after the connection was switched on are sent."""
    return conn.connected_at is None or when is None or when >= conn.connected_at
