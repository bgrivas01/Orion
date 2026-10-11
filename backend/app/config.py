"""Settings loaded from the environment / .env. Never hardcode keys."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    road_snap_limit_m: float = Field(150, gt=0, le=350)
    ors_api_key: str = ""
    database_url: str = ""

    ingest_states: str = "TX"
    enable_scheduler: bool = True
    use_fixtures: bool = False

    # --- OpenRouteService service limits (see docs/known constraints) -------- #
    ors_base_url: str = "https://api.heigit.org/openrouteservice"
    geocoding_base_url: str = "https://api.heigit.org/pelias/v1"

    @field_validator("ors_base_url")
    @classmethod
    def migrate_legacy_ors_url(cls, value: str) -> str:
        value = value.rstrip("/")
        if value == "https://api.openrouteservice.org":
            return "https://api.heigit.org/openrouteservice"
        return value

    # Hard caps enforced by the public ORS instance.
    max_avoid_polygon_area_km2: float = 200.0
    max_avoid_polygon_extent_km: float = 20.0
    max_route_km_with_avoidance: float = 150.0
    # ORS drops avoid polygons after the first few, so we send very few parts.
    max_avoid_polygon_parts: int = 3

    # --- Risk engine tuning ------------------------------------------------- #
    # Flood polygons get buffered by this much before being sent to ORS, so the
    # route is pushed clear of the edge rather than hugging it.
    flood_buffer_m: float = 150.0
    # Corridor half-width around the straight origin->destination line, used to
    # decide which flood zones are even relevant to this request.
    corridor_buffer_m: float = 15_000.0
    # Gauges within this distance of a route contribute to its score.
    gauge_influence_m: float = 8_000.0

    @property
    def state_list(self) -> list[str]:
        return [s.strip().upper() for s in self.ingest_states.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
