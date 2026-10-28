"""Prospect pipeline: create, import, Google Maps add, win-back, contact, convert.

Every query is tenant-scoped, and branch staff see their own branch's
prospects plus those not yet given a branch. A shop is identified by its normalised phone
number (and, for Google results, its place ID), so the same shop is never
added twice and a shop that is already a customer is never pitched as new.
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.branches import default_branch, get_branch, in_scope
from app.core.permissions import Capability, has_capability
from app.db.models.customer import Customer
from app.db.models.order import Order
from app.db.models.prospect import Prospect, ProspectActivity
from app.db.models.user import User
from app.db.models.zone import Zone
from app.modules.analytics.service import REVENUE_STATUSES, drifting_customers
from app.modules.prospects import places
from app.modules.prospects.phones import InvalidPhone, normalize_phone, phone_digits

STATUSES = ("new", "contacted", "interested", "won", "lost")
OPEN_STATUSES = ("new", "contacted", "interested")
# a win-back the rep marked lost is not re-suggested for this long
_WINBACK_COOLDOWN = timedelta(days=30)
_LIST_LIMIT = 500


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _actor_name(user: User | None) -> str | None:
    if user is None:
        return None
    return user.full_name or user.email


def _phone(raw: str | None) -> str | None:
    try:
        return normalize_phone(raw, settings.PROSPECT_DEFAULT_COUNTRY_CODE)
    except InvalidPhone:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'{raw}' is not a valid phone number")


def _log(db: AsyncSession, p: Prospect, kind: str, body: str | None, actor: User | None) -> None:
    db.add(ProspectActivity(
        tenant_id=p.tenant_id, prospect_id=p.id, kind=kind, body=body,
        actor_id=actor.id if actor else None, actor_name=_actor_name(actor),
    ))


# --- lookups ----------------------------------------------------------------------

def _visible(scope: uuid.UUID | None, branch_id: uuid.UUID | None) -> bool:
    return branch_id is None or in_scope(scope, branch_id)


async def get_prospect(
    db: AsyncSession, tenant_id: uuid.UUID, prospect_id: uuid.UUID, scope: uuid.UUID | None = None
) -> Prospect:
    p = await db.scalar(select(Prospect).where(Prospect.id == prospect_id, Prospect.tenant_id == tenant_id))
    if p is None or not _visible(scope, p.branch_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prospect not found")
    return p


async def _customer_by_phone(db: AsyncSession, tenant_id: uuid.UUID, phone: str | None) -> Customer | None:
    digits = phone_digits(phone)
    if not digits:
        return None
    return await db.scalar(
        select(Customer).where(
            Customer.tenant_id == tenant_id,
            func.regexp_replace(Customer.whatsapp_number, "[^0-9]", "", "g") == digits,
        )
    )


async def _prospect_by_phone(db: AsyncSession, tenant_id: uuid.UUID, phone: str | None,
                             exclude_id: uuid.UUID | None = None) -> Prospect | None:
    if not phone:
        return None
    q = select(Prospect).where(Prospect.tenant_id == tenant_id, Prospect.phone == phone)
    if exclude_id:
        q = q.where(Prospect.id != exclude_id)
    return await db.scalar(q.order_by(Prospect.created_at.desc()))


async def _check_zone(db: AsyncSession, tenant_id: uuid.UUID, zone_id: uuid.UUID | None) -> None:
    if zone_id is None:
        return
    if await db.scalar(select(Zone.id).where(Zone.id == zone_id, Zone.tenant_id == tenant_id)) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown zone")


async def _check_assignee(db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    if user_id is None:
        return
    u = await db.scalar(select(User).where(User.id == user_id, User.tenant_id == tenant_id, User.is_active.is_(True)))
    if u is None or not has_capability(u.role, Capability.MANAGE_PROSPECTS):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That person can't be assigned prospects")


async def _ensure_new_shop(db: AsyncSession, tenant_id: uuid.UUID, phone: str | None,
                           exclude_id: uuid.UUID | None = None) -> None:
    if not phone:
        return
    customer = await _customer_by_phone(db, tenant_id, phone)
    if customer:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{customer.name} is already a customer with this number")
    existing = await _prospect_by_phone(db, tenant_id, phone, exclude_id)
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Already in your prospects as {existing.name}")


# --- output shaping -------------------------------------------------------------

async def _zones_with_customers(db: AsyncSession, tenant_id: uuid.UUID) -> set:
    rows = await db.scalars(
        select(Customer.zone_id).where(Customer.tenant_id == tenant_id, Customer.zone_id.is_not(None)).distinct()
    )
    return set(rows)


def _priority(p: Prospect, served_zones: set) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if p.kind == "winback":
        if p.insight:
            reasons.append(p.insight)
        if not p.phone:
            reasons.append("No WhatsApp number on file")
            return "medium", reasons
        return "high", reasons
    score = 0
    if p.phone:
        score += 2
        reasons.append("Has a phone number for WhatsApp")
    else:
        reasons.append("No phone number yet -- add one to message them")
    if p.zone_id and p.zone_id in served_zones:
        score += 1
        reasons.append("In a zone you already deliver to")
    return ("high" if score >= 3 else "medium" if score == 2 else "low"), reasons


async def _shape(db: AsyncSession, tenant_id: uuid.UUID, prospects: list[Prospect]) -> list[dict]:
    zone_ids = {p.zone_id for p in prospects if p.zone_id}
    user_ids = {p.assigned_to_id for p in prospects if p.assigned_to_id}
    zones = dict((await db.execute(select(Zone.id, Zone.name).where(Zone.id.in_(zone_ids)))).all()) if zone_ids else {}
    users = {}
    if user_ids:
        for u in await db.scalars(select(User).where(User.id.in_(user_ids))):
            users[u.id] = _actor_name(u)
    served = await _zones_with_customers(db, tenant_id)

    out = []
    for p in prospects:
        priority, reasons = _priority(p, served)
        out.append({
            "id": p.id, "branch_id": p.branch_id, "kind": p.kind, "source": p.source, "status": p.status,
            "name": p.name, "contact_name": p.contact_name, "phone": p.phone,
            "phone_digits": phone_digits(p.phone), "address": p.address, "area": p.area,
            "category": p.category, "zone_id": p.zone_id, "zone_name": zones.get(p.zone_id),
            "google_maps_uri": p.google_maps_uri, "insight": p.insight, "notes": p.notes,
            "lost_reason": p.lost_reason, "assigned_to_id": p.assigned_to_id,
            "assigned_to_name": users.get(p.assigned_to_id), "customer_id": p.customer_id,
            "last_contacted_at": p.last_contacted_at, "closed_at": p.closed_at,
            "created_at": p.created_at, "priority": priority, "priority_reasons": reasons,
        })
    return out


async def detail(
    db: AsyncSession, tenant_id: uuid.UUID, prospect_id: uuid.UUID, scope: uuid.UUID | None = None
) -> dict:
    p = await get_prospect(db, tenant_id, prospect_id, scope)
    row = (await _shape(db, tenant_id, [p]))[0]
    acts = await db.scalars(
        select(ProspectActivity)
        .where(ProspectActivity.prospect_id == p.id, ProspectActivity.tenant_id == tenant_id)
        .order_by(ProspectActivity.created_at.desc())
        .limit(100)
    )
    row["activities"] = [
        {"id": a.id, "kind": a.kind, "body": a.body, "actor_name": a.actor_name, "created_at": a.created_at}
        for a in acts
    ]
    return row


# --- list and summary -----------------------------------------------------------

async def list_prospects(
    db: AsyncSession, tenant_id: uuid.UUID, *, kind: str | None = None, status_: str | None = None,
    assigned_to: uuid.UUID | None = None, q: str | None = None, scope: uuid.UUID | None = None,
) -> list[dict]:
    await _close_recovered_winbacks(db, tenant_id)
    query = select(Prospect).where(Prospect.tenant_id == tenant_id)
    if scope is not None:
        query = query.where((Prospect.branch_id == scope) | Prospect.branch_id.is_(None))
    if kind:
        query = query.where(Prospect.kind == kind)
    if status_ == "open":
        query = query.where(Prospect.status.in_(OPEN_STATUSES))
    elif status_:
        query = query.where(Prospect.status == status_)
    if assigned_to:
        query = query.where(Prospect.assigned_to_id == assigned_to)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(
            Prospect.name.ilike(like) | Prospect.phone.ilike(like) | Prospect.area.ilike(like)
            | Prospect.contact_name.ilike(like)
        )
    query = query.order_by(Prospect.updated_at.desc()).limit(_LIST_LIMIT)
    rows = await _shape(db, tenant_id, list(await db.scalars(query)))
    rank = {"high": 0, "medium": 1, "low": 2}
    open_first = {s: i for i, s in enumerate(("interested", "new", "contacted", "won", "lost"))}
    rows.sort(key=lambda r: (open_first[r["status"]], rank[r["priority"]]))
    return rows


async def summary(db: AsyncSession, tenant_id: uuid.UUID, scope: uuid.UUID | None = None) -> dict:
    counts = {s: 0 for s in STATUSES}
    by_kind = {"new": 0, "winback": 0}
    q = (
        select(Prospect.kind, Prospect.status, func.count(Prospect.id))
        .where(Prospect.tenant_id == tenant_id)
        .group_by(Prospect.kind, Prospect.status)
    )
    if scope is not None:
        q = q.where((Prospect.branch_id == scope) | Prospect.branch_id.is_(None))
    rows = await db.execute(q)
    for kind, st, n in rows:
        counts[st] = counts.get(st, 0) + n
        if st in OPEN_STATUSES:
            by_kind[kind] = by_kind.get(kind, 0) + n

    assignees = []
    for u in await db.scalars(
        select(User).where(User.tenant_id == tenant_id, User.is_active.is_(True)).order_by(User.full_name)
    ):
        if scope is not None and u.branch_id not in (None, scope):
            continue
        if has_capability(u.role, Capability.MANAGE_PROSPECTS) and u.role != "demo":
            assignees.append({"id": u.id, "name": _actor_name(u)})

    return {
        "counts": counts,
        "open_new": by_kind["new"],
        "open_winback": by_kind["winback"],
        "google_search_enabled": places.enabled(),
        "assignees": assignees,
    }


# --- create / update ------------------------------------------------------------

async def _prospect_branch(
    db: AsyncSession, tenant_id: uuid.UUID, scope: uuid.UUID | None, requested: uuid.UUID | None,
    zone_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Explicit branch, else the zone's, else the branch the caller is working in (may be none)."""
    branch_id = requested
    if branch_id is None and zone_id is not None:
        branch_id = await db.scalar(select(Zone.branch_id).where(Zone.id == zone_id, Zone.tenant_id == tenant_id))
    if branch_id is None:
        branch_id = scope
    if branch_id is not None:
        await get_branch(db, tenant_id, branch_id)
        if not in_scope(scope, branch_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "That branch is outside your access")
    return branch_id


async def create_prospect(db: AsyncSession, tenant_id: uuid.UUID, actor: User, data: dict,
                          *, source: str = "manual", scope: uuid.UUID | None = None) -> dict:
    phone = _phone(data.get("phone"))
    await _ensure_new_shop(db, tenant_id, phone)
    await _check_zone(db, tenant_id, data.get("zone_id"))
    await _check_assignee(db, tenant_id, data.get("assigned_to_id"))
    branch_id = await _prospect_branch(db, tenant_id, scope, data.get("branch_id"), data.get("zone_id"))
    p = Prospect(
        tenant_id=tenant_id, branch_id=branch_id, kind="new", source=source, status="new",
        name=data["name"].strip(), contact_name=data.get("contact_name"), phone=phone,
        address=data.get("address"), area=data.get("area"), category=data.get("category"),
        zone_id=data.get("zone_id"), notes=data.get("notes"),
        assigned_to_id=data.get("assigned_to_id") or actor.id,
        created_by_id=actor.id,
    )
    db.add(p)
    await db.flush()
    _log(db, p, "created", "Added by hand", actor)
    await db.commit()
    return await detail(db, tenant_id, p.id)


async def update_prospect(db: AsyncSession, tenant_id: uuid.UUID, prospect_id: uuid.UUID,
                          actor: User, data: dict, scope: uuid.UUID | None = None) -> dict:
    p = await get_prospect(db, tenant_id, prospect_id, scope)
    if "branch_id" in data:
        p.branch_id = await _prospect_branch(db, tenant_id, scope, data["branch_id"]) if data["branch_id"] else None

    if "phone" in data:
        phone = _phone(data["phone"])
        if phone != p.phone:
            if p.kind == "new":
                await _ensure_new_shop(db, tenant_id, phone, exclude_id=p.id)
            p.phone = phone
    if "zone_id" in data:
        await _check_zone(db, tenant_id, data["zone_id"])
        p.zone_id = data["zone_id"]
    if "assigned_to_id" in data:
        await _check_assignee(db, tenant_id, data["assigned_to_id"])
        p.assigned_to_id = data["assigned_to_id"]
    for f in ("name", "contact_name", "address", "area", "category", "notes", "lost_reason"):
        if f in data:
            value = data[f]
            if f == "name" and not (value or "").strip():
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Name can't be empty")
            setattr(p, f, value.strip() if isinstance(value, str) else value)

    new_status = data.get("status")
    if new_status and new_status != p.status:
        if new_status == "won":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Use 'Mark as won' to close a prospect as won")
        if p.status == "won":
            raise HTTPException(status.HTTP_409_CONFLICT, "This prospect is already won")
        old = p.status
        p.status = new_status
        p.closed_at = _now() if new_status == "lost" else None
        note = f"Status: {old} → {new_status}"
        if new_status == "lost" and p.lost_reason:
            note += f" ({p.lost_reason})"
        _log(db, p, "status", note, actor)

    await db.commit()
    return await detail(db, tenant_id, p.id)


async def add_note(db: AsyncSession, tenant_id: uuid.UUID, prospect_id: uuid.UUID, actor: User, text: str,
                   scope: uuid.UUID | None = None) -> dict:
    p = await get_prospect(db, tenant_id, prospect_id, scope)
    _log(db, p, "note", text.strip(), actor)
    p.updated_at = _now()
    await db.commit()
    return await detail(db, tenant_id, p.id)


async def mark_contacted(db: AsyncSession, tenant_id: uuid.UUID, prospect_id: uuid.UUID,
                         actor: User, message: str | None, scope: uuid.UUID | None = None) -> dict:
    p = await get_prospect(db, tenant_id, prospect_id, scope)
    if not p.phone:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Add a phone number first")
    p.last_contacted_at = _now()
    if p.status == "new":
        p.status = "contacted"
    if p.assigned_to_id is None:
        p.assigned_to_id = actor.id
    _log(db, p, "contacted", (message or "").strip()[:4000] or "Opened WhatsApp", actor)
    await db.commit()
    return await detail(db, tenant_id, p.id)


async def convert(db: AsyncSession, tenant_id: uuid.UUID, prospect_id: uuid.UUID, actor: User,
                  zone_id: uuid.UUID | None = None, scope: uuid.UUID | None = None) -> dict:
    """Close as won. A new shop becomes a customer (or is linked to the existing one)."""
    p = await get_prospect(db, tenant_id, prospect_id, scope)
    if p.status == "won":
        raise HTTPException(status.HTTP_409_CONFLICT, "This prospect is already won")

    if p.kind == "winback":
        note = "Marked as won back"
    else:
        await _check_zone(db, tenant_id, zone_id)
        customer = await _customer_by_phone(db, tenant_id, p.phone)
        if customer is None:
            zone = zone_id or p.zone_id
            branch_id = await _prospect_branch(db, tenant_id, scope, p.branch_id, zone)
            if branch_id is None:
                branch_id = (await default_branch(db, tenant_id)).id
            zone_branch = await db.scalar(select(Zone.branch_id).where(Zone.id == zone)) if zone else None
            if zone_branch is not None and zone_branch != branch_id:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That zone belongs to another branch")
            customer = Customer(
                tenant_id=tenant_id, branch_id=branch_id, name=p.name, company=p.name, whatsapp_number=p.phone,
                address=p.address, zone_id=zone,
            )
            p.branch_id = branch_id
            db.add(customer)
            await db.flush()
            note = "Added as a customer"
        else:
            note = f"Linked to existing customer {customer.name}"
        p.customer_id = customer.id

    p.status = "won"
    p.closed_at = _now()
    _log(db, p, "won", note, actor)
    await db.commit()
    return await detail(db, tenant_id, p.id)


# --- import -----------------------------------------------------------------------

async def import_rows(db: AsyncSession, tenant_id: uuid.UUID, actor: User,
                      rows: list[dict], problems: list[dict], scope: uuid.UUID | None = None) -> dict:
    customer_digits = {
        d for d in (
            phone_digits(n) for n in await db.scalars(
                select(Customer.whatsapp_number).where(Customer.tenant_id == tenant_id, Customer.whatsapp_number.is_not(None))
            )
        ) if d
    }
    prospect_phones = set(await db.scalars(
        select(Prospect.phone).where(Prospect.tenant_id == tenant_id, Prospect.phone.is_not(None))
    ))
    zone_rows = list(await db.execute(select(Zone.id, Zone.name, Zone.branch_id).where(Zone.tenant_id == tenant_id)))
    zones = {name.strip().lower(): zid for zid, name, _ in zone_rows}
    zone_branch = {zid: bid for zid, _, bid in zone_rows}

    skipped = list(problems)
    created = 0
    seen: set[str] = set()
    for r in rows:
        phone = r["phone"]
        if phone:
            if phone_digits(phone) in customer_digits:
                skipped.append({"row": r["row"], "name": r["name"], "reason": "Already a customer"})
                continue
            if phone in prospect_phones:
                skipped.append({"row": r["row"], "name": r["name"], "reason": "Already in your prospects"})
                continue
            if phone in seen:
                skipped.append({"row": r["row"], "name": r["name"], "reason": "Same number appears earlier in the file"})
                continue
            seen.add(phone)

        zone_id, area = None, r["area"]
        if r["zone"]:
            zone_id = zones.get(r["zone"].strip().lower())
            if zone_id is None and not area:
                area = r["zone"]
        elif area:
            zone_id = zones.get(area.strip().lower())
        branch_id = zone_branch.get(zone_id) if zone_id else scope
        if not in_scope(scope, branch_id):  # a zone of another branch: keep the name only
            zone_id, area, branch_id = None, area or r["zone"], scope

        p = Prospect(
            tenant_id=tenant_id, branch_id=branch_id, kind="new", source="import", status="new", name=r["name"],
            contact_name=r["contact_name"], phone=phone, address=r["address"], area=area,
            category=r["category"], zone_id=zone_id, notes=r["notes"],
            assigned_to_id=actor.id, created_by_id=actor.id,
        )
        db.add(p)
        await db.flush()
        _log(db, p, "created", f"Imported (row {r['row']})", actor)
        created += 1

    await db.commit()
    skipped.sort(key=lambda s: s["row"])
    return {"created": created, "skipped": skipped}


# --- Google Maps ------------------------------------------------------------------

async def search_google(db: AsyncSession, tenant_id: uuid.UUID, query: str, language: str,
                        page_token: str | None) -> dict:
    try:
        page = await places.search_places(query, language=language, page_token=page_token)
    except places.PlacesNotConfigured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Google Maps search isn't set up. Add GOOGLE_MAPS_API_KEY on the server.")
    except places.PlacesError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))

    results = page["results"]
    ids = [r["place_id"] for r in results]
    known_places = set(await db.scalars(
        select(Prospect.google_place_id).where(Prospect.tenant_id == tenant_id, Prospect.google_place_id.in_(ids))
    )) if ids else set()
    phones = [r["phone"] for r in results if r["phone"]]
    known_phones = set(await db.scalars(
        select(Prospect.phone).where(Prospect.tenant_id == tenant_id, Prospect.phone.in_(phones))
    )) if phones else set()
    customer_digits = {
        d for d in (
            phone_digits(n) for n in await db.scalars(
                select(Customer.whatsapp_number).where(Customer.tenant_id == tenant_id, Customer.whatsapp_number.is_not(None))
            )
        ) if d
    }
    for r in results:
        r["already_prospect"] = r["place_id"] in known_places or (r["phone"] in known_phones if r["phone"] else False)
        r["already_customer"] = bool(r["phone"]) and phone_digits(r["phone"]) in customer_digits
    return {"results": results, "next_page_token": page["next_page_token"]}


async def add_from_google(db: AsyncSession, tenant_id: uuid.UUID, actor: User, data: dict,
                          scope: uuid.UUID | None = None) -> dict:
    exists = await db.scalar(select(Prospect.id).where(
        Prospect.tenant_id == tenant_id, Prospect.google_place_id == data["place_id"]
    ))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "This place is already in your prospects")
    phone = _phone(data.get("phone"))
    await _ensure_new_shop(db, tenant_id, phone)
    await _check_zone(db, tenant_id, data.get("zone_id"))
    branch_id = await _prospect_branch(db, tenant_id, scope, None, data.get("zone_id"))
    p = Prospect(
        tenant_id=tenant_id, branch_id=branch_id, kind="new", source="google", status="new", name=data["name"].strip(),
        phone=phone, address=data.get("address"), area=data.get("area"), category=data.get("category"),
        zone_id=data.get("zone_id"), google_place_id=data["place_id"], google_maps_uri=data.get("maps_uri"),
        assigned_to_id=actor.id, created_by_id=actor.id,
    )
    db.add(p)
    await db.flush()
    _log(db, p, "created", "Added from Google Maps", actor)
    await db.commit()
    return await detail(db, tenant_id, p.id)


# --- win-back -----------------------------------------------------------------------

async def _close_recovered_winbacks(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Open win-backs whose customer has ordered again since the prospect was created -> won."""
    rows = list(await db.execute(
        select(Prospect, func.max(Order.created_at))
        .join(Order, (Order.customer_id == Prospect.customer_id) & (Order.created_at > Prospect.created_at))
        .where(
            Prospect.tenant_id == tenant_id, Prospect.kind == "winback",
            Prospect.status.in_(OPEN_STATUSES), Order.status.in_(REVENUE_STATUSES),
        )
        .group_by(Prospect.id)
    ))
    for p, ordered_at in rows:
        p.status = "won"
        p.closed_at = _now()
        _log(db, p, "won", f"Ordered again on {ordered_at:%d %b %Y}", None)
    if rows:
        await db.commit()
    return len(rows)


async def refresh_winbacks(db: AsyncSession, tenant_id: uuid.UUID, actor: User,
                           scope: uuid.UUID | None = None) -> dict:
    closed = await _close_recovered_winbacks(db, tenant_id)
    drifting = await drifting_customers(db, tenant_id, branch_id=scope)
    if not drifting:
        return {"created": 0, "closed": closed}

    ids = [d.customer_id for d in drifting]
    open_for = set(await db.scalars(select(Prospect.customer_id).where(
        Prospect.tenant_id == tenant_id, Prospect.kind == "winback",
        Prospect.customer_id.in_(ids), Prospect.status.in_(OPEN_STATUSES),
    )))
    cooling = set(await db.scalars(select(Prospect.customer_id).where(
        Prospect.tenant_id == tenant_id, Prospect.kind == "winback", Prospect.customer_id.in_(ids),
        Prospect.status == "lost", Prospect.closed_at >= _now() - _WINBACK_COOLDOWN,
    )))
    customers = {c.id: c for c in await db.scalars(select(Customer).where(Customer.id.in_(ids)))}

    created = 0
    for d in drifting:
        if d.customer_id in open_for or d.customer_id in cooling:
            continue
        c = customers[d.customer_id]
        try:
            phone = normalize_phone(c.whatsapp_number, settings.PROSPECT_DEFAULT_COUNTRY_CODE)
        except InvalidPhone:
            phone = None
        gap = f"{d.typical_gap_days:g}"
        p = Prospect(
            tenant_id=tenant_id, branch_id=c.branch_id, kind="winback", source="winback", status="new",
            name=c.name, phone=phone, address=c.address, zone_id=c.zone_id, customer_id=c.id,
            insight=(f"Usually orders every {gap} days; last order {d.days_since_last_order} days ago "
                     f"({d.order_count} orders in total)."),
            created_by_id=actor.id,
        )
        db.add(p)
        await db.flush()
        _log(db, p, "created", "Suggested for win-back: ordering far less often than usual", actor)
        created += 1
    await db.commit()
    return {"created": created, "closed": closed}