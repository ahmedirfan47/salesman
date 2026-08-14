"""Parse an uploaded .xlsx price sheet into validated price lines.

Real-world sheets have inconsistent headers, so we match each required field
against a set of known aliases (English + Arabic). If a required column is
missing, we fail loudly rather than guess -- protecting the 'never hallucinate
prices' rule at the ingestion layer.
"""
from __future__ import annotations

import io
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook

from app.schemas.pricing import PriceLineIn

# header aliases (lowercased) -> canonical field
_ALIASES: dict[str, set[str]] = {
    "sku": {"sku", "code", "item code", "product code", "id", "الرمز", "الكود"},
    "name": {"name", "product", "product name", "item", "description", "الاسم", "المنتج"},
    "price": {"price", "unit price", "rate", "cost", "amount", "السعر", "الثمن"},
    "quantity": {"quantity", "qty", "stock", "available", "quantity available",
                 "الكمية", "المخزون"},
}


class ExcelParseError(Exception):
    """Raised when the sheet can't be parsed or a required column is missing."""


def _canonical(header: str | None) -> str | None:
    if header is None:
        return None
    h = str(header).strip().lower()
    for field, aliases in _ALIASES.items():
        if h in aliases:
            return field
    return None


def parse_price_sheet(file_bytes: bytes) -> list[PriceLineIn]:
    try:
        wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise ExcelParseError(f"Could not open the file as an Excel workbook: {exc}") from exc

    ws = wb.active
    rows = ws.iter_rows(values_only=True)

    # locate the header row (first row containing a recognizable SKU + price column)
    header_map: dict[str, int] = {}
    header_found = False
    for raw in rows:
        mapping = {}
        for idx, cell in enumerate(raw):
            field = _canonical(cell)
            if field and field not in mapping:
                mapping[field] = idx
        if "sku" in mapping and "price" in mapping:
            header_map = mapping
            header_found = True
            break

    if not header_found:
        raise ExcelParseError(
            "Could not find a header row. The sheet must have columns for at least "
            "SKU and Price (recognized names include: sku/code, price/unit price)."
        )

    missing = [f for f in ("sku", "price", "quantity") if f not in header_map]
    if missing:
        raise ExcelParseError(f"Missing required column(s): {', '.join(missing)}")

    lines: list[PriceLineIn] = []
    errors: list[str] = []
    for row_num, raw in enumerate(rows, start=2):  # remaining rows after header
        sku_cell = raw[header_map["sku"]] if header_map["sku"] < len(raw) else None
        if sku_cell is None or str(sku_cell).strip() == "":
            continue  # skip blank rows

        sku = str(sku_cell).strip()
        try:
            price = Decimal(str(raw[header_map["price"]]).strip())
        except (InvalidOperation, AttributeError, TypeError):
            errors.append(f"Row {row_num} (SKU {sku}): price is not a valid number")
            continue

        qty_raw = raw[header_map["quantity"]] if header_map["quantity"] < len(raw) else 0
        try:
            quantity = int(float(qty_raw)) if qty_raw is not None else 0
        except (ValueError, TypeError):
            errors.append(f"Row {row_num} (SKU {sku}): quantity is not a valid number")
            continue

        if price < 0 or quantity < 0:
            errors.append(f"Row {row_num} (SKU {sku}): price and quantity must be >= 0")
            continue

        name = None
        if "name" in header_map and header_map["name"] < len(raw):
            name_cell = raw[header_map["name"]]
            name = str(name_cell).strip() if name_cell is not None else None

        lines.append(
            PriceLineIn(sku=sku, unit_price=price, quantity=quantity, name_en=name)
        )

    wb.close()

    if errors:
        raise ExcelParseError("Problems found in the sheet:\n- " + "\n- ".join(errors))
    if not lines:
        raise ExcelParseError("No product rows found in the sheet.")

    return lines