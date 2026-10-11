# SafeHaven + Orion

SafeHaven remains the teammate's React 19/TanStack Start app, alongside the existing Next.js `web/` and Expo `mobile/`. Its map, address search and observations now consume Orion's Python API. The existing visual tokens, navigation, checklist and session profile remain.

## Run locally

Start the existing Orion backend on port 8081 using its normal instructions and configuration. SafeHaven defaults to `http://127.0.0.1:8081`; override the public backend origin using `VITE_ORION_API_BASE`. In PowerShell, without editing any `.env` file:

```powershell
cd safehaven
$env:VITE_ORION_API_BASE = 'http://127.0.0.1:8081'
npm install --workspaces=false --package-lock=false
npm run dev -- --port 3004
```

Open `http://localhost:3004`. The explicit port avoids the existing Orion web server's 3001 port. Stop the server before clearing the process environment override if needed. For deployment, set a reachable HTTPS backend origin at build time; a visitor's `127.0.0.1` cannot reach your deployed backend. Existing backend CORS permits this frontend; no backend change is included.

SafeHaven remains independent of the root workspace and lockfile. MapLibre is its only new dependency. No Google Maps key is needed: MapLibre loads the OpenFreeMap style and a separate Vite-generated, same-origin worker asset. The existing Next.js worker fix is untouched. The original Cloudflare-targeted Lovable/Nitro build configuration remains.

## Truly integrated

- Typed client imports the existing generated API models, without changing shared contracts or importing server secrets. Browser requests omit credentials and can be cancelled.
- `/health` checks dependencies once on connection and on explicit refresh. This endpoint exercises ORS and consumes quota, so it is not automatically polled. Raw health diagnostic detail is not displayed.
- `GET /api/flood-zones`, `/api/gauges` and `/api/flood-reports?limit=100` populate the map and observations screen. Warning queries retain the backend's coverage/limit; reports are limited to the latest 100. The list shows the first 20 returned gauges; the map includes all returned gauges. Refresh updates observations. There is no all-clear inference from missing data.
- `GET /api/geocode` provides selectable origin/destination coordinates, including a location chosen in Explore. `POST /api/routes` sends `driving-car` and Safest/Balanced/Fastest to Orion. Only provider-returned geometries are rendered; there is no illustrative route fallback.
- Route cards show backend risk (0 lower, 100 worse), duration, distance, unique warning exposure, severity, hazard exposure, initial warning exit, re-entry and limitations. SafeHaven does not rescore routes or invert scores into a personal safety score. Dangerous routes are information only and never displayed as preferred candidates.
- Road snapping preserves original locations and requires a public-road-access acknowledgement plus Accept before resubmitting proposed points with the existing `accepted_snaps` contract. Cancel does not retry. Orion enforces its conservative configured distance and reassesses the entire accepted route. A road point is not proof of building access or safe travel.
- Failed health/database checks suppress fallback observations and disable routing. Detected `source: demo` warning payloads also disable routing. Failed warning loading disables routing; other observation failures show missing-data warnings. Changing endpoints, preferences or connection availability clears previous routes and cancels stale responses.

## Safety and demonstration limits

NWS shading is a precautionary warning footprint, not confirmed floodwater or a road closure. Other hazard footprints retain source metadata. Gauge levels and dated report points do not establish road passability; flood reports currently do not affect backend route scoring. Provider limits and GraphHopper availability remain governed by Orion's existing routing safeguards; this frontend adds no avoidance capability to the backend.

The backend must run in its existing non-fixture configuration for live operation. Its health response has no explicit fixture-mode field; SafeHaven detects demo warning sources but cannot prove the provenance of every response independently. Do not interpret this app as a complete, real-time coverage guarantee.

Personal safety scores, future flood predictions, shelter availability, verified evacuation destinations, turn-by-turn guidance, automatic voice/push alerts and offline downloads are not integrated. The former fabricated score/forecast/shelter route is removed from operational screens. Profile preferences, saved places/contacts and download controls remain clearly labelled, in-memory demonstrations. The checklist is functional session state. Offline preview disables live routing and hides observations; it downloads no tiles or routes. Always follow official emergency guidance.

## Verification

```sh
cd safehaven
npm run build
npx tsc --noEmit
npm test -- --pool=threads
```

The build/dev plugin generates the ignored `src/routeTree.gen.ts` needed by the existing routing test and TypeScript check. Integration tests exercise HTTP client URLs/bodies/errors, backend payload rendering, exact GeoJSON consumption, preferences, dangerous/no-lower-exposure displays, snapping confirmation/cancellation, geocoding selection, stale responses and fixture/health failure handling. HTTP fixtures exist only in tests; application code has no test route or demo geometry fallback.

Validation for this change: SafeHaven production client/SSR/Cloudflare build and TypeScript passed; 28 frontend tests passed; unchanged backend suite passed 171 tests with 14 database-dependent skips. Automated Edge launch and in-app localhost access were blocked in the isolated Windows session, so real-browser rendering and live ORS/database requests have not yet been verified. The supplied review-time browser checker can run in normal PowerShell using isolated HTTP test responses, without touching Tiger Cloud. Browser fixture success does not establish live provider routing or real flood avoidance. No database, keys, `.env`, backend, mobile, shared types, existing web app or root lockfile changes are included.
