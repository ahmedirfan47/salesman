"""Tests for the Excel price-sheet parser (no database needed)."""
import io
from decimal import Decimal

import pytest
from openpyxl import Workbook

from app.modules.pricing.excel_parser import ExcelParseError, parse_price_sheet


def _xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _by_sku(lines):
    return {line.sku: line for line in lines}


def test_basic_sheet():
    lines = parse_price_sheet(_xlsx([
        ["SKU", "Name", "Price", "Qty"],
        ["TOM-5", "Tomatoes 5 kg", 35, 212],
        ["POT-10", "Potatoes 10 kg", 22.5, 140],
    ]))
    by = _by_sku(lines)
    assert by["TOM-5"].unit_price == Decimal("35") and by["TOM-5"].quantity == 212
    assert by["POT-10"].unit_price == Decimal("22.5") and by["POT-10"].name_en == "Potatoes 10 kg"


def test_cost_column_is_never_used_as_price_even_when_it_comes_first():
    lines = parse_price_sheet(_xlsx([
        ["SKU", "Cost", "Price", "Qty"],
        ["TOM-5", 24.5, 35, 10],
    ]))
    assert lines[0].unit_price == Decimal("35")


def test_sheet_with_only_a_cost_column_is_rejected():
    with pytest.raises(ExcelParseError, match="header row"):
        parse_price_sheet(_xlsx([["SKU", "Cost", "Qty"], ["TOM-5", 24.5, 10]]))


def test_two_possible_price_columns_are_rejected():
    with pytest.raises(ExcelParseError, match="More than one column could be the price"):
        parse_price_sheet(_xlsx([["SKU", "Price", "Rate", "Qty"], ["A", 10, 12, 1]]))


def test_amount_is_not_treated_as_price():
    # "Amount" is often a line total; it must not be read as the unit price.
    lines = parse_price_sheet(_xlsx([["SKU", "Price", "Qty", "Amount"], ["A", 10, 3, 30]]))
    assert lines[0].unit_price == Decimal("10")


def test_row_numbers_are_correct_when_header_is_not_on_row_1():
    with pytest.raises(ExcelParseError) as e:
        parse_price_sheet(_xlsx([
            ["Al Rayyan Fresh — price list"],
            [],
            ["SKU", "Price", "Qty"],
            ["A", 10, 1],
            ["B", "abc", 1],
        ]))
    assert "Row 5 (SKU B)" in str(e.value)


def test_arabic_headers_digits_and_currency_label():
    lines = parse_price_sheet(_xlsx([
        ["الرمز", "اسم المنتج", "السعر", "الكمية"],
        ["TOM-5", "طماطم", "٣٥ ر.س", "٢١٢"],
    ]))
    line = lines[0]
    assert line.unit_price == Decimal("35")
    assert line.quantity == 212
    assert line.currency == "SAR"


def test_thousands_separator_and_currency_prefix():
    lines = parse_price_sheet(_xlsx([["SKU", "Price", "Qty"], ["A", "SAR 1,050.50", 5]]))
    assert lines[0].unit_price == Decimal("1050.50")
    assert lines[0].currency == "SAR"


def test_currency_from_header():
    lines = parse_price_sheet(_xlsx([["SKU", "Unit Price (SAR)", "Qty"], ["A", 35, 5]]))
    assert lines[0].currency == "SAR"


def test_currency_column():
    lines = parse_price_sheet(_xlsx([["SKU", "Price", "Currency", "Qty"], ["A", 35, "sar", 5]]))
    assert lines[0].currency == "SAR"


def test_mixed_currencies_rejected():
    with pytest.raises(ExcelParseError, match="mixes currencies"):
        parse_price_sheet(_xlsx([["SKU", "Price", "Qty"], ["A", "SAR 35", 1], ["B", "USD 10", 1]]))


def test_no_currency_keeps_schema_default():
    lines = parse_price_sheet(_xlsx([["SKU", "Price", "Qty"], ["A", 35, 1]]))
    assert lines[0].currency == "USD"


def test_numeric_sku_keeps_integer_form():
    lines = parse_price_sheet(_xlsx([["Code", "Price", "Qty"], [1001.0, 10, 1]]))
    assert lines[0].sku == "1001"


def test_real_sku_column_wins_over_generic_id():
    lines = parse_price_sheet(_xlsx([["ID", "SKU", "Price", "Qty"], [1, "TOM-5", 35, 1]]))
    assert lines[0].sku == "TOM-5"


def test_duplicate_sku_reported_with_both_rows():
    with pytest.raises(ExcelParseError, match=r"Row 3 \(SKU A\): SKU appears more than once \(first on row 2\)"):
        parse_price_sheet(_xlsx([["SKU", "Price", "Qty"], ["A", 10, 1], ["A", 11, 1]]))


@pytest.mark.parametrize("bad", [0, -5, "", None, "abc", "1,2", float("nan")])
def test_bad_prices_rejected(bad):
    with pytest.raises(ExcelParseError, match="Row 2"):
        parse_price_sheet(_xlsx([["SKU", "Price", "Qty"], ["A", bad, 1]]))


def test_fractional_quantity_rejected_and_blank_quantity_is_zero():
    with pytest.raises(ExcelParseError, match="not a whole number"):
        parse_price_sheet(_xlsx([["SKU", "Price", "Qty"], ["A", 10, 2.5]]))
    lines = parse_price_sheet(_xlsx([["SKU", "Price", "Qty"], ["A", 10, None]]))
    assert lines[0].quantity == 0


def test_formula_like_prices_rounded_to_cents():
    lines = parse_price_sheet(_xlsx([["SKU", "Price", "Qty"], ["A", 10 / 3, 1]]))
    assert lines[0].unit_price == Decimal("3.33")


def test_missing_quantity_column():
    with pytest.raises(ExcelParseError, match="Missing required column: quantity"):
        parse_price_sheet(_xlsx([["SKU", "Price"], ["A", 10]]))


def test_blank_rows_skipped_and_empty_sheet_rejected():
    lines = parse_price_sheet(_xlsx([["SKU", "Price", "Qty"], [], ["A", 10, 1], [None, None, None]]))
    assert len(lines) == 1
    with pytest.raises(ExcelParseError, match="No product rows"):
        parse_price_sheet(_xlsx([["SKU", "Price", "Qty"]]))


def test_not_an_excel_file():
    with pytest.raises(ExcelParseError, match="Could not open"):
        parse_price_sheet(b"not a spreadsheet")