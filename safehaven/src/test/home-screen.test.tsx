import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { OrionHomeScreen } from '@/components/orion-observations';
import { useOrion } from '@/components/orion-context';
vi.mock('@/components/orion-context', () => ({ useOrion: vi.fn(), ConnectionStatus: () => <p>Connection controls preserved</p> }));
vi.mock('@tanstack/react-router', () => ({ Link: ({ to, children, ...props }: { to: string; children: ReactNode }) => <a href={to} {...props}>{children}</a> }));
const now = Date.parse('2026-10-11T17:00:00Z');
const place = { name: 'Selected school', lat: 29.76, lon: -95.37 };
const gauge = { site_id: '080001', name: 'USGS river gauge', lat: 29.76, lon: -95.37, flood_stage_ft: 12, action_stage_ft: 8,
  status: 'normal', series: [{ time: '2026-10-11T16:50:00Z', gauge_height_ft: 3 }] };
const warning = { id: 'nws-1', source: 'nws', severity: 'severe', event: 'Flash Flood Warning',
  effective: '2026-10-11T16:00:00Z', expires: '2026-10-11T18:00:00Z',
  geometry: { type: 'MultiPolygon', coordinates: [[[[-95.38, 29.75], [-95.36, 29.75], [-95.36, 29.77], [-95.38, 29.77], [-95.38, 29.75]]]] } };
let host: HTMLDivElement, root: Root, queries: QueryClient, transport: ReturnType<typeof vi.fn>;
async function render(origin = place, available = true) {
  vi.mocked(useOrion).mockReturnValue({ origin, dataAvailable: available, health: { dataUpdatedAt: now } } as ReturnType<typeof useOrion>);
  await act(async () => root.render(<QueryClientProvider client={queries}><OrionHomeScreen /></QueryClientProvider>));
}
async function settle() { await act(async () => { await new Promise(r => setTimeout(r, 40)); }); }
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); vi.spyOn(Date, 'now').mockReturnValue(now);
  queries = new QueryClient(); host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  transport = vi.fn(async (url: string) => new Response(JSON.stringify(url.includes('/flood-zones?') ? [warning] : url.includes('/gauges?') ? [gauge] : [])));
  vi.stubGlobal('fetch', transport);
});
afterEach(async () => { await act(async () => root.unmount()); queries.clear(); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it('consumes bounded local API responses, restores score design and retains links', async () => {
  await render(); await settle(); await settle();
  expect(host.querySelector('.score-number strong')?.textContent).toBe('40');
  expect(host.textContent).toContain('Your safety score'); expect(host.textContent).toContain('High Concern');
  expect(host.textContent).toContain('not a flooding probability or safety guarantee');
  expect(host.querySelector('a[href="/map"]')).not.toBeNull(); expect(host.querySelector('a[href="/plan"]')).not.toBeNull();
  expect(host.querySelector('a[href="/explore"]')).not.toBeNull();
  expect(transport.mock.calls.some(([url]) => url.includes('/flood-zones?bbox=') && url.includes('limit=2000'))).toBe(true);
  expect(transport.mock.calls.some(([url]) => url.includes('/gauges?bbox=') && url.includes('limit=1000'))).toBe(true);
  expect(transport.mock.calls.some(([url]) => url.endsWith('/flood-reports?limit=500'))).toBe(true);
  expect(transport.mock.calls.every(([url]) => !url.includes('/routes'))).toBe(true);
});
it('refetches on location changes without displaying the old score', async () => {
  await render(); await settle(); await settle();
  expect(host.querySelector('.score-number strong')?.textContent).toBe('40');
  await render({ ...place, name: 'Other location', lon: -95.34 });
  expect(host.querySelector('.score-number strong')?.textContent).toBe('Score unavailable');
  await settle(); await settle();
  expect(host.querySelector('.score-number strong')?.textContent).toBe('100'); expect(host.textContent).toContain('Low Concern');
  expect(host.textContent).toContain('Other location');
});
it('does not render a number after a failed data request', async () => {
  transport.mockImplementation(async (url: string) => url.includes('/gauges?') ? new Response('Unavailable', { status: 503 }) : new Response('[]'));
  await render(); await settle(); await settle();
  expect(host.querySelector('.score-number strong')?.textContent).toBe('Score unavailable'); expect(host.querySelector('.risk-chip')).toBeNull();
});
it('hides a previous number if data becomes unavailable/offline', async () => {
  await render(); await settle(); await settle(); await render(place, false);
  expect(host.querySelector('.score-number strong')?.textContent).toBe('Score unavailable');
});
it('does not render a score from demo-only local warnings', async () => {
  transport.mockImplementation(async (url: string) => new Response(JSON.stringify(url.includes('/flood-zones?') ? [{ ...warning, source: 'demo' }] : url.includes('/gauges?') ? [gauge] : [])));
  await render(); await settle(); await settle();
  expect(host.querySelector('.score-number strong')?.textContent).toBe('Score unavailable');
});
