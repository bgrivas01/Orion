"""Optional self-hosted GraphHopper custom model. No geometry is synthesized."""
import json
import math
import logging
import httpx
from ..config import get_settings
from ..models import LineString, LatLng
from . import ors

log = logging.getLogger(__name__)


async def route(origin, destination, areas, inside_warning=False):
    settings = get_settings()
    if not settings.hazard_router_url:
        raise ors.ORSUnavailable("Hazard-weighted road routing is not configured; large or endpoint-containing warning areas cannot be fully optimized by ORS.")
    if len(areas) > 200:
        raise ors.ORSUnavailable("Hazard model exceeds the 200-polygon budget; no partial hazard model was sent.")
    features = []
    # Fail closed if this encoded value is unsupported. A car graph alone may
    # merely penalize private/destination-only roads instead of excluding them.
    rules = [{"if":"road_access != YES && road_access != DESIGNATED", "multiply_by":"0"}]
    factors = {"extreme":0.02,"severe":0.05,"moderate":0.15,"unknown":0.1,"minor":0.3}
    # A single if/else-if chain applies the strongest evidence once even where
    # polygons overlap. Road hazards always dominate precautionary warnings.
    areas = sorted(areas, key=lambda a: (a["source"] == "nws", factors.get(a["severity"],0.1)))
    for i, area in enumerate(areas):
        name = f"area_{i}"
        features.append({"type":"Feature","id":name,"properties":{},"geometry":json.loads(area["geometry"])})
        factor = factors.get(area["severity"],0.1) if area["source"] == "nws" and inside_warning else 0
        rules.append({"if" if i == 0 else "else_if":f"in_{name}","multiply_by":str(factor)})
    payload = {"points":[[origin.lon,origin.lat],[destination.lon,destination.lat]],
        "profile":settings.hazard_router_profile,"points_encoded":False,"instructions":False,
        "ch.disable":True,"custom_model":{"areas":{"type":"FeatureCollection","features":features},"priority":rules}}
    if len(json.dumps(payload)) > 1_000_000:
        raise ors.ORSUnavailable("Hazard model exceeds the geometry budget; select another trip or use a configured engine with a larger regional model.")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(settings.hazard_router_url,json=payload)
        log.info("Hazard router status=%d polygon_count=%d weighted_warnings=%s", response.status_code, len(areas), inside_warning)
        if response.status_code != 200:
            raise ors.ORSUnavailable(f"Hazard-weighted router unavailable (HTTP {response.status_code}); no avoidance claim can be made.")
        path = response.json()["paths"][0]
        geometry = LineString(**path["points"])
        if len(geometry.coordinates) < 2:
            raise ValueError()
        for coord in geometry.coordinates:
            if len(coord) < 2 or not all(math.isfinite(v) for v in coord):
                raise ValueError()
            LatLng(lon=coord[0],lat=coord[1])
        # The engine must not silently relocate selected endpoints.
        for expected,coord in [(origin,geometry.coordinates[0]),(destination,geometry.coordinates[-1])]:
            if ors.distance_m(expected,LatLng(lon=coord[0],lat=coord[1])) > 5:
                raise ors.ORSError("Hazard router moved an endpoint; select and confirm a public-road point manually.")
        distance, duration = float(path["distance"]),float(path["time"])/1000
        if not all(math.isfinite(v) and v > 0 for v in (distance,duration)):
            raise ValueError()
        return ors.RouteResult(geometry,distance,duration)
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError) as exc:
        raise ors.ORSUnavailable("Hazard-weighted router failed or returned invalid route data.") from exc
