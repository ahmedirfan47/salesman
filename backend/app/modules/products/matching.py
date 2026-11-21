"""Product matching: turn the words a customer used into a product, with a score.

Customers rarely type a SKU. They write "2 كرتون حليب المراعي صغير", "the red
one", "pepsi diet can" or make the same typo every week. This module:

- normalises Arabic and English text so spelling variants compare equal
  (hamza forms, taa marbuta, alef maqsura, diacritics, tatweel, Arabic digits);
- looks up aliases first (this customer's own words, then the business's),
  then scores product names and SKUs;
- returns a 0-1 score for every match, which the orders flow uses to decide
  whether the AI's choice is safe to confirm or must go to the team;
- learns new aliases when a customer confirms an order or staff correct one.

No external services and no database extensions: scoring is plain Python over
a short list of candidates fetched with ILIKE, so it runs the same everywhere.
"""
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.product import Product
from app.db.models.product_alias import ProductAlias

# A word at or above this similarity counts as the same word ("pepsy" ~ "pepsi").
_WORD_MATCH = 0.8
# Small catalogs are scored in full so typos are still found.
_FULL_SCAN_LIMIT = 1500
_CANDIDATE_LIMIT = 300

_DIACRITICS = re.compile(r"[ً-ٰٟـ]")
_ARABIC_MAP = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي", "ئ": "ي", "ؤ": "و", "ة": "ه",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
})
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)
# "1l", "500ml", "2kg" and "1 l" all become "1l" / "500ml" / "2kg"
_NUM_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s+(ml|l|g|kg|gm|ltr|pcs|pc)\b")


def normalise(text: str | None) -> str:
    """Lower-case, strip diacritics and punctuation, unify Arabic letter forms."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text).lower()
    s = _DIACRITICS.sub("", s)
    s = s.translate(_ARABIC_MAP)
    s = s.replace("_", " ")
    s = _NON_WORD.sub(" ", s)
    s = _NUM_UNIT.sub(r"\1\2", s)
    return " ".join(s.split())


def _tokens(norm: str) -> list[str]:
    return [t for t in norm.split() if t]


def _has_digit(token: str) -> bool:
    return any(ch.isdigit() for ch in token)


def similarity(query_norm: str, candidate_norm: str) -> float:
    """0-1 score of how well the customer's words name a candidate."""
    if not query_norm or not candidate_norm:
        return 0.0
    if query_norm == candidate_norm:
        return 1.0
    q, c = _tokens(query_norm), _tokens(candidate_norm)
    ratio = SequenceMatcher(None, query_norm, candidate_norm).ratio()

    matched = 0
    for qt in q:
        if qt in c:
            matched += 1
            continue
        if not _has_digit(qt) and any(SequenceMatcher(None, qt, ct).ratio() >= _WORD_MATCH for ct in c):
            matched += 1
    coverage = matched / len(q)
    score = max(ratio, 0.75 * coverage + 0.25 * ratio)

    # every word of the customer's phrase appears in the name, in order: strong
    if coverage == 1.0 and f" {query_norm} " in f" {candidate_norm} ":
        score = max(score, 0.9)

    # sizes must agree: "1l" must not quietly become "2l"
    q_nums = {t for t in q if _has_digit(t)}
    c_nums = {t for t in c if _has_digit(t)}
    if q_nums and c_nums and not (q_nums & c_nums):
        score *= 0.5
    return round(min(score, 1.0), 3)


async def _aliases_for(
    db: AsyncSession, tenant_id: uuid.UUID, product_ids: list[uuid.UUID], customer_id: uuid.UUID | None,
) -> dict[uuid.UUID, list[ProductAlias]]:
    if not product_ids:
        return {}
    q = select(ProductAlias).where(
        ProductAlias.tenant_id == tenant_id, ProductAlias.product_id.in_(product_ids),
    )
    if customer_id is None:
        q = q.where(ProductAlias.customer_id.is_(None))
    else:
        q = q.where(or_(ProductAlias.customer_id.is_(None), ProductAlias.customer_id == customer_id))
    out: dict[uuid.UUID, list[ProductAlias]] = {}
    for a in await db.scalars(q):
        out.setdefault(a.product_id, []).append(a)
    return out


def _score_product(query_norm: str, product: Product, aliases: list[ProductAlias],
                   customer_id: uuid.UUID | None) -> tuple[float, str]:
    best, via = 0.0, "name"
    if query_norm == normalise(product.sku):
        return 1.0, "sku"
    for name in (product.name_en, product.name_ar):
        s = similarity(query_norm, normalise(name))
        if s > best:
            best, via = s, "name"
    for a in aliases:
        exact = a.alias_norm == query_norm
        if exact:
            s = 1.0 if (customer_id is not None and a.customer_id == customer_id) else 0.97
        else:
            # a fuzzy alias match is worth a little less than the same match on the real name
            s = similarity(query_norm, a.alias_norm) * 0.95
        if s > best:
            best, via = s, "customer_alias" if a.customer_id is not None else "alias"
    return round(best, 3), via


async def find_matches(
    db: AsyncSession, tenant_id: uuid.UUID, query: str, *,
    customer_id: uuid.UUID | None = None, limit: int = 8, min_score: float = 0.35,
) -> list[dict]:
    """Best products for the customer's words, best first: [{product, score, via}]."""
    query_norm = normalise(query)
    if not query_norm:
        return []
    active = (Product.tenant_id == tenant_id, Product.is_active.is_(True))

    catalog_size = await db.scalar(select(func.count(Product.id)).where(*active)) or 0
    if catalog_size <= _FULL_SCAN_LIMIT:
        products = list(await db.scalars(select(Product).where(*active)))
    else:
        conds = []
        for t in _tokens(query_norm)[:8]:
            if len(t) < 2:
                continue
            like = f"%{t}%"
            conds += [Product.name_en.ilike(like), Product.name_ar.ilike(like), Product.sku.ilike(like)]
        alias_ids = select(ProductAlias.product_id).where(
            ProductAlias.tenant_id == tenant_id, ProductAlias.alias_norm.ilike(f"%{query_norm[:60]}%"),
        )
        conds.append(Product.id.in_(alias_ids))
        products = list(await db.scalars(select(Product).where(*active, or_(*conds)).limit(_CANDIDATE_LIMIT)))

    aliases = await _aliases_for(db, tenant_id, [p.id for p in products], customer_id)
    scored = []
    for p in products:
        score, via = _score_product(query_norm, p, aliases.get(p.id, []), customer_id)
        if score >= min_score:
            scored.append({"product": p, "score": score, "via": via})
    scored.sort(key=lambda m: (-m["score"], m["product"].name_en))
    top = scored[:limit]

    # count alias use, so staff can see which aliases earn their keep
    if top and top[0]["via"] in ("alias", "customer_alias"):
        hit = next((a for a in aliases.get(top[0]["product"].id, []) if a.alias_norm == query_norm), None)
        if hit is not None:
            hit.hits += 1
            hit.last_used_at = datetime.now(timezone.utc)
            await db.flush()
    return top


async def match_score(
    db: AsyncSession, tenant_id: uuid.UUID, wording: str, product: Product, customer_id: uuid.UUID | None,
) -> float:
    """How well `wording` names this one product (used to check the AI's choice)."""
    query_norm = normalise(wording)
    if not query_norm:
        return 0.0
    aliases = await _aliases_for(db, tenant_id, [product.id], customer_id)
    score, _ = _score_product(query_norm, product, aliases.get(product.id, []), customer_id)
    return score


_TRUST = {"manual": 3, "correction": 2, "learned": 1}


async def learn_alias(
    db: AsyncSession, tenant_id: uuid.UUID, product: Product, wording: str, *,
    customer_id: uuid.UUID | None, source: str, actor_id: uuid.UUID | None = None,
) -> ProductAlias | None:
    """Remember that `wording` means `product`. Returns the alias, or None when
    there is nothing worth learning (the words are the product's own name or SKU,
    a bare number, or too short/long). A learned alias never replaces one that
    staff typed or corrected; a correction replaces a learned one."""
    alias = (wording or "").strip()
    norm = normalise(alias)
    if len(norm) < 2 or len(alias) > 200 or norm.replace(" ", "").isdigit():
        return None
    if norm in (normalise(product.name_en), normalise(product.name_ar), normalise(product.sku)):
        return None

    q = select(ProductAlias).where(ProductAlias.tenant_id == tenant_id, ProductAlias.alias_norm == norm)
    q = q.where(ProductAlias.customer_id.is_(None) if customer_id is None else ProductAlias.customer_id == customer_id)
    existing = await db.scalar(q)
    now = datetime.now(timezone.utc)
    if existing is not None:
        if existing.product_id != product.id:
            if _TRUST.get(source, 0) < _TRUST.get(existing.source, 0):
                return existing
            existing.product_id = product.id
            existing.source = source
        existing.hits += 1
        existing.last_used_at = now
        await db.flush()
        return existing
    created = ProductAlias(
        tenant_id=tenant_id, product_id=product.id, customer_id=customer_id, alias=alias, alias_norm=norm,
        source=source, hits=1, last_used_at=now, created_by=actor_id,
    )
    db.add(created)
    await db.flush()
    return created


# --- staff management of aliases -------------------------------------------------------

async def list_aliases(
    db: AsyncSession, tenant_id: uuid.UUID, *, product_id: uuid.UUID | None = None, limit: int = 500,
) -> list[dict]:
    from app.db.models.customer import Customer  # local: keeps this module light to import

    q = (
        select(ProductAlias, Product.sku, Product.name_en, Customer.name)
        .join(Product, Product.id == ProductAlias.product_id)
        .outerjoin(Customer, Customer.id == ProductAlias.customer_id)
        .where(ProductAlias.tenant_id == tenant_id)
    )
    if product_id is not None:
        q = q.where(ProductAlias.product_id == product_id)
    rows = (await db.execute(q.order_by(ProductAlias.hits.desc(), ProductAlias.alias).limit(limit))).all()
    return [
        {
            "id": a.id, "product_id": a.product_id, "sku": sku, "product_name": name, "alias": a.alias,
            "customer_id": a.customer_id, "customer_name": cname, "source": a.source, "hits": a.hits,
            "last_used_at": a.last_used_at, "created_at": a.created_at,
        }
        for a, sku, name, cname in rows
    ]


async def add_alias(
    db: AsyncSession, tenant_id: uuid.UUID, product_id: uuid.UUID, alias: str, *,
    customer_id: uuid.UUID | None = None, actor_id: uuid.UUID | None = None,
) -> ProductAlias:
    from fastapi import HTTPException, status

    from app.db.models.customer import Customer

    product = await db.scalar(select(Product).where(Product.id == product_id, Product.tenant_id == tenant_id))
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    if customer_id is not None and await db.scalar(
        select(Customer.id).where(Customer.id == customer_id, Customer.tenant_id == tenant_id)
    ) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    created = await learn_alias(db, tenant_id, product, alias, customer_id=customer_id, source="manual",
                                actor_id=actor_id)
    if created is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "That alias is the product's own name or SKU, a bare number, or too short",
        )
    await db.commit()
    await db.refresh(created)
    return created


async def delete_alias(db: AsyncSession, tenant_id: uuid.UUID, alias_id: uuid.UUID) -> None:
    from fastapi import HTTPException, status

    row = await db.scalar(select(ProductAlias).where(ProductAlias.id == alias_id, ProductAlias.tenant_id == tenant_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alias not found")
    await db.delete(row)
    await db.commit()
