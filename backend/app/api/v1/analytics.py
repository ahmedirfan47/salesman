"""Owner analytics: margins, cost entry, customer drift, stuck orders.

All figures are SQL aggregates over the tenant's own data (see
app.modules.analytics.service). Gated by VIEW_ANALYTICS -- owner/admin only --
because cost and margin data are commercially sensitive.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import CurrentUser, DBSession, require_capability
from app.core.permissions import Capability
from app.modules.analytics import service
from app.schemas.analytics import (
    DriftingCustomerOut,
    MarginSummaryOut,
    ProductCostBulkIn,
    ProductCostBulkResult,
    ProductCostOut,
    ProductMarginOut,
    StuckOrderOut,
)

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    dependencies=[Depends(require_capability(Capability.VIEW_ANALYTICS))],
)

Days = Query(30, ge=1, le=365, description="Trailing window in days")


@router.get("/summary", response_model=MarginSummaryOut)
async def summary(db: DBSession, user: CurrentUser, days: int = Days) -> MarginSummaryOut:
    return MarginSummaryOut.model_validate(await service.margin_summary(db, user.tenant_id, days=days))


@router.get("/margins", response_model=list[ProductMarginOut])
async def margins(db: DBSession, user: CurrentUser, days: int = Days) -> list[ProductMarginOut]:
    rows = await service.product_margins(db, user.tenant_id, days=days)
    return [ProductMarginOut.model_validate(r) for r in rows]


@router.get("/drifting-customers", response_model=list[DriftingCustomerOut])
async def drifting(
    db: DBSession,
    user: CurrentUser,
    min_orders: int = Query(3, ge=2, le=50),
    multiplier: float = Query(2.0, ge=1.2, le=10.0),
) -> list[DriftingCustomerOut]:
    rows = await service.drifting_customers(db, user.tenant_id, min_orders=min_orders, multiplier=multiplier)
    return [DriftingCustomerOut.model_validate(r) for r in rows]


@router.get("/stuck-orders", response_model=list[StuckOrderOut])
async def stuck(db: DBSession, user: CurrentUser) -> list[StuckOrderOut]:
    rows = await service.stuck_orders(db, user.tenant_id)
    return [StuckOrderOut.model_validate(r) for r in rows]


@router.get("/product-costs", response_model=list[ProductCostOut])
async def product_costs(db: DBSession, user: CurrentUser) -> list[ProductCostOut]:
    rows = await service.product_costs(db, user.tenant_id)
    return [ProductCostOut.model_validate(r) for r in rows]


@router.put(
    "/product-costs",
    response_model=ProductCostBulkResult,
    dependencies=[Depends(require_capability(Capability.MANAGE_PRODUCTS))],
)
async def set_product_costs(
    data: ProductCostBulkIn, db: DBSession, user: CurrentUser
) -> ProductCostBulkResult:
    """Set or clear cost prices. Applies to orders placed from now on; past
    orders keep the cost they were snapshotted with."""
    try:
        n = await service.set_product_costs(
            db, user.tenant_id, [(i.product_id, i.cost_price, i.cost_currency) for i in data.items]
        )
    except service.CostUpdateError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    return ProductCostBulkResult(updated=n)