# HeiGIT API migration

Directions use `https://api.heigit.org/openrouteservice/v2/directions/{profile}/geojson`.
Autocomplete uses `https://api.heigit.org/pelias/v1/autocomplete`.
The existing server-side `ORS_API_KEY` is sent in the Authorization header for
both services; it is never added to a browser request or query string.

`ORS_BASE_URL` remains the routing service root (without `/v2`). Its default
is `https://api.heigit.org/openrouteservice`. An existing value equal to the
old public origin is migrated in memory, without rewriting `.env`.
`GEOCODING_BASE_URL` defaults to `https://api.heigit.org/pelias/v1`.
Custom routing roots remain supported.

Failure messages distinguish upstream 401 (invalid/missing credentials), 403
(access denied: check permissions and key validity), and 429 (rate/quota limit).
A 403 alone cannot prove whether the key is valid, so the message deliberately
mentions both possibilities. Raw upstream response bodies and network exception
text are not returned to clients. Provider authentication/access failures map
to API 502; temporary outages/rate limits map to 503. The original upstream
status and service are included in the safe detail message.

The public ORS API does not offer `/v2/health`. Orion's `/health` now makes one
small directions request and one autocomplete request using the configured key.
Both must return valid successful results for `ors: true`. This costs normal
API quota per health request; avoid frequent polling. Database health queries
remain unchanged. No tables, ingestion jobs, or stored flood data are changed.

Verification: run `python -m pytest tests/test_ors.py -q` from `backend`.
These tests mock upstream HTTP and database availability. They verify URLs,
Authorization headers, response mappings, geometry/elevation preservation,
error sanitization, and health rejection on authentication/access/rate errors.
For live verification after restarting the backend, request
`GET /api/geocode?q=Houston` and `POST /api/routes` with a JSON body such as
`{"origin":{"lat":29.7604,"lon":-95.3698},"destination":{"lat":29.7634,"lon":-95.3698}}`.
A successful geocode returns places with name/lat/lon; a successful route returns
route geometry. A remaining 401/403 requires checking the existing key's status
and service access in the HeiGIT dashboard; migrating a URL cannot grant access.

References:
- https://ask.openrouteservice.org/t/deprecating-api-openrouteservice-org-in-favour-of-api-heigit-org/7912
- https://giscience.github.io/openrouteservice/api-reference/endpoints/health/
