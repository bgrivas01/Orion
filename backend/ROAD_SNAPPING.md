# Confirmed road-point proposals

For driving-car error 2010 only, Orion extracts endpoint indices from the ORS
message without exposing that message. It asks POST
`/openrouteservice/v2/snap/driving-car/json` for those points within
`ROAD_SNAP_LIMIT_M` (default 150 metres, maximum setting 350). Returned points
are validated and distance is independently measured. There is no larger-radius
retry. Unknown endpoint indices, null/unchanged/out-of-range points, invalid
payloads, unsupported snapping, access denial and rate limits give a manual
public-road entrance/address instruction. Error 2009 does not trigger snapping.

The existing /api/routes response can contain no routes and `snap_proposals`.
Each proposal identifies the endpoint, original and proposed coordinates,
distance, confirmation_required=true and access_verified=false. It is not a
route or proof of public/building access. The frontend preserves original
labels and coordinates, displays the proposal, and requires the user to affirm
public access before Accept. Cancel and selection edits discard the proposal.
If access across a highway, barrier, fence or restricted entrance is uncertain,
the user must cancel and select an entrance manually. ORS snapping data cannot
prove access or detect all such obstacles; Orion does not claim otherwise.

Accept submits a fresh ordinary route request with proposed coordinates and
accepted_snaps metadata. The server validates distance and coordinate agreement,
preserves originals in the response, reruns full PostGIS risk assessment, and
refuses confirmed snapped routing when the database is unavailable. No second
snapping loop is attempted. Original/confirmation metadata is response-only;
no database schema or stored flood data changes are made.

A geocoder POI centroid may be farther than 150m from a road. In fact, a default
ORS routing snap radius can be larger than this conservative proposal limit,
so many 2010 failures will correctly produce no proposal. Users must choose an
entrance in that case. Never raise the radius merely to force a route.

Validation:
- Backend tests: `python -m pytest tests -q` (no live database needed).
- TypeScript: `tsc --noEmit` in web after installing workspace dependencies.
- Browser regression: with web running, install/use Playwright and run
  `ORION_TEST_URL=http://127.0.0.1:3000 node web/scripts/check-snapping.mjs`.
  `ORION_PLAYWRIGHT` may point to an existing Playwright package. The script
  mocks frontend API requests and checks Cancel, gated Accept, original
  preservation, submitted metadata and editing invalidation.
- The hosted snap endpoint responded HTTP 401 to an unauthenticated availability
  probe. Authenticated account access and real POI snapping remain unverified:
  no configured API key was available to the test process. A 401 does not prove
  that the account has snapping permission.
- Windows isolation prevented launching the browser regression runner here;
  the test is provided but not reported as passed. Native production build
  validation remains pending outside this isolated Windows session.

API reference: https://giscience.github.io/openrouteservice/api-reference/endpoints/snapping/
