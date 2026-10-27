"""PDFs requested on WhatsApp: a customer's statement or a copy of one of their invoices.

The AI agent queues a WHATSAPP_SEND_DOCUMENT job; the job calls build() so
the PDF reflects the account at the moment it is sent.
"""
import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import SalesInvoice
from app.db.models.customer import Customer
from app.modules.accounts import pdf as account_pdf
from app.modules.accounts import service
from app.modules.zatca import service as zatca


async def build(db: AsyncSession, p: dict) -> tuple[bytes, str, str] | None:
    tenant_id = uuid.UUID(p["tenant_id"])
    arabic = p.get("language") == "ar"
    if p.get("doc") == "statement":
        customer = await db.get(Customer, uuid.UUID(p["customer_id"]))
        if customer is None or customer.tenant_id != tenant_id:
            return None
        data = await service.statement(
            db, tenant_id, customer,
            start=date.fromisoformat(p["start"]) if p.get("start") else None,
            end=date.fromisoformat(p["end"]) if p.get("end") else None,
        )
        ccy = data["currency"]
        caption = (
            f"كشف حسابك. الرصيد المستحق: {data['closing_balance']:,.2f} {ccy}"
            if arabic else f"Your statement. Balance due: {ccy} {data['closing_balance']:,.2f}"
        )
        return account_pdf.render_statement_pdf(data), account_pdf.statement_filename(data), caption
    if p.get("doc") == "invoice":
        inv = await db.get(SalesInvoice, uuid.UUID(p["invoice_id"]))
        if inv is None or inv.tenant_id != tenant_id:
            return None
        caption = f"نسخة من {inv.number}" if arabic else f"Copy of {inv.number}"
        return account_pdf.render_invoice_pdf(inv, await zatca.einvoice_for_pdf(db, inv)), f"{inv.number}.pdf", caption
    return None