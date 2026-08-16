import uuid

from fastapi import APIRouter, Depends, status

from app.core.deps import CurrentUser, DBSession, require_capability
from app.core.permissions import Capability
from app.modules.zones import service
from app.schemas.zone import (
    DriverZonesUpdate,
    OrderAssign,
    ZoneCreate,
    ZoneOut,
)
from app.schemas.order import OrderOut

router = APIRouter(prefix="/zones", tags=["zones"])

_manage = Depends(require_capability(Capability.MANAGE_USERS))
_dispatch = Depends(require_capability(Capability.DISPATCH_ORDER))


@router.get("", response_model=list[ZoneOut])
async def list_zones(db: DBSession, user: CurrentUser) -> list[ZoneOut]:
    return await service.list_zones(db, user.tenant_id)


@router.post("", response_model=ZoneOut, status_code=status.HTTP_201_CREATED, dependencies=[_manage])
async def create_zone(data: ZoneCreate, db: DBSession, user: CurrentUser) -> ZoneOut:
    return await service.create_zone(db, user.tenant_id, data.name, data.description)


@router.delete("/{zone_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_manage])
async def delete_zone(zone_id: uuid.UUID, db: DBSession, user: CurrentUser) -> None:
    await service.delete_zone(db, user.tenant_id, zone_id)


@router.get("/drivers/{driver_id}/zones", response_model=list[uuid.UUID])
async def get_driver_zones(driver_id: uuid.UUID, db: DBSession, user: CurrentUser) -> list[uuid.UUID]:
    return await service.list_driver_zones(db, user.tenant_id, driver_id)


@router.put("/drivers/{driver_id}/zones", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_manage])
async def set_driver_zones(
    driver_id: uuid.UUID, data: DriverZonesUpdate, db: DBSession, user: CurrentUser
) -> None:
    await service.set_driver_zones(db, user.tenant_id, driver_id, data.zone_ids)


@router.get("/suggest-driver/{zone_id}")
async def suggest_driver(zone_id: uuid.UUID, db: DBSession, user: CurrentUser) -> dict:
    driver = await service.suggest_driver(db, user.tenant_id, zone_id)
    if not driver:
        return {"driver_id": None, "driver_name": None}
    return {"driver_id": str(driver.id), "driver_name": driver.full_name or driver.email}


@router.post("/assign/{order_id}", response_model=OrderOut, dependencies=[_dispatch])
async def assign_order(
    order_id: uuid.UUID, data: OrderAssign, db: DBSession, user: CurrentUser
) -> OrderOut:
    return await service.assign_order(db, user.tenant_id, order_id, data.zone_id, data.driver_id)


@router.get("/my-deliveries/list", response_model=list[OrderOut])
async def my_deliveries(db: DBSession, user: CurrentUser) -> list[OrderOut]:
    """Orders assigned to the current driver (dispatched or delivered)."""
    return await service.list_driver_orders(db, user.tenant_id, user.id)