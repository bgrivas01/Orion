# Orion — flood-aware safest-route routing

Normal navigation apps optimise for time and have no idea which roads are
underwater. Orion answers a different question: **given live flood conditions
and terrain, what is the safest way to get there?**

- **Backend** — FastAPI, fusing live NWS flood warnings, USGS river gauges and
  terrain elevation with OpenRouteService routing.
- **Web** — Next.js + MapLibre GL.
- **Mobile** — Expo (React Native) + react-native-maps, using the phone's GPS
  and raising a notification when flooding appears near you or on your route.
- **Database** — TigerData (Tiger Cloud): Postgres + TimescaleDB + PostGIS.

## The core design idea

> **OpenRouteService proposes. PostGIS disposes.**

ORS's `avoid_polygons` is unreliable — polygons past the first are often ignored
and avoidance silently fails a meaningful share of the time. So Orion never
trusts it:

1. **Propose** — 2–3 separate ORS calls produce candidate routes
   (unconstrained, flood-avoiding, and high-severity-only).
2. **Dispose** — every returned geometry is re-checked against live flood
   polygons in PostGIS (`ST_Intersection`). We compute the score, we rank, we
   label.

`RouteCandidate.avoidance_verified` is the authoritative field, and it is set
only after our own PostGIS check passes. **Never** trust
`avoidance_requested`.

## Risk score (0 = safest, 100 = worst)

| Component | Weight | What it measures |
|---|---:|---|
| Flood exposure | 50 | Route length inside active flood polygons, weighted by alert severity. Any contact at all forces the **Dangerous** band. |
| Low-lying terrain | 25 | Depth and extent of **basins** along the route — places with higher ground on *both* sides, where water pools. A steady hill climb scores zero. |
| Gauge proximity | 20 | Nearby river gauges at or above flood stage, distance-weighted. |
| Approach margin | 5 | How closely the route skirts a flood-zone edge. |

## Quick start

### 1. Backend

```bash
cd backend
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
cp .env.example .env          # then fill in ORS_API_KEY and DATABASE_URL
.venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000/docs>. Check <http://localhost:8000/health> first —
it reports whether the database, PostGIS, TimescaleDB and ORS are all reachable.

**No keys yet?** Set `USE_FIXTURES=true` and the API serves a realistic Houston
flood scenario in the exact response shape. The frontends work fully against it.

Bind to `0.0.0.0` (not just localhost) so the Expo app on a phone can reach it.

### 2. Web

```bash
npm install                   # from the repo root — this is an npm workspace
npm run web                   # http://localhost:3000
```

Set `NEXT_PUBLIC_API_BASE` in `web/.env.local` if the backend is not on
`localhost:8000`.

### 3. Mobile

```bash
cd mobile && npx expo start   # scan the QR code with Expo Go
```

The API base is inferred from the host Expo serves the bundle from, so a phone
on the same Wi-Fi reaches your laptop with no config. Override it with
`extra.apiBase` in `app.json` if the backend is deployed elsewhere.

### 4. Shared types

`packages/shared` holds the generated API types plus the risk labels, colours
and formatters both clients use, so web and mobile cannot drift.

```bash
npm run types                 # regenerate from the running backend's OpenAPI schema
```

Regenerate this whenever `backend/app/models.py` changes.

## Credentials you need

| What | Where | Notes |
|---|---|---|
| `ORS_API_KEY` | <https://openrouteservice.org/dev/#/signup> | Free. 2,000 directions/day, 40/min. |
| `DATABASE_URL` | Tiger Cloud console → service → Connection info | Free tier is enough. Needs `postgis` + `timescaledb`. |

Everything else — NWS flood alerts, USGS gauges, NOAA gauge thresholds, the
basemap tiles — is free and needs no key.

## Demo insurance

If nothing in the US is flooding when you present:

```bash
cd backend
.venv/bin/python scripts/seed_demo.py                    # Houston scenario
.venv/bin/python scripts/seed_demo.py --at 29.65,-95.28  # put it on your phone's location
.venv/bin/python scripts/seed_demo.py --clear            # clean up afterwards
```

This writes real rows into TigerData, so the actual code paths — PostGIS
intersection, scoring, ranking — all run. **Rehearse the full demo on real
devices at least twice.**

## Tests

```bash
cd backend && .venv/bin/python -m pytest -q          # risk engine (no DB needed)
DATABASE_URL='postgres://...' .venv/bin/python -m pytest tests/test_postgis.py -v
npm run check:charts -w web                          # chart SVGs contain no NaN
```

`tests/test_postgis.py` contains the project's central assertion: a route
through a flood polygon must be flagged, a route around it must come back clean,
and the clear one must rank better. It rolls back everything it writes.

## Data sources

### Community flood reports (bloodproject integration)

`GET /api/flood-reports?limit=100` reads the existing `public.flood_reports`
table using the backend's `DATABASE_URL`. The web app shows the latest 100
reports in a list and plots reports with coordinates as square map markers.
It refreshes every minute and offers a manual refresh. Reports include the
location, reported water depth in inches, original severity, description and
timestamp. They are observations, and do not currently change route scores or
verified flood-zone avoidance. Check the timestamp before relying on a report.

Set `DATABASE_URL` in `backend/.env` to the same Tiger Cloud connection used by
`bloodproject/app.py`; keep it out of Git. No `psycopg` dependency is needed:
Orion reuses its asynchronous connection pool. Fresh databases receive a
compatible table; existing rows are preserved. Fixture mode returns no reports.
An unavailable database produces an explicit unavailable state in the web app.

The Python scripts for MNIST and superconductor analysis are unrelated to these
reports and are not required by Orion.

| Source | Use | Key? |
|---|---|---|
| OpenRouteService | routing (+3D elevation in the same call), geocoding | yes, free |
| api.weather.gov | active flood alert polygons | no |
| USGS Water Services | live river gauge heights | no |
| NOAA NWPS gauge report | flood/action stage thresholds | no |
| OpenFreeMap | basemap vector tiles | no |

## Known constraints

1. **ORS avoidance is unreliable** — mitigated by the propose/dispose design.
   Do not let a demo depend on ORS honouring a polygon.
2. **ORS caps**: 200 km² per avoid polygon, 20 km extent, 150 km route when
   avoidance is used. `avoid_set.py` clips, unions and simplifies to stay
   inside them, and warns when a zone is too big to route around.
3. **MapLibre is web-only here.** `@maplibre/maplibre-react-native` needs a
   custom dev build and will not run in Expo Go, so mobile uses
   `react-native-maps`. Don't burn hours on a dev build.
4. **Remote push does not work in Expo Go** (removed in SDK 53+). Local
   notifications do, so alerts come from a 60-second foreground poll.
   `POST /api/alerts/subscribe` already stores device positions for when
   someone makes a dev build.
5. **Not every NWS alert carries geometry** — zone-coded alerts are resolved
   via `/zones/...` and cached in `nws_zones`.
6. **US-only** by design: the free live flood feeds are US government services.
   `flood_zones.source` leaves room for another region later.

## Layout

```
backend/
  app/
    models.py          the wire contract — both clients generate types from this
    services/
      risk.py          scoring + PostGIS verification  ← the heart of it
      avoid_set.py     builds ORS-legal avoid polygons
      ors.py           OpenRouteService client
    ingest/            NWS alerts, USGS gauges, APScheduler jobs
    routers/           health, routes, flood-zones, gauges, geocode, alerts
  sql/                 schema (001), continuous aggregate (002)
  scripts/seed_demo.py demo insurance
web/                   Next.js + MapLibre
mobile/                Expo + react-native-maps
packages/shared/       generated types + shared risk labels/formatters
```
