# Warning exposure and bounded road routing

Safest now requests ORS area avoidance before ordinary alternatives. Active NWS
areas join recorded non-NWS hazards in eligible avoidance requests. Neither a
request nor a provider response proves avoidance: every distinct returned road
geometry is assessed against all active stored polygons in PostGIS.

## Provider limits and configuration

The public [ORS restrictions](https://openrouteservice.org/restrictions/) limit
alternative routes to 100 km and three alternatives, and area-avoidance routes to
150 km, 200 km² total avoidance area and 20 km extent. Orion conservatively checks
the baseline road distance, limits polygon parts, and explains dropped polygons.
It does not label shortest-road or highway-avoidance requests as flood avoidance.
Clipped ORS polygons are only a search aid; full stored polygons assess results.

For broad warnings or endpoints within warnings, optionally configure an existing
self-hosted [GraphHopper custom-model](https://docs.graphhopper.com/openapi)
road-routing service through deployment environment variables:

* `HAZARD_ROUTER_URL`: full private `/route` endpoint; disabled by default.
* `HAZARD_ROUTER_PROFILE`: a graph profile enforcing driving-car access, default
  `car`. The deployment must support flexible routing and per-request custom
  models (`ch.disable: true`) for this profile.
* `ROUTING_TIMEOUT_S`: full assessed-request time budget, default 60, maximum 120.

No hosted GraphHopper account is provisioned or key reused. The existing ORS key
remains server-side and is never sent to this service. Configure a trusted private
service; do not send credentials in its URL. No `.env` edits are required by this PR.
The graph must support `road_access`: only `YES` and `DESIGNATED` access is allowed
by the request model. Private/delivery/destination-only or other restricted access
is blocked; an unsupported encoded value fails the candidate instead of silently
using a more permissive model. This cannot correct missing or outdated OSM tags.

The adapter submits complete active stored polygons, with a 200-polygon/1 MB cap;
it refuses oversized models rather than silently submitting partial hazards.
Non-NWS hazard areas have zero edge priority (blocked). When neither endpoint is
inside a warning, all warning areas also have zero priority. When either is
inside, NWS warning priority multipliers are extreme .02, severe .05, moderate
.15, unknown .10, minor .30. These are conservative search penalties using NWS
severity metadata, **not** probabilities or statements that a road is safe.
The strongest evidence applies once at overlapping polygons via an if/else-if
chain. GraphHopper computes a real connected route; Orion creates no waypoints,
roads, or fallback geometry. Endpoint displacement greater than 5 m is rejected;
this tolerance is numerical matching, not permission to relocate an entrance.
Existing ORS endpoint-snapping confirmation remains intact.

At most four sequential provider calls including the baseline, no retries,
15 seconds for the weighted-engine call, and a 60-second total default budget.
Auth/quota errors stop extra search. Candidates exceeding 1.75× baseline distance
or 2× baseline travel time are discarded. Short ORS alternatives and the optional
weighted-engine candidate are bounded searches, not a proof of global optimality
or a guarantee that every feasible exit has been found. Missing/unsupported engine
configuration is explicitly reported. There is no silent shortest-road substitute.

## Unique exposure and ranking

PostGIS 3.2+ dissolves overlapping polygons and removes higher-severity geometry
from lower-severity geometry within each evidence class. Intersections are
measured on each directed route edge, so repeated traversal counts correctly and
overlapping warnings count once. Distances use the edge's geodesic length allocated
by intersection fraction; percentage uses the same measured route denominator.
This is exact for the returned piecewise route representation, subject to geometry
and floating-point precision, not a survey of the road. Unknown warning severity
is kept explicitly. Warning and non-NWS hazard distances remain separate and must
not be added together when the evidence overlaps.
Boundary-only contact is checked separately: zero measured metres does not imply
zero intersection. Warning boundary contact does not receive a complete-avoidance
claim, and recorded hazard contact excludes the candidate.

Safest excludes every candidate intersecting a recorded non-NWS hazard area. Among
remaining candidates it prioritizes gauge hazard evidence, then zero warning
overlap, then exposure in descending severity (extreme, severe, moderate, unknown,
minor), total exposure, earliest initial exit, fewer re-entries, terrain and time.
This is intentionally conservative, not a time-versus-safety exchange rate.
An inside destination is explained as potentially unavoidable exposure. Exit and
re-entry are measured on the union of warning intervals along the route.

The warning display component is `50 * weighted_metres / (weighted_metres + 10000)`;
it no longer saturates at 2 km. Ranking uses uncompressed measurements, so rounding
of display scores cannot erase differences. Component totals equal the sum of
the displayed components. Non-NWS hazards retain conservative blocking behavior.

The UI reports unique warning miles, percent, severity and complete polygon
avoidance separately from confirmed road safety. A lower-exposure warning route
is labelled “Lower exposure,” never guaranteed safe. Dangerous candidates are
information-only. If no defensible improvement/clear route exists, Orion displays:
“No lower-exposure route found. Travel safety cannot be confirmed.”

## Evidence and remaining limitations

Stored NWS regions include warnings, watches and advisories; they are precautionary
alert footprints, not confirmed flooded roads. Orion currently has no comprehensive
verified road-closure feed. It conservatively blocks all recorded non-NWS hazard
areas, but cannot know about unrecorded closures, stale road-access tags or missing
warnings outside configured ingestion states. No data or ingestion configuration
is changed here. GraphHopper graph coverage, access restrictions and alert coverage
must be validated by the operator before use. Lower warning severity is not proof
of accessibility. An unconfigured engine cannot resolve broad-area ORS limitations.

Automated tests use synthetic geometry/mocked provider responses. They do not prove
a genuine Sulphur–Lafayette detour. The PostGIS regressions include the 35.1-mile
route whose naive overlap sum was 50.1 miles, equal-severity overlaps, repeated
traversal, expired alerts and separate hazard evidence. They write only temporary
tables on a disposable instance when `TEST_POSTGIS_URL` is supplied; existing
database tests retain their separate opt-in `DATABASE_URL` behavior.

For live validation, use a configured car road graph and current warning coverage;
record actual provider-returned route geometry and the PostGIS measurements for an
outside trip, broad-warning crossing, inside origin and inside destination. Compare
the baseline and accepted candidate, ensure endpoints match, confirm no known
hazard intersection, and inspect road access. Do not claim successful avoidance
from API mocks, a drawn line, HTTP 200 alone, or the fact that this adapter exists.
