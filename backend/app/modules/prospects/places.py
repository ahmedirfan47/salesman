"""Google Maps search for new shops, via the Places API (New) Text Search.

Search results are shown to the rep and never stored. Only the shop the rep
chooses to add becomes a prospect, keyed by Google's place ID.

The phone-number fields sit in Google's Enterprise billing tier, which is
what makes a result usable for WhatsApp outreach. Each search is one billed
request; "load more" is another.
"""
import httpx

from app.config import settings
from app.modules.prospects.phones import InvalidPhone, normalize_phone

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.internationalPhoneNumber",
    "places.nationalPhoneNumber",
    "places.businessStatus",
    "places.googleMapsUri",
    "places.rating",
    "places.userRatingCount",
    "nextPageToken",
])


class PlacesNotConfigured(Exception):
    pass


class PlacesError(Exception):
    pass


def enabled() -> bool:
    return bool(settings.GOOGLE_MAPS_API_KEY)


async def search_places(
    query: str,
    *,
    language: str = "en",
    page_token: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Returns {"results": [...], "next_page_token": str | None}."""
    if not enabled():
        raise PlacesNotConfigured()

    body: dict = {
        "textQuery": query,
        "pageSize": 20,
        "languageCode": language,
        "regionCode": settings.PROSPECT_REGION_CODE,
    }
    if page_token:
        body["pageToken"] = page_token
    headers = {
        "X-Goog-Api-Key": settings.GOOGLE_MAPS_API_KEY,
        "X-Goog-FieldMask": _FIELD_MASK,
    }

    own_client = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        resp = await client.post(SEARCH_URL, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise PlacesError("Google Maps could not be reached. Try again in a moment.") from exc
    finally:
        if own_client:
            await client.aclose()

    if resp.status_code != 200:
        try:
            message = resp.json().get("error", {}).get("message") or resp.text
        except ValueError:
            message = resp.text
        raise PlacesError(f"Google Maps search failed: {message[:300]}")

    data = resp.json()
    results = []
    for p in data.get("places", []):
        if p.get("businessStatus") == "CLOSED_PERMANENTLY":
            continue
        try:
            phone = normalize_phone(p.get("internationalPhoneNumber"), settings.PROSPECT_DEFAULT_COUNTRY_CODE)
        except InvalidPhone:
            phone = None
        results.append({
            "place_id": p["id"],
            "name": (p.get("displayName") or {}).get("text") or "Unnamed place",
            "address": p.get("formattedAddress"),
            "phone": phone,
            "phone_display": p.get("nationalPhoneNumber") or p.get("internationalPhoneNumber"),
            "maps_uri": p.get("googleMapsUri"),
            "rating": p.get("rating"),
            "rating_count": p.get("userRatingCount"),
            "temporarily_closed": p.get("businessStatus") == "CLOSED_TEMPORARILY",
        })
    return {"results": results, "next_page_token": data.get("nextPageToken")}