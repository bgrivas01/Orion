# Bounded flood-aware candidate search

The old planner created alternatives only from hard avoidance polygons. Since
NWS warning areas are intentionally not hard road closures, this could leave
only the default route. The recommender then always picked a candidate, even
when every candidate was Dangerous. Neither behavior met the Safest intent.

Safest and Balanced now obtain a baseline real route, then:
- Below 100 km of actual baseline driving distance, request up to 3 ORS
  alternative routes (`target_count=3`, `weight_factor=1.4`, `share_factor=0.6`).
- At or above 100 km for driving-car, request shortest-road and highway-avoiding
  routes. These are complete provider-computed network routes using unchanged
  endpoints, not arbitrary waypoint detours. Random lateral waypoints were
  rejected as a strategy because nearest-road snapping cannot establish access.
- If eligible, request an additional hard-hazard avoidance route. The baseline
  must be no longer than the provider's 150 km area-avoidance limit.

At most 4 directions calls are made per user request, sequentially, with no
retry loop. Authentication/access/quota failures stop additional search.
Detours over 1.75 times the baseline distance or twice its duration are excluded.
Account-wide quotas can still reject a request; this is not a global quota
reservation system. Provider limits can reject an otherwise eligible request,
which is reported while retaining the successfully evaluated baseline.

All distinct accepted candidates run through full PostGIS assessment. Duplicate
corridors are identified from 33 distance-spaced samples, with 30 points within
100m considered equivalent. This bounded heuristic can miss a short local
variation; it does not guarantee exhaustive road coverage. Equal durations and
distances alone no longer cause different routes to be discarded.

No Dangerous route is recommended for any preference. If no non-Dangerous
candidate improves on baseline risk, Safest/ Balanced display
"No lower-risk route found". Dangerous results remain visible for information,
with an explicit warning against treating them as safe navigation guidance.
A lower assessed score is not a guarantee of road passability.

Flagged segments expose source/evidence metadata. NWS intersections remain
precautionary warning exposure, not confirmed flooded roads. Route cards,
map polygon popups, elevation labels and risk explanations reflect this.
If the origin is within an NWS polygon, the response explains why leaving the
warning area without any overlap may be impossible. No NWS polygon is converted
into a road closure. Existing confirmed-road-point proposal/confirmation flows
remain in place; route assessment also runs after confirmation.

Validation: backend candidate tests include synthetic Sulphur-Lafayette distance
contracts, short/long/provider boundary cases, duplicates, failures, quota stops,
origin warning membership and all-Dangerous outcomes. Existing Houston, snapping
and risk regressions also run. `node scripts/check-route-labels.cjs` server-renders
a Dangerous NWS-overlap card and rejects a Recommended badge or confirmed-water
wording. No live Sulphur-Lafayette route or live Tiger Cloud test was performed;
provider credentials were unavailable to this test process. SQL integration tests
remain skipped without a test database. Native browser/build checks must run in
normal Windows PowerShell because this isolated session cannot run the compiler.

No .env, schema, ingestion or existing Tiger Cloud data changes.

Provider references:
https://openrouteservice.org/restrictions/
https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/routing-options
