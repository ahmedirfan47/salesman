"""Tax invoice, credit note and statement PDFs, in English with Arabic labels.

Arabic names and addresses print properly: the Noto Sans fonts in
app/assets/fonts are embedded, Arabic falls back to Noto Sans Arabic, and
text is shaped right-to-left with HarfBuzz. If the font files are missing
(e.g. a fresh checkout before they were downloaded), the PDF still renders
with the built-in font and Arabic prints as '?'.

When the invoice is a ZATCA e-invoice, its QR code is printed (for standard
invoices, the one from the XML ZATCA cleared).
"""
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import segno
from fpdf import FPDF

from app.db.models.accounts import SalesInvoice

FONTS = Path(__file__).resolve().parents[2] / "assets" / "fonts"
_FILES = {
    ("NotoSans", ""): "NotoSans-Regular.ttf",
    ("NotoSans", "B"): "NotoSans-Bold.ttf",
    ("NotoSansArabic", ""): "NotoSansArabic-Regular.ttf",
    ("NotoSansArabic", "B"): "NotoSansArabic-Bold.ttf",
}

_KIND_TITLE = {
    "invoice": ("TAX INVOICE", "فاتورة ضريبية"),
    "simplified": ("SIMPLIFIED TAX INVOICE", "فاتورة ضريبية مبسطة"),
    "credit_note": ("CREDIT NOTE", "إشعار دائن"),
    "simplified_credit_note": ("SIMPLIFIED CREDIT NOTE", "إشعار دائن مبسط"),
    "opening_balance": ("OPENING BALANCE", "رصيد افتتاحي"),
}
_STATUS = {"open": "UNPAID", "partially_paid": "PART PAID", "paid": "PAID", "issued": "ISSUED"}
_KIND_LABEL = {
    "invoice": "Invoice", "credit_note": "Credit note", "opening_balance": "Opening balance",
    "payment": "Payment", "payment_void": "Payment reversed",
}


class _Doc(FPDF):
    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.unicode = all((FONTS / name).exists() for name in _FILES.values())
        if self.unicode:
            for (family, style), name in _FILES.items():
                self.add_font(family, style, str(FONTS / name))
            self.set_fallback_fonts(["NotoSansArabic"], exact_match=False)
            try:
                self.set_text_shaping(True)  # needs uharfbuzz; joins and orders Arabic correctly
            except Exception:  # noqa: BLE001
                pass
        self.family = "NotoSans" if self.unicode else "Helvetica"
        self.set_auto_page_break(auto=True, margin=16)
        self.set_margins(16, 16, 16)
        self.footer_text = ""

    def text_(self, value) -> str:
        text = str(value if value is not None else "")
        if self.unicode:
            return text
        return text.replace("—", "-").replace("–", "-").encode("latin-1", "replace").decode("latin-1")

    def font(self, size: float, bold: bool = False, grey: int | None = None) -> None:
        self.set_font(self.family, "B" if bold else "", size)
        self.set_text_color(grey if grey is not None else 0)

    def footer(self) -> None:
        self.set_y(-12)
        self.font(7.5, grey=140)
        left = self.text_(self.footer_text)[:150]
        self.cell(0, 5, left, align="L")
        self.set_x(self.l_margin)
        self.cell(0, 5, f"Page {self.page_no()}/{{nb}}", align="R")


def _money(value) -> str:
    return f"{Decimal(str(value or 0)):,.2f}"


def _day(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return f"{value.day} {value:%b %Y}"


def national_address(party: dict) -> str | None:
    """'Building, Street, District, City Postal code' when the structured address is filled in."""
    parts = [
        " ".join(p for p in (party.get("building_number"), party.get("street")) if p),
        party.get("district"),
        " ".join(p for p in (party.get("city"), party.get("postal_code")) if p),
    ]
    text = ", ".join(p for p in parts if p)
    return text or None


def _seller_block(pdf: _Doc, seller: dict, width: float) -> None:
    pdf.font(15, bold=True)
    pdf.cell(width, 7, pdf.text_(seller.get("name") or ""), new_x="LMARGIN", new_y="NEXT")
    if seller.get("name_ar"):
        pdf.font(10, bold=True, grey=60)
        pdf.cell(width, 5.5, pdf.text_(seller["name_ar"]), new_x="LMARGIN", new_y="NEXT")
    pdf.font(8.5, grey=90)
    for line in [seller.get("address") or national_address(seller)] + [
        # number between the English and Arabic labels, so right-to-left text never swaps it round
        f"VAT No. {seller['vat_number']}  |  الرقم الضريبي" if seller.get("vat_number") else None,
        f"CR No. {seller['cr_number']}  |  السجل التجاري" if seller.get("cr_number") else None,
    ]:
        if line:
            pdf.multi_cell(width, 4.4, pdf.text_(line), new_x="LMARGIN", new_y="NEXT")


def _party_block(pdf: _Doc, label_en: str, label_ar: str, party: dict, x: float, y: float, width: float) -> float:
    pdf.set_xy(x, y)
    pdf.font(7.5, bold=True, grey=120)
    pdf.cell(width, 4.5, pdf.text_(f"{label_en} / {label_ar}"), new_x="LEFT", new_y="NEXT")
    pdf.font(10.5, bold=True)
    pdf.multi_cell(width, 5.2, pdf.text_(party.get("name") or "—"), new_x="LEFT", new_y="NEXT")
    pdf.font(8.5, grey=70)
    for line in (
        party.get("company") if party.get("company") and party.get("company") != party.get("name") else None,
        national_address(party) or party.get("address"),
        party.get("phone"),
        f"VAT No.: {party['vat_number']}" if party.get("vat_number") else None,
        f"CR No.: {party['cr_number']}" if party.get("cr_number") else None,
    ):
        if line:
            pdf.multi_cell(width, 4.4, pdf.text_(line), new_x="LEFT", new_y="NEXT")
    return pdf.get_y()


def _facts(pdf: _Doc, rows: list[tuple[str, str]], x: float, y: float, width: float) -> float:
    pdf.set_xy(x, y)
    for label, value in rows:
        pdf.set_x(x)
        pdf.font(8.5, grey=110)
        pdf.cell(width * 0.5, 5, pdf.text_(label))
        pdf.font(8.5, bold=True)
        pdf.cell(width * 0.5, 5, pdf.text_(value), align="R", new_x="LMARGIN", new_y="NEXT")
    return pdf.get_y()


def _table_header(pdf: _Doc, cols: list[tuple[str, float, str]]) -> None:
    pdf.set_fill_color(243, 244, 248)
    pdf.font(7.5, bold=True, grey=80)
    for label, w, align in cols:
        pdf.cell(w, 7, pdf.text_(label), border="B", align=align, fill=True)
    pdf.ln()


_EINVOICE_NOTE = {
    "cleared": "Cleared by ZATCA / معتمدة من هيئة الزكاة والضريبة والجمارك",
    "reported": "Reported to ZATCA / تم الإبلاغ عنها لهيئة الزكاة والضريبة والجمارك",
    "queued": "E-invoice being sent to ZATCA / جاري إرسال الفاتورة الإلكترونية",
    "rejected": "E-invoice rejected by ZATCA: being corrected / الفاتورة الإلكترونية قيد التصحيح",
    "blocked": "E-invoice details incomplete / بيانات الفاتورة الإلكترونية غير مكتملة",
}


def _qr_png(payload: str) -> BytesIO:
    out = BytesIO()
    segno.make(payload, error="m").save(out, kind="png", scale=6, border=2)
    out.seek(0)
    return out


def render_invoice_pdf(inv: SalesInvoice, einvoice: dict | None = None) -> bytes:
    """einvoice: {"flow": "standard"|"simplified", "status": ..., "qr": base64 TLV or None} when ZATCA applies."""
    pdf = _Doc()
    pdf.alias_nb_pages()
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin
    ccy = inv.currency
    seller, buyer = inv.seller or {}, inv.buyer or {}
    kind = inv.kind
    b2c = (einvoice["flow"] == "simplified") if einvoice else not (buyer.get("vat_number") or buyer.get("cr_number"))
    if kind == "invoice" and b2c:
        kind = "simplified"
    elif kind == "credit_note" and einvoice and b2c:
        kind = "simplified_credit_note"
    title_en, title_ar = _KIND_TITLE[kind]
    pdf.footer_text = f"{seller.get('name') or ''} · {inv.number}"

    top = pdf.get_y()
    _seller_block(pdf, seller, width * 0.58)
    after_seller = pdf.get_y()
    pdf.set_xy(pdf.l_margin + width * 0.58, top)
    pdf.font(15, bold=True)
    pdf.cell(width * 0.42, 7, pdf.text_(title_en), align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_x(pdf.l_margin + width * 0.58)
    pdf.font(11, bold=True, grey=60)
    pdf.cell(width * 0.42, 6, pdf.text_(title_ar), align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_x(pdf.l_margin + width * 0.58)
    pdf.font(9, bold=True, grey=120)
    pdf.cell(width * 0.42, 5, _STATUS.get(inv.status, inv.status.upper()), align="R")
    pdf.set_y(max(after_seller, pdf.get_y()) + 6)

    y = pdf.get_y()
    left_end = _party_block(pdf, "BILL TO", "العميل", buyer, pdf.l_margin, y, width * 0.55)
    facts = [
        ("Number / الرقم", inv.number),
        ("Issue date / تاريخ الإصدار", _day(inv.issue_date)),
    ]
    if inv.kind != "credit_note":
        facts.append(("Due date / تاريخ الاستحقاق", _day(inv.due_date)))
    if inv.reason:
        facts.append(("Reason / السبب", inv.reason[:40]))
    right_end = _facts(pdf, facts, pdf.l_margin + width * 0.6, y, width * 0.4)
    pdf.set_y(max(left_end, right_end) + 6)

    # lines
    if inv.lines:
        cols = [
            ("Description / الوصف", width * 0.38, "L"), ("Qty", width * 0.08, "R"), ("Unit price", width * 0.12, "R"),
            ("Net", width * 0.12, "R"), ("VAT %", width * 0.08, "R"), ("VAT", width * 0.10, "R"), ("Total", width * 0.12, "R"),
        ]
        _table_header(pdf, cols)
        for ln in inv.lines:
            if pdf.get_y() > pdf.h - 40:
                pdf.add_page()
                _table_header(pdf, cols)
            pdf.font(8.5)
            name = ln.get("name") or ""
            if ln.get("sku"):
                name = f"{name} ({ln['sku']})"
            y0 = pdf.get_y()
            pdf.multi_cell(cols[0][1], 5, pdf.text_(name), new_x="RIGHT", new_y="TOP")
            h = max(pdf.get_y() - y0, 6)
            pdf.set_xy(pdf.l_margin + cols[0][1], y0)
            for value, (_, w, align) in zip(
                (ln.get("quantity"), _money(ln.get("unit_price")), _money(ln.get("net")),
                 f"{Decimal(str(ln.get('vat_rate') or 0)):.0f}%", _money(ln.get("vat")), _money(ln.get("total"))),
                cols[1:],
            ):
                pdf.cell(w, 6, pdf.text_(value), align=align)
            pdf.set_y(y0 + h)
            pdf.set_draw_color(230)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + width, pdf.get_y())
        pdf.ln(4)

    # totals (the e-invoice QR code sits to their left)
    totals_top = pdf.get_y()
    if einvoice:
        qr = einvoice.get("qr")
        show_qr = qr and (einvoice.get("flow") == "simplified" or einvoice.get("status") == "cleared")
        if show_qr:
            pdf.image(_qr_png(qr), x=pdf.l_margin, y=totals_top, w=32, h=32)
        note = _EINVOICE_NOTE.get(einvoice.get("status") or "")
        if note:
            pdf.set_xy(pdf.l_margin + (35 if show_qr else 0), totals_top + (2 if show_qr else 0))
            pdf.font(7.5, grey=90)
            pdf.multi_cell(width * 0.5 - (35 if show_qr else 0), 4, pdf.text_(note))
        pdf.set_y(totals_top)
    x = pdf.l_margin + width * 0.55
    rows = [("Subtotal excl. VAT / المجموع بدون الضريبة", inv.subtotal), ("VAT / ضريبة القيمة المضافة", inv.vat_amount)]
    for label, value in rows:
        pdf.set_x(x)
        pdf.font(8.5, grey=90)
        pdf.cell(width * 0.30, 6, pdf.text_(label))
        pdf.font(8.5)
        pdf.cell(width * 0.15, 6, _money(value), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(x)
    pdf.font(10, bold=True)
    pdf.cell(width * 0.30, 8, pdf.text_("Total / الإجمالي"), border="T")
    pdf.cell(width * 0.15, 8, f"{ccy} {_money(inv.total)}", border="T", align="R", new_x="LMARGIN", new_y="NEXT")
    if inv.kind != "credit_note" and (Decimal(str(inv.amount_paid)) > 0 or Decimal(str(inv.amount_credited)) > 0):
        for label, value in (("Paid / المدفوع", inv.amount_paid), ("Credited / الإشعارات الدائنة", inv.amount_credited),
                             ("Balance due / المبلغ المستحق", inv.balance_due)):
            pdf.set_x(x)
            pdf.font(8.5, bold=label.startswith("Balance"))
            pdf.cell(width * 0.30, 6, pdf.text_(label))
            pdf.cell(width * 0.15, 6, _money(value), align="R", new_x="LMARGIN", new_y="NEXT")

    if einvoice and einvoice.get("qr"):
        pdf.set_y(max(pdf.get_y(), totals_top + 34))
    if inv.notes:
        pdf.ln(4)
        pdf.font(8.5, grey=80)
        pdf.multi_cell(width, 4.5, pdf.text_(inv.notes))
    return bytes(pdf.output())


def render_statement_pdf(data: dict) -> bytes:
    pdf = _Doc()
    pdf.alias_nb_pages()
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin
    ccy = data["currency"]
    seller, customer, summary = data["seller"] or {}, data["customer"], data["summary"]
    pdf.footer_text = f"{seller.get('name') or ''} · Statement for {customer.get('name') or ''}"

    top = pdf.get_y()
    _seller_block(pdf, seller, width * 0.58)
    after_seller = pdf.get_y()
    pdf.set_xy(pdf.l_margin + width * 0.5, top)
    pdf.font(15, bold=True)
    pdf.cell(width * 0.5, 7, "STATEMENT OF ACCOUNT", align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_x(pdf.l_margin + width * 0.5)
    pdf.font(11, bold=True, grey=60)
    pdf.cell(width * 0.5, 6, pdf.text_("كشف حساب"), align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_x(pdf.l_margin + width * 0.5)
    pdf.font(8.5, grey=110)
    pdf.cell(width * 0.5, 5, f"{_day(data['start'])} to {_day(data['end'])}", align="R")
    pdf.set_y(max(after_seller, pdf.get_y()) + 6)

    y = pdf.get_y()
    left_end = _party_block(pdf, "CUSTOMER", "العميل", customer, pdf.l_margin, y, width * 0.55)
    limit = summary.get("credit_limit")
    facts = [
        ("Statement date / التاريخ", _day(data["generated_on"])),
        ("Payment terms / مدة السداد", f"{summary['payment_terms_days']} days"),
        ("Credit limit / الحد الائتماني", f"{ccy} {_money(limit)}" if limit is not None else "No limit"),
    ]
    right_end = _facts(pdf, facts, pdf.l_margin + width * 0.6, y, width * 0.4)
    pdf.set_y(max(left_end, right_end) + 6)

    # summary boxes
    boxes = [
        ("Opening balance", data["opening_balance"]), ("Invoiced", data["total_debits"]),
        ("Paid and credited", data["total_credits"]), ("Balance due", data["closing_balance"]),
    ]
    bw = width / 4
    y = pdf.get_y()
    for i, (label, value) in enumerate(boxes):
        pdf.set_fill_color(238, 241, 253) if i == 3 else pdf.set_fill_color(246, 247, 250)
        pdf.rect(pdf.l_margin + i * bw + (1 if i else 0), y, bw - 2, 15, style="F")
        pdf.set_xy(pdf.l_margin + i * bw + 3, y + 2)
        pdf.font(7.5, grey=110)
        pdf.cell(bw - 6, 4, label)
        pdf.set_xy(pdf.l_margin + i * bw + 3, y + 7)
        pdf.font(10.5, bold=True)
        pdf.cell(bw - 6, 6, f"{ccy} {_money(value)}")
    pdf.set_y(y + 21)

    cols = [
        ("Date", width * 0.12, "L"), ("Document", width * 0.15, "L"), ("Description", width * 0.37, "L"),
        ("Debit", width * 0.12, "R"), ("Credit", width * 0.12, "R"), ("Balance", width * 0.12, "R"),
    ]
    _table_header(pdf, cols)
    pdf.font(8.5, grey=90)
    pdf.cell(cols[0][1] + cols[1][1], 6, _day(data["start"]))
    pdf.cell(cols[2][1], 6, "Opening balance")
    pdf.cell(cols[3][1] + cols[4][1], 6, "")
    pdf.cell(cols[5][1], 6, _money(data["opening_balance"]), align="R", new_x="LMARGIN", new_y="NEXT")
    for ln in data["lines"]:
        if pdf.get_y() > pdf.h - 30:
            pdf.add_page()
            _table_header(pdf, cols)
        pdf.font(8.5)
        y0 = pdf.get_y()
        pdf.cell(cols[0][1], 6, _day(ln["date"]))
        pdf.cell(cols[1][1], 6, pdf.text_(ln["document_number"]))
        pdf.multi_cell(cols[2][1], 6, pdf.text_(ln["description"])[:120], new_x="RIGHT", new_y="TOP")
        h = max(pdf.get_y() - y0, 6)
        pdf.set_xy(pdf.l_margin + cols[0][1] + cols[1][1] + cols[2][1], y0)
        pdf.cell(cols[3][1], 6, _money(ln["debit"]) if ln["debit"] else "", align="R")
        pdf.cell(cols[4][1], 6, _money(ln["credit"]) if ln["credit"] else "", align="R")
        pdf.font(8.5, bold=True)
        pdf.cell(cols[5][1], 6, _money(ln["balance"]), align="R")
        pdf.set_y(y0 + h)
        pdf.set_draw_color(232)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + width, pdf.get_y())
    if not data["lines"]:
        pdf.font(8.5, grey=130)
        pdf.cell(width, 8, "No activity in this period.", new_x="LMARGIN", new_y="NEXT")

    # aging
    pdf.ln(6)
    if pdf.get_y() > pdf.h - 40:
        pdf.add_page()
    pdf.font(8, bold=True, grey=80)
    pdf.cell(width, 5, pdf.text_("AMOUNT DUE BY AGE / أعمار الديون"), new_x="LMARGIN", new_y="NEXT")
    aging = summary["aging"]
    labels = [("Not yet due", "current"), ("1-30 days", "days_1_30"), ("31-60 days", "days_31_60"),
              ("61-90 days", "days_61_90"), ("Over 90 days", "days_90_plus")]
    cw = width / len(labels)
    pdf.font(7.5, grey=110)
    for label, _ in labels:
        pdf.cell(cw, 5, label, border="B", align="C")
    pdf.ln()
    pdf.font(9, bold=True)
    for _, key in labels:
        pdf.cell(cw, 7, _money(aging[key]), align="C")
    pdf.ln(10)
    if Decimal(str(summary.get("unapplied") or 0)) > 0:
        pdf.font(8.5, grey=80)
        pdf.cell(width, 5, f"Unapplied credit on account: {ccy} {_money(summary['unapplied'])}", new_x="LMARGIN", new_y="NEXT")
    if data.get("footer"):
        pdf.ln(2)
        pdf.font(8.5, grey=80)
        pdf.multi_cell(width, 4.5, pdf.text_(data["footer"]))
    return bytes(pdf.output())


def statement_filename(data: dict) -> str:
    safe = "".join(ch for ch in (data["customer"].get("name") or "customer") if ch.isalnum() or ch in " -_").strip()
    return f"Statement {safe or 'customer'} {data['end']}.pdf"