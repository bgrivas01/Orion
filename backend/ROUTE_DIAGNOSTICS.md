# Route failure diagnostics

The reported Sulphur High School -> Chennault Airport error contains two
independent events: an oversized avoid polygon was omitted locally, then
Fastest (which already has no avoid polygon) returned HTTP 404. No additional
no-avoid fallback is appropriate. The earlier client discarded ORS's numeric
error code, so neither the pasted error nor local logs establish the actual
reason for this particular 404. No live route reproduction is claimed.

The client now distinguishes documented ORS codes:
- 2010: point not found on the routable network; select a public-road entrance
  instead of an airport/campus centre. Orion returns HTTP 422.
- 2009: no connected route; check entrances/access restrictions or choose
  different locations. Orion returns HTTP 422.
- 2004: provider request limit; the existing Fastest request is independent.
- Unclassified 404: remains an upstream/configuration error (502), not an
  assumption that the endpoint or destination is wrong.

Reproduce with the exact selected coordinates after restarting the backend.
The INFO diagnostic `ORS directions status=... code=... profile=...
avoidance=False point_count=2` identifies the failure category of Fastest.
Logs contain no coordinates, request URL, response body, or Authorization key.
An unclassified 404 requires checking the configured endpoint; don't blindly
increase snapping radii, substitute points, retry the same route, or fabricate
geometry. A geocoder result is not a guarantee of road access.

NWS polygons represent warning areas, not observed flooded road segments.
They are retained in exposure scoring, flagged segments and explicit warnings,
but excluded from hard avoidance. NWS overlap alone no longer invokes the
categorical observed-hazard dangerous rule; the conservative numerical score
can still indicate high risk. The legacy avoidance_verified field describes
polygon overlap only and must not be read as proof that a road is passable.
No schema or existing data is changed.

Other hazard avoidance polygons are capped by cumulative area and conservative
combined extent, not just by individual part size. Oversized sets are omitted
with warnings; returned routes remain independently assessed. Missing credentials
outside explicit fixture mode return 503 instead of a fabricated Houston route.

Tests cover coded/generic 404s, safe logs, no duplicate Fastest call, missing
credentials, aggregate geometry limits, NWS semantics and Houston success.
Run `python -m pytest tests -q` from backend. Local result: 99 passed, 10
PostGIS tests skipped. No Tiger Cloud writes or live credential access occurred.

Provider definitions: https://giscience.github.io/openrouteservice/api-reference/error-codes
