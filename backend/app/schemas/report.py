from pydantic import BaseModel


class DailyTotals(BaseModel):
    total_orders: int
    confirmed_orders: int
    cancelled_orders: int
    review_orders: int
    total_revenue: float
    avg_order_value: float
    total_units_sold: int


class ProductSold(BaseModel):
    sku: str
    name: str
    qty: int
    revenue: float


class StockRow(BaseModel):
    sku: str
    name: str
    quantity: int


class OrderRow(BaseModel):
    order_number: str
    customer: str
    status: str
    total: float
    time: str


class DailySummary(BaseModel):
    date: str
    currency: str
    totals: DailyTotals
    products_sold: list[ProductSold]
    remaining_stock: list[StockRow]
    orders: list[OrderRow]