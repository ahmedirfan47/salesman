"""Invoice PDF (A4). Seller and bank details come from the BILLING_* settings."""
from decimal import Decimal

from fpdf import FPDF

from app.config import settings
from app.db.models.billing import Invoice

_STATUS_LABEL = {"open": "UNPAID", "paid": "PAID", "void": "VOID"}


def _san(text) -> str:
    """fpdf core fonts are latin-1; anything else (e.g. Arabic) prints as '?'."""
    return str(text or "").replace("—", "-").replace("–", "-").encode("latin-1", "replace").decode("latin-1")


def _lines(value: str) -> list[str]:
    return [part.strip() for part in (value or "").replace("\n", "|").split("|") if part.strip()]


def _amount(currency: str, value) -> str:
    return f"{currency} {Decimal(str(value)):,.2f}"


def render_invoice_pdf(invoice: Invoice) -> bytes:
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_margins(18, 18, 18)
    width = pdf.w - 36
    ccy = invoice.currency

    # seller
    pdf.set_xy(18, 18)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(width / 2, 9, _san(settings.BILLING_SELLER_NAME))
    pdf.set_font("Helvetica", "B", 22)
    pdf.cell(width / 2, 9, "INVOICE", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90)
    for line in _lines(settings.BILLING_SELLER_ADDRESS):
        pdf.cell(width, 4.5, _san(line), new_x="LMARGIN", new_y="NEXT")
    if settings.BILLING_SELLER_EMAIL:
        pdf.cell(width, 4.5, _san(settings.BILLING_SELLER_EMAIL), new_x="LMARGIN", new_y="NEXT")
    if settings.BILLING_SELLER_TAX_ID:
        pdf.cell(width, 4.5, _san(f"Tax ID: {settings.BILLING_SELLER_TAX_ID}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    pdf.ln(6)

    # bill to + invoice facts
    top = pdf.get_y()
    bill = invoice.bill_to or {}
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(120)
    pdf.cell(width / 2, 5, "BILL TO", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(width / 2, 6, _san(bill.get("name")), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    for line in _lines(bill.get("address") or ""):
        pdf.cell(width / 2, 4.5, _san(line), new_x="LMARGIN", new_y="NEXT")
    if bill.get("tax_id"):
        pdf.cell(width / 2, 4.5, _san(f"Tax ID: {bill['tax_id']}"), new_x="LMARGIN", new_y="NEXT")
    if bill.get("email"):
        pdf.cell(width / 2, 4.5, _san(bill["email"]), new_x="LMARGIN", new_y="NEXT")
    left_bottom = pdf.get_y()

    facts = [("Invoice number", invoice.number), ("Issue date", f"{invoice.issued_on:%d %b %Y}"),
             ("Due date", f"{invoice.due_on:%d %b %Y}")]
    if invoice.period_start and invoice.period_end:
        facts.append(("Period", f"{invoice.period_start:%d %b %Y} - {invoice.period_end:%d %b %Y}"))
    facts.append(("Status", _STATUS_LABEL.get(invoice.status, invoice.status.upper())))
    pdf.set_xy(18 + width / 2, top)
    for label, value in facts:
        pdf.set_x(18 + width / 2)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(120)
        pdf.cell(width / 4, 5.5, label)
        pdf.set_text_color(0)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(width / 4, 5.5, _san(value), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(max(left_bottom, pdf.get_y()) + 8)

    # lines
    cols = (width * 0.55, width * 0.12, width * 0.16, width * 0.17)
    pdf.set_fill_color(242, 243, 247)
    pdf.set_font("Helvetica", "B", 9)
    for label, w, align in zip(("Description", "Qty", "Unit price", "Amount"), cols, ("L", "R", "R", "R")):
        pdf.cell(w, 8, label, fill=True, align=align)
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 9)
    for line in invoice.lines:
        y = pdf.get_y()
        pdf.multi_cell(cols[0], 5.5, _san(line["description"]), new_x="RIGHT", new_y="TOP")
        row_h = max(pdf.get_y() - y, 5.5)
        pdf.set_xy(18 + cols[0], y)
        pdf.cell(cols[1], 5.5, _san(line["quantity"]), align="R")
        pdf.cell(cols[2], 5.5, f"{Decimal(line['unit_amount']):,.2f}", align="R")
        pdf.cell(cols[3], 5.5, f"{Decimal(line['amount']):,.2f}", align="R")
        pdf.set_y(y + max(row_h, 5.5) + 2)
        pdf.set_draw_color(225)
        pdf.line(18, pdf.get_y(), 18 + width, pdf.get_y())
        pdf.ln(1)

    # totals
    pdf.ln(3)
    label_w, value_w = width * 0.25, width * 0.2
    x = 18 + width - label_w - value_w
    rows = [("Subtotal", _amount(ccy, invoice.subtotal))]
    if Decimal(str(invoice.tax_percent)) > 0:
        rows.append((f"VAT {Decimal(str(invoice.tax_percent)).normalize():f}%", _amount(ccy, invoice.tax_amount)))
    for label, value in rows:
        pdf.set_x(x)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(label_w, 6, label)
        pdf.cell(value_w, 6, value, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(x)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(label_w, 9, "Total")
    pdf.cell(value_w, 9, _amount(ccy, invoice.total), align="R", new_x="LMARGIN", new_y="NEXT")

    # status / payment
    pdf.ln(8)
    if invoice.status == "paid":
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(4, 120, 87)
        ref = f" (ref. {invoice.payment_reference})" if invoice.payment_reference else ""
        pdf.cell(width, 6, _san(f"Paid on {invoice.paid_on:%d %b %Y}{ref}. Thank you."), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0)
    elif invoice.status == "void":
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(185, 28, 28)
        pdf.cell(width, 6, _san(f"This invoice was voided: {invoice.void_reason or ''}"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0)
    else:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(width, 6, "Payment by bank transfer", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        for line in _lines(settings.BILLING_BANK_DETAILS) or ["Bank details will be sent to you by the Stonic team."]:
            pdf.cell(width, 5, _san(line), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        pdf.cell(width, 5, _san(f"Please use {invoice.number} as the payment reference."), new_x="LMARGIN", new_y="NEXT")

    if invoice.notes:
        pdf.ln(4)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(90)
        pdf.multi_cell(width, 5, _san(invoice.notes))
        pdf.set_text_color(0)

    pdf.ln(6)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(140)
    pdf.cell(width, 4, "Amounts exclude VAT unless VAT is shown above.", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())