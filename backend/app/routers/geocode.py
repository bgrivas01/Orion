"""Geocoding proxy. Keeps the ORS key server-side and the clients simple."""

import logging

from fastapi import APIRouter, HTTPException, Query

from ..config import get_settings
from ..models import Place
from ..services import ors

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["geocoding"])

# Used when ORS has no key configured, so the frontends still have something to
# search against in fixture mode.
_FIXTURE_PLACES = [
    Place(name="Downtown Houston, TX", lat=29.7604, lon=-95.3698, region="Texas"),
    Place(name="George Bush Intercontinental Airport (IAH)", lat=29.9902, lon=-95.3368, region="Texas"),
    Place(name="Houston Heights, TX", lat=29.7905, lon=-95.3988, region="Texas"),
    Place(name="Memorial Park, Houston, TX", lat=29.7644, lon=-95.4382, region="Texas"),
    Place(name="Baytown, TX", lat=29.7355, lon=-94.9774, region="Texas"),
]


@router.get("/geocode", response_model=list[Place])
async def geocode(q: str = Query(..., min_length=2, description="Free-text place search")) -> list[Place]:
    settings = get_settings()

    if settings.use_fixtures or not settings.ors_api_key:
        needle = q.lower()
        matches = [p for p in _FIXTURE_PLACES if needle in p.name.lower()]
        return matches or _FIXTURE_PLACES

    try:
        results = await ors.geocode(q)
    except ors.ORSUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ors.ORSError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return [Place(**r) for r in results]
