import type { FloodZone, Gauge, FloodReport, LatLng } from './orion-api';

// Deliberate, conservative UI policy; not a calibrated flooding probability.
export const HOME_POLICY = { gaugeRadiusM: 10_000, reportRadiusM: 2_000, gaugeAgeMs: 3 * 3600_000,
  reportAgeMs: 24 * 3600_000, fetchAgeMs: 5 * 60_000, healthAgeMs: 10 * 60_000,
  zoneLimit: 2000, gaugeLimit: 1000, reportLimit: 500 };
const severityPoints = { minor: 20, moderate: 40, severe: 60, extreme: 75 };
const demo = (text: string) => /\b(demo|demonstration|example|fixture|test-only)\b/i.test(text);
const timestamp = (s?: string | null) => s ? Date.parse(s) : NaN;
export function distanceM(a: LatLng, b: LatLng) {
  const r = Math.PI / 180, dlat = (b.lat - a.lat) * r, dlon = (b.lon - a.lon) * r;
  const h = Math.sin(dlat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dlon / 2) ** 2;
  return 6371008.8 * 2 * Math.asin(Math.sqrt(Math.min(1, h)));
}
function validPoint(p: LatLng) { return Number.isFinite(p.lat) && Number.isFinite(p.lon) && Math.abs(p.lat) <= 90 && Math.abs(p.lon) <= 180; }
// Ring result: 0 outside, 1 inside, 2 boundary. Boundaries count conservatively.
function inRing(point: LatLng, ring: number[][]) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [ax, ay] = ring[j], [bx, by] = ring[i], x = point.lon, y = point.lat;
    const cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax);
    if (Math.abs(cross) < 1e-10 && x >= Math.min(ax, bx) && x <= Math.max(ax, bx) && y >= Math.min(ay, by) && y <= Math.max(ay, by)) return 2;
    if ((ay > y) !== (by > y) && x < (bx - ax) * (y - ay) / (by - ay) + ax) inside = !inside;
  }
  return inside ? 1 : 0;
}
export function containsPoint(point: LatLng, zone: FloodZone) {
  return zone.geometry.coordinates.some(polygon => {
    const outer = inRing(point, polygon[0]);
    if (outer === 2) return true;
    return outer === 1 && !polygon.slice(1).some(hole => inRing(point, hole) === 1);
  });
}
function validGeometry(zone: FloodZone) {
  return zone.geometry?.type === 'MultiPolygon' && Array.isArray(zone.geometry.coordinates) && zone.geometry.coordinates.length > 0 && zone.geometry.coordinates.every(p => Array.isArray(p) && p.length > 0 && p.every(r =>
    Array.isArray(r) && r.length >= 4 && r.every(c => Array.isArray(c) && c.length >= 2 && validPoint({ lon: c[0], lat: c[1] }))
    && r[0][0] === r.at(-1)![0] && r[0][1] === r.at(-1)![1]
    && r.reduce((max, c) => Math.max(max, c[0]), -Infinity) - r.reduce((min, c) => Math.min(min, c[0]), Infinity) <= 180));
}
export interface HomeInput {
  point: LatLng | null; zones: FloodZone[]; gauges: Gauge[]; reports: FloodReport[];
  available: boolean; refreshedAt: number; now: number;
}
export interface HomeIndicator {
  score: number | null; status: 'Low Concern' | 'Caution' | 'High Concern' | 'Score unavailable';
  reasons: string[]; zones: FloodZone[]; gaugePoints: number; areaPoints: number; reportPoints: number;
}
export function homeFloodIndicator(input: HomeInput): HomeIndicator {
  const { point, zones, gauges, reports, now } = input;
  const unavailable = (reason: string): HomeIndicator => ({ score: null, status: 'Score unavailable', reasons: [reason], zones: [], gaugePoints: 0, areaPoints: 0, reportPoints: 0 });
  if (!point) return unavailable('Choose a location to assess current flood indicators.');
  if (!validPoint(point)) return unavailable('Selected coordinates are invalid.');
  if (!input.available || !Number.isFinite(input.refreshedAt) || now - input.refreshedAt > HOME_POLICY.fetchAgeMs || input.refreshedAt > now + 60_000)
    return unavailable('Live data is unavailable, loading, stale or incomplete. Refresh observations.');
  if (zones.some(z => !z || typeof z.source !== 'string' || typeof z.event !== 'string')
    || gauges.some(g => !g || typeof g.name !== 'string' || !Array.isArray(g.series))
    || reports.some(r => !r)) return unavailable('Observation fields are incomplete.');
  if (zones.length >= HOME_POLICY.zoneLimit || gauges.length >= HOME_POLICY.gaugeLimit)
    return unavailable('The local response reached its limit; coverage may be incomplete.');
  if (zones.some(z => z.source === 'demo' || demo([z.event, z.headline].join(' '))) || gauges.some(g => demo(g.name)))
    return unavailable('Demonstration data cannot establish a live flood-safety indicator.');
  let areaPoints = 0;
  const active: FloodZone[] = [];
  for (const zone of zones) {
    if (!validGeometry(zone)) return unavailable('Warning geometry is incomplete or unsupported.');
    const expires = timestamp(zone.expires), effective = timestamp(zone.effective);
    if ((zone.expires && !Number.isFinite(expires)) || (zone.effective && !Number.isFinite(effective))) return unavailable('Warning timing is invalid.');
    if (expires <= now || effective > now) continue;
    if (!containsPoint(point, zone)) continue;
    if (zone.source === 'nws' && (!Number.isFinite(expires) || !Number.isFinite(effective))) return unavailable('Current NWS warning timing is incomplete.');
    if (!Object.hasOwn(severityPoints, zone.severity) || !['nws', 'noaa_fim'].includes(zone.source)) return unavailable('Affected-area severity or evidence is unknown.');
    active.push(zone);
    // The location is one physical point: take the strongest area indicator once,
    // including repeated/overlapping warnings, rather than adding polygons.
    areaPoints = Math.max(areaPoints, zone.source === 'nws' ? severityPoints[zone.severity as keyof typeof severityPoints] : 70);
  }
  const nearby = gauges.filter(g => validPoint(g) && distanceM(point, g) <= HOME_POLICY.gaugeRadiusM);
  if (gauges.some(g => !validPoint(g))) return unavailable('Gauge coordinates are incomplete.');
  if (!nearby.length) return unavailable('No usable USGS gauge coverage within 10 km. Fewer observations are not lower risk.');
  let gaugePoints = 0;
  for (const gauge of nearby) {
    const reading = [...gauge.series].filter(r => r && Number.isFinite(r.gauge_height_ft) && Number.isFinite(timestamp(r.time)))
      .sort((a, b) => timestamp(b.time) - timestamp(a.time))[0];
    const time = timestamp(reading?.time);
    if (!reading || now - time > HOME_POLICY.gaugeAgeMs || time > now + 60_000 || !Number.isFinite(gauge.flood_stage_ft)
      || !Number.isFinite(gauge.action_stage_ft) || gauge.action_stage_ft! > gauge.flood_stage_ft! || !['normal', 'action', 'flood'].includes(gauge.status))
      return unavailable('A nearby gauge lacks recent readings or known action/flood thresholds.');
    // Use the timestamped hourly reading, not the untimestamped current_ft.
    gaugePoints = Math.max(gaugePoints, reading.gauge_height_ft! >= gauge.flood_stage_ft! || gauge.status === 'flood' ? 60
      : reading.gauge_height_ft! >= gauge.action_stage_ft! || gauge.status === 'action' ? 25 : 0);
  }
  if (reports.length >= HOME_POLICY.reportLimit && reports.some(r => !Number.isFinite(timestamp(r.reported_at)) || now - timestamp(r.reported_at) <= HOME_POLICY.reportAgeMs))
    return unavailable('The report response may omit recent observations. Coverage is incomplete.');
  let reportPoints = 0, localReports = 0;
  for (const report of reports) {
    const time = timestamp(report.reported_at);
    if (!Number.isFinite(time)) return unavailable('A report has no usable observation time; recent local coverage cannot be established.');
    if (now - time > HOME_POLICY.reportAgeMs) continue;
    const p = { lat: report.latitude ?? NaN, lon: report.longitude ?? NaN };
    if (!validPoint(p) || time > now + 60_000) return unavailable('Recent report coordinates or timing are incomplete.');
    if (distanceM(point, p) > HOME_POLICY.reportRadiusM) continue;
    if (demo([report.location_name, report.description].join(' '))) return unavailable('Nearby reports contain demonstration observations.');
    const depth = report.water_depth_inches;
    if (depth == null || !Number.isFinite(depth) || depth < 0) return unavailable('A nearby report lacks usable water-depth evidence.');
    localReports++;
    reportPoints = Math.max(reportPoints, depth >= 12 || report.severity === 'high' ? 60 : depth >= 6 || report.severity === 'medium' ? 30 : depth > 0 ? 15 : 0);
  }
  const score = Math.max(0, 100 - areaPoints - gaugePoints - reportPoints);
  return { score, status: score <= 40 ? 'High Concern' : score < 90 ? 'Caution' : 'Low Concern', zones: active,
    areaPoints, gaugePoints, reportPoints, reasons: [
      `Affected areas: −${areaPoints} points (strongest severity/evidence only; overlaps count once).`,
      `USGS gauges within 10 km: −${gaugePoints} points (strongest stage indicator; ${nearby.length} usable sites).`,
      `Reports within 2 km in the last 24 hours: −${reportPoints} points (strongest observation; ${localReports} reports).`,
    ] };
}
