import { describe, it, expect, vi } from 'vitest';
import { createOrionClient } from '@/lib/orion-api';
import { buildOrionMapData } from '@/lib/orion-map-data';
import { response, route, snap } from './orion-fixtures';

describe('Orion HTTP client and geometry', () => {
  it('calls all backend endpoints without browser credentials', async () => {
    const transport = vi.fn().mockImplementation(async () => new Response('[]', { status: 200 }));
    const c = createOrionClient('http://127.0.0.1:8081/', transport);
    await c.health(); await c.floodZones(); await c.gauges(); await c.floodReports(); await c.geocode('Sulphur & school');
    expect(transport.mock.calls.map(([url]) => url)).toEqual([
      'http://127.0.0.1:8081/health', 'http://127.0.0.1:8081/api/flood-zones', 'http://127.0.0.1:8081/api/gauges',
      'http://127.0.0.1:8081/api/flood-reports?limit=100', 'http://127.0.0.1:8081/api/geocode?q=Sulphur%20%26%20school',
    ]);
    transport.mock.calls.forEach(([, init]) => { expect(init.credentials).toBe('omit'); expect(init.headers.Authorization).toBeUndefined(); });
  });
  it('posts selected coordinates and preserves backend route/exposure/snapping metadata', async () => {
    const payload = { ...response, accepted_snaps: [{ ...snap, public_access_confirmed: true }] };
    const transport = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload)));
    const c = createOrionClient('https://orion.example', transport);
    const request = { origin: snap.proposed, destination: { lat: 29.74, lon: -95.37 }, profile: 'driving-car', preference: 'safest' as const,
      accepted_snaps: [{ ...snap, public_access_confirmed: true as const }] };
    expect(await c.routes(request)).toEqual(payload);
    expect(JSON.parse(transport.mock.calls[0][1].body)).toEqual(request);
    expect(transport.mock.calls[0][1].method).toBe('POST');
  });
  it.each([403, 422, 429, 503])('reports backend status and detail (%s)', async status => {
    const c = createOrionClient('https://orion.example', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Select an entrance; routing rejected.' }), { status })));
    await expect(c.geocode('Airport')).rejects.toMatchObject({ status, message: 'Select an entrance; routing rejected.' });
  });
  it('handles non-JSON errors', async () => {
    const c = createOrionClient('https://orion.example', vi.fn().mockResolvedValue(new Response('Unavailable', { status: 502 })));
    await expect(c.floodZones()).rejects.toMatchObject({ status: 502 });
  });
  it('forwards cancellation', async () => {
    const abort = new AbortController(); abort.abort();
    const transport = vi.fn().mockImplementation((_url, init) => { expect(init.signal.aborted).toBe(true); throw new DOMException('Aborted', 'AbortError'); });
    await expect(createOrionClient('https://orion.example', transport).geocode('School', abort.signal)).rejects.toMatchObject({ name: 'AbortError' });
  });
  it('draws only returned geometries and never a demo route', () => {
    const zone = { id: 'nws-7', source: 'nws', event: 'Flash Flood Warning', severity: 'severe' as const,
      geometry: { type: 'MultiPolygon' as const, coordinates: [[[[-95.4, 29.7], [-95.3, 29.7], [-95.3, 29.8], [-95.4, 29.7]]]] } };
    const input = { zones: [zone], gauges: [], reports: [], routes: [route], selectedId: route.id, origin: null, destination: null };
    const data = buildOrionMapData(input);
    expect(data.routes.features).toEqual([expect.objectContaining({ geometry: route.geometry })]);
    expect(data.zones.features).toEqual([expect.objectContaining({ geometry: zone.geometry, properties: expect.objectContaining({ source: 'nws' }) })]);
    expect(buildOrionMapData({ ...input, routes: [] }).routes.features).toEqual([]);
  });
});
