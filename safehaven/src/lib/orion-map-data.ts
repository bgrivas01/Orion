import type { FloodZone, Gauge, FloodReport, LatLng, RouteCandidate } from './orion-api';
const colors = { extreme: '#d03b3b', severe: '#d03b3b', moderate: '#ec835a', minor: '#fab219', unknown: '#898781' };
const bands = { safe: '#19BCA0', caution: '#fab219', dangerous: '#d03b3b' };
const collection = (features: object[]) => ({ type: 'FeatureCollection' as const, features });
export interface OrionMapData {
  zones: FloodZone[]; gauges: Gauge[]; reports: FloodReport[]; routes: RouteCandidate[];
  selectedId: string | null; origin: LatLng | null; destination: LatLng | null;
}
export function buildOrionMapData(data: OrionMapData) {
  return {
    zones: collection(data.zones.map(zone => ({ type: 'Feature', geometry: zone.geometry,
      properties: { id: zone.id, source: zone.source, event: zone.event, severity: zone.severity, color: colors[zone.severity] } }))),
    routes: collection(data.routes.map(route => ({ type: 'Feature', geometry: route.geometry,
      properties: { id: route.id, selected: route.id === data.selectedId, color: bands[route.risk_band] } }))),
    flagged: collection(data.routes.flatMap(route => (route.flagged_segments ?? []).map(segment => ({
      type: 'Feature', geometry: segment.geometry, properties: { selected: route.id === data.selectedId,
        evidence: segment.evidence, source: segment.source, event: segment.event, severity: segment.severity },
    })))),
    gauges: collection(data.gauges.map(gauge => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [gauge.lon, gauge.lat] },
      properties: { name: gauge.name, status: gauge.status, current: gauge.current_ft, color: gauge.status === 'flood' ? '#d03b3b' : gauge.status === 'action' ? '#fab219' : '#19BCA0' } }))),
    reports: collection(data.reports.filter(report => report.latitude != null && report.longitude != null).map(report => ({
      type: 'Feature', geometry: { type: 'Point', coordinates: [report.longitude!, report.latitude!] },
      properties: { name: report.location_name ?? 'Flood observation', depth: report.water_depth_inches, reported: report.reported_at ?? 'Unknown time' },
    }))),
    endpoints: collection(([['origin', data.origin], ['destination', data.destination]] as const).flatMap(([role, point]) => point ? [{
      type: 'Feature', geometry: { type: 'Point', coordinates: [point.lon, point.lat] }, properties: { role },
    }] : [])),
  };
}
