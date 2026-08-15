"""Printing: enqueue order slips + render a printable slip PDF.

enqueue_for_order() is called when an order is confirmed. The on-site print
agent polls list_jobs(status='queued'), renders/prints each slip, then calls
mark_status(). Slip PDF is a narrow (80mm) thermal-receipt layout.
"""
import uuid
from datetime import datetime, timezone

from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.order import Order
from app.db.models.print_job import PrintJob


def _slip_payload(order: Order, items: list[dict]) -> dict:
    created = order.created_at or datetime.now(timezone.utc)
    return {
        "order_number": order.order_number,
        "customer_name": order.customer_name or "-",
        "customer_company": order.customer_company or "",
        "whatsapp_number": order.whatsapp_number or "",
        "currency": order.currency,
        "total_amount": float(order.total_amount),
        "created_at": created.strftime("%Y-%m-%d %H:%M"),
        "items": items,
    }


async def enqueue_for_order(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    order: Order,
    items: list[dict],
    *,
    location: str | None = None,
) -> PrintJob:
    """Queue a slip. `items` is a list of {sku,name,quantity,unit_price,line_total}
    passed by the caller (avoids lazy-loading order.items inside async)."""
    job = PrintJob(
        tenant_id=tenant_id,
        order_id=order.id,
        payload=_slip_payload(order, items),
        status="queued",
        location=location,
    )
    db.add(job)
    # caller commits (so it joins the order's transaction)
    return job


async def list_jobs(
    db: AsyncSession, tenant_id: uuid.UUID, *, status: str | None = None
) -> list[PrintJob]:
    stmt = select(PrintJob).where(PrintJob.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(PrintJob.status == status)
    return list(await db.scalars(stmt.order_by(PrintJob.created_at)))


async def mark_status(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    status: str,
    error: str | None = None,
) -> PrintJob:
    from fastapi import HTTPException

    job = await db.scalar(
        select(PrintJob).where(PrintJob.id == job_id, PrintJob.tenant_id == tenant_id)
    )
    if not job:
        raise HTTPException(404, "Print job not found")
    job.status = status
    job.error = error
    if status == "done":
        job.printed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(job)
    return job


def _san(text: str) -> str:
    return (text or "").encode("latin-1", "replace").decode("latin-1")


def render_slip_pdf(business_name: str, payload: dict) -> bytes:
    """80mm-wide thermal receipt style slip."""
    W = 80  # mm
    pdf = FPDF(orientation="P", unit="mm", format=(W, 200))
    pdf.set_margins(4, 5, 4)
    pdf.add_page()
    inner = W - 8

    pdf.set_font("Helvetica", "B", 12)
    pdf.multi_cell(inner, 6, _san(business_name), align="C")
    pdf.set_font("Helvetica", "", 8)
    pdf.multi_cell(inner, 4, "ORDER SLIP", align="C")
    pdf.ln(1)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(inner, 5, _san(payload["order_number"]), ln=True, align="C")
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(inner, 4, payload["created_at"], ln=True, align="C")
    pdf.ln(1)

    pdf.set_font("Helvetica", "", 8)
    pdf.cell(inner, 4, f"Customer: {_san(payload['customer_name'])}", ln=True)
    if payload.get("customer_company"):
        pdf.cell(inner, 4, f"Company: {_san(payload['customer_company'])}", ln=True)
    if payload.get("whatsapp_number"):
        pdf.cell(inner, 4, f"WhatsApp: {_san(payload['whatsapp_number'])}", ln=True)

    pdf.ln(1)
    pdf.cell(inner, 0, "", border="T", ln=True)
    pdf.ln(1)

    cur = payload["currency"]
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(inner * 0.5, 4, "Item")
    pdf.cell(inner * 0.15, 4, "Qty", align="R")
    pdf.cell(inner * 0.35, 4, "Total", align="R", ln=True)
    pdf.set_font("Helvetica", "", 8)
    for it in payload["items"]:
        name = _san(it["name"])[:22]
        pdf.cell(inner * 0.5, 4, name)
        pdf.cell(inner * 0.15, 4, str(it["quantity"]), align="R")
        pdf.cell(inner * 0.35, 4, f"{it['line_total']:,.2f}", align="R", ln=True)
        pdf.set_text_color(120)
        pdf.set_font("Helvetica", "", 6)
        pdf.cell(inner, 3, f"  {it['sku']} @ {it['unit_price']:,.2f}", ln=True)
        pdf.set_text_color(0)
        pdf.set_font("Helvetica", "", 8)

    pdf.ln(1)
    pdf.cell(inner, 0, "", border="T", ln=True)
    pdf.ln(1)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(inner * 0.5, 6, "TOTAL")
    pdf.cell(inner * 0.5, 6, f"{cur} {payload['total_amount']:,.2f}", align="R", ln=True)

    pdf.ln(3)
    pdf.set_font("Helvetica", "", 7)
    pdf.multi_cell(inner, 3, "Thank you!", align="C")

    return bytes(pdf.output())