import { describe, expect, it } from 'vitest';
import { HOME_POLICY, containsPoint, homeFloodIndicator, type HomeInput } from '@/lib/home-flood-indicator';
import { homeBounds } from '@/lib/home-flood-data';
import type { FloodZone, Gauge, FloodReport } from '@/lib/orion-api';
const now = Date.parse('2026-10-11T17:00:00Z');
export const point = { lat: 29.76, lon: -95.37 };
export const warning: FloodZone = { id: 'nws-1', source: 'nws', event: 'Flash Flood Warning', severity: 'severe',
  effective: '2026-10-11T16:00:00Z', expires: '2026-10-11T18:00:00Z',
  geometry: { type: 'MultiPolygon', coordinates: [[[[-95.38, 29.75], [-95.36, 29.75], [-95.36, 29.77], [-95.38, 29.77], [-95.38, 29.75]]]] } };
export const gauge: Gauge = { site_id: '08000000', name: 'USGS river station', ...point, current_ft: 3, flood_stage_ft: 12,
  action_stage_ft: 8, status: 'normal', trend: 'steady', series: [{ time: '2026-10-11T16:50:00Z', gauge_height_ft: 3 }] };
export const report: FloodReport = { id: '17', latitude: point.lat, longitude: point.lon, water_depth_inches: 7,
  reported_at: '2026-10-11T16:30:00Z', location_name: 'Street observation', description: 'Standing water', severity: 'medium' };
export const input: HomeInput = { point, available: true, now, refreshedAt: now, zones: [], gauges: [gauge], reports: [] };
describe('Home flood-safety indicator', () => {
  it('raises the score when indicators are fewer; severe/extreme lower it', () => {
    expect(homeFloodIndicator(input)).toMatchObject({ score: 100, status: 'Low Concern' });
    expect(homeFloodIndicator({ ...input, zones: [warning] })).toMatchObject({ score: 40, status: 'High Concern' });
    expect(homeFloodIndicator({ ...input, zones: [{ ...warning, severity: 'extreme' }] }).score).toBe(25);
    expect(homeFloodIndicator({ ...input, zones: [{ ...warning, severity: 'minor' }] }).score).toBe(80);
  });
  it('never adds overlapping polygons; strongest severity counts once', () => {
    expect(homeFloodIndicator({ ...input, zones: [warning, { ...warning, id: 'overlap', severity: 'moderate' }, warning] }).score).toBe(40);
  });
  it('updates by selected location instead of counting regional warnings', () => {
    expect(homeFloodIndicator({ ...input, zones: [warning] }).score).toBe(40);
    expect(homeFloodIndicator({ ...input, point: { ...point, lon: -95.34 }, zones: [warning] }).score).toBe(100);
  });
  it('respects polygon holes and conservatively includes boundaries', () => {
    const hole = [[-95.375, 29.755], [-95.365, 29.755], [-95.365, 29.765], [-95.375, 29.765], [-95.375, 29.755]];
    expect(containsPoint(point, { ...warning, geometry: { ...warning.geometry, coordinates: [[warning.geometry.coordinates[0][0], hole]] } })).toBe(false);
    expect(containsPoint({ ...point, lon: -95.38 }, warning)).toBe(true);
  });
  it('gives greater concern to flood-stage gauges than action or normal', () => {
    const action = homeFloodIndicator({ ...input, gauges: [{ ...gauge, status: 'action', series: [{ time: gauge.series[0].time, gauge_height_ft: 9 }] }] });
    const flood = homeFloodIndicator({ ...input, gauges: [{ ...gauge, status: 'flood', series: [{ time: gauge.series[0].time, gauge_height_ft: 13 }] }] });
    expect(action.score).toBe(75); expect(flood).toMatchObject({ score: 40, status: 'High Concern' });
    expect(homeFloodIndicator({ ...input, gauges: [gauge, { ...gauge, lon: -93, status: 'flood' }] }).score).toBe(100);
  });
  it('uses recent local reports, ignores old/distant ones and does not multiply duplicates', () => {
    expect(homeFloodIndicator({ ...input, reports: [report, report] }).score).toBe(70);
    expect(homeFloodIndicator({ ...input, reports: [{ ...report, longitude: -93 }] }).score).toBe(100);
    expect(homeFloodIndicator({ ...input, reports: [{ ...report, reported_at: '2026-10-09T00:00:00Z' }] }).score).toBe(100);
    expect(homeFloodIndicator({ ...input, reports: [{ ...report, water_depth_inches: 13 }] }).score).toBe(40);
  });
  it('ignores expired/not-yet-active warnings, keeps recorded hazards distinct', () => {
    expect(homeFloodIndicator({ ...input, zones: [{ ...warning, expires: '2026-10-11T15:00:00Z' }] }).score).toBe(100);
    expect(homeFloodIndicator({ ...input, zones: [{ ...warning, effective: '2026-10-11T18:00:00Z' }] }).score).toBe(100);
    expect(homeFloodIndicator({ ...input, zones: [{ ...warning, source: 'noaa_fim' }] })).toMatchObject({ score: 30, areaPoints: 70 });
  });
  it('clamps the score at zero with mathematically consistent component subtraction', () => {
    const result = homeFloodIndicator({ ...input, zones: [warning], reports: [report], gauges: [{ ...gauge, status: 'flood' }] });
    expect(result.score).toBe(Math.max(0, 100 - result.areaPoints - result.gaugePoints - result.reportPoints));
  });
  it.each([
    { available: false }, { point: null }, { gauges: [] }, { refreshedAt: now - HOME_POLICY.fetchAgeMs - 1 },
    { zones: [{ ...warning, source: 'demo' }] }, { zones: [{ ...warning, severity: 'unknown' }] },
    { zones: [{ ...warning, expires: null }] }, { gauges: [{ ...gauge, series: [] }] },
    { gauges: [{ ...gauge, flood_stage_ft: null }] }, { gauges: [{ ...gauge, status: 'unknown' }] },
    { gauges: [{ ...gauge, series: [{ time: '2026-10-10T00:00:00Z', gauge_height_ft: 3 }] }] },
    { reports: [{ ...report, latitude: null }] }, { reports: [{ ...report, reported_at: null }] },
    { reports: [{ ...report, description: 'Demo report' }] }, { reports: [{ ...report, water_depth_inches: null }] },
    { reports: Array.from({ length: HOME_POLICY.reportLimit }, () => report) },
    { gauges: Array.from({ length: HOME_POLICY.gaugeLimit }, () => gauge) },
    { zones: Array.from({ length: HOME_POLICY.zoneLimit }, () => warning) },
  ] as Partial<HomeInput>[])('shows no number for unavailable/incomplete/demo input %#', change => {
    expect(homeFloodIndicator({ ...input, ...change })).toMatchObject({ score: null, status: 'Score unavailable' });
  });
  it('bounds local queries conservatively and refuses unsupported boundary regions', () => {
    expect(homeBounds(point)?.gauges.split(',').map(Number)).toHaveLength(4);
    expect(homeBounds({ lat: 89, lon: 0 })).toBeNull();
    expect(homeBounds({ lat: 10, lon: 179.999 })).toBeNull();
  });
});
