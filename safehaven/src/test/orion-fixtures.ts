import type { RouteCandidate, RouteResponse, SnapProposal } from '@/lib/orion-api';
// Test-only HTTP payloads: never imported by application code.
export const route: RouteCandidate = {
  id: 'provider-route-7', label: 'safest', geometry: { type: 'LineString', coordinates: [[-95.4, 29.7], [-95.39, 29.72], [-95.37, 29.74]] },
  distance_m: 6000, duration_s: 720, risk_score: 24, risk_band: 'caution', risk_breakdown: { flood_exposure: 10, gauge_proximity: 4, low_lying: 10, approach_margin: 0, total: 24 },
  warning_exposure_m: 1609.344, warning_exposure_percent: 26.8, warning_severity_m: { severe: 1609.344 },
  hazard_exposure_m: 0, initial_warning_exit_m: 100, warning_reentries: 0, warning_avoidance_achieved: false,
  flagged_segments: [], elevation_profile: [], avoidance_requested: true, avoidance_verified: false,
  warnings: ['Origin lies inside an NWS warning; complete avoidance may be impossible.'],
};
export const response: RouteResponse = { request_id: 'request-7', generated_at: '2026-10-11T12:00:00Z', routes: [route],
  recommended_id: route.id, flood_zones_considered: 2, warnings: ['Large areas exceed provider avoidance limits.'], no_lower_risk_route_found: false };
export const snap: SnapProposal = { endpoint: 'origin', original: { lat: 29.7, lon: -95.4 }, proposed: { lat: 29.7005, lon: -95.4 },
  distance_m: 56, confirmation_required: true, access_verified: false };
