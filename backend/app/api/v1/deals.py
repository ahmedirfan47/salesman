"""Customer prices, promotions and free goods (see app.modules.deals.service for the pricing rule)."""
import uuid

from fastapi import APIRouter, Depends, Query, status

from app.core.branches import BranchScope, default_branch
from app.core.deps import CurrentUser, DBSession, require_capability
from app.core.permissions import Capability
from app.modules.deals import service
from app.schemas.deals import CustomerPriceIn, CustomerPriceOut, PromotionIn, PromotionOut, QuoteOut

router = APIRouter(prefix="/deals", tags=["deals"])
_manage = Depends(require_capability(Capability.MANAGE_PRICING))
_view = Depends(require_capability(Capability.CREATE_ORDER))


@router.get("/customer-prices", response_model=list[CustomerPriceOut], dependencies=[_view])
async def list_customer_prices(db: DBSession, user: CurrentUser, customer_id: uuid.UUID | None = None):
    return await service.list_customer_prices(db, user.tenant_id, customer_id)


@router.post("/customer-prices", response_model=CustomerPriceOut, dependencies=[_manage])
async def save_customer_price(data: CustomerPriceIn, db: DBSession, user: CurrentUser):
    """Create, or update the row for the same customer, product, branch and minimum quantity."""
    return await service.save_customer_price(db, user.tenant_id, data.model_dump())


@router.put("/customer-prices/{price_id}", response_model=CustomerPriceOut, dependencies=[_manage])
async def update_customer_price(price_id: uuid.UUID, data: CustomerPriceIn, db: DBSession, user: CurrentUser):
    return await service.save_customer_price(db, user.tenant_id, data.model_dump(), price_id)


@router.delete("/customer-prices/{price_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_manage])
async def delete_customer_price(price_id: uuid.UUID, db: DBSession, user: CurrentUser) -> None:
    await service.delete_customer_price(db, user.tenant_id, price_id)


@router.get("/promotions", response_model=list[PromotionOut], dependencies=[_view])
async def list_promotions(db: DBSession, user: CurrentUser):
    return await service.list_promotions(db, user.tenant_id)


@router.post("/promotions", response_model=PromotionOut, dependencies=[_manage])
async def create_promotion(data: PromotionIn, db: DBSession, user: CurrentUser):
    return await service.save_promotion(db, user.tenant_id, data.model_dump())


@router.put("/promotions/{promo_id}", response_model=PromotionOut, dependencies=[_manage])
async def update_promotion(promo_id: uuid.UUID, data: PromotionIn, db: DBSession, user: CurrentUser):
    return await service.save_promotion(db, user.tenant_id, data.model_dump(), promo_id)


@router.delete("/promotions/{promo_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_manage])
async def delete_promotion(promo_id: uuid.UUID, db: DBSession, user: CurrentUser) -> None:
    await service.delete_promotion(db, user.tenant_id, promo_id)


@router.get("/quote", response_model=QuoteOut, dependencies=[_view])
async def quote(db: DBSession, user: CurrentUser, scope: BranchScope, sku: str, quantity: int = Query(1, ge=1),
                customer_id: uuid.UUID | None = None, branch_id: uuid.UUID | None = None):
    """What a customer would pay for a line today: list price, their price, deals and free goods."""
    branch = branch_id or scope or (await default_branch(db, user.tenant_id)).id
    return await service.preview(db, user.tenant_id, branch_id=branch, customer_id=customer_id, sku=sku, quantity=quantity)
