import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SafetyProvider } from '@/components/safety-context';
import { OrionProvider, useOrion } from '@/components/orion-context';
import { OrionRoutePlanner } from '@/components/orion-route-planner';
import { response, route, snap } from './orion-fixtures';

vi.mock('@/components/evacuation-map', () => ({ EvacuationMap: ({ data }: { data: unknown }) => <pre data-testid="map">{JSON.stringify(data)}</pre> }));
let host: HTMLDivElement, root: Root, client: QueryClient;
let api: ReturnType<typeof useOrion>;
let fetcher: ReturnType<typeof vi.fn>;
const requests: object[] = [];
function Harness() { api = useOrion(); return <OrionRoutePlanner />; }
async function settle() { await act(async () => { await new Promise(r => setTimeout(r, 35)); }); }
async function click(text: string) {
  const button = [...host.querySelectorAll('button')].find(b => b.textContent === text)!;
  expect(button).toBeTruthy(); await act(async () => button.click()); await settle();
}
async function mount(database = true) {
  fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    let data: unknown = [];
    if (url.endsWith('/health')) data = { status: database ? 'ok' : 'degraded', database, postgis: database, ors: true, timescaledb: database };
    if (url.endsWith('/api/routes')) { requests.push(JSON.parse(init!.body as string)); data = response; }
    return new Response(JSON.stringify(data));
  });
  vi.stubGlobal('fetch', fetcher);
  await act(async () => root.render(<QueryClientProvider client={client}><SafetyProvider><OrionProvider><Harness /></OrionProvider></SafetyProvider></QueryClientProvider>));
  await settle(); await settle();
  await act(async () => { api.setOrigin({ name: 'Sulphur High School', ...snap.original }); api.setDestination({ name: 'Airport', lat: 29.74, lon: -95.37 }); });
  await settle();
}
beforeEach(() => { vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); requests.length = 0; host = document.createElement('div'); document.body.append(host); root = createRoot(host); client = new QueryClient(); });
afterEach(async () => { await act(async () => root.unmount()); client.clear(); host.remove(); vi.unstubAllGlobals(); });
describe('SafeHaven backend response integration', () => {
  it('requests real routes and renders server exposure, risk, time and geometry', async () => {
    await mount(); await click('Find route');
    expect(requests[0]).toMatchObject({ origin: snap.original, preference: 'safest', profile: 'driving-car' });
    expect(host.textContent).toContain('Risk 24/100'); expect(host.textContent).toContain('1.00 miles (26.8%)');
    expect(host.textContent).toContain('12 min'); expect(host.textContent).toContain('Large areas exceed provider avoidance limits.');
    expect(JSON.parse(host.querySelector('[data-testid="map"]')!.textContent!).routes[0].geometry).toEqual(route.geometry);
    expect(host.textContent).not.toContain('Heights Community Center');
  });
  it('disables routing and suppresses database demo fallbacks when database is unavailable', async () => {
    await mount(false);
    expect(host.textContent).toContain('Demo fallback data is not shown');
    expect((([...host.querySelectorAll('button')].find(b => b.textContent === 'Find route')) as HTMLButtonElement).disabled).toBe(true);
    expect(fetcher.mock.calls.some(([url]) => /flood-zones|gauges|flood-reports/.test(url))).toBe(false);
  });
  it('never recommends Dangerous routes even if the response recommends one', async () => {
    await mount(); fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ ...response, no_lower_risk_route_found: true, routes: [{ ...route, risk_band: 'dangerous', risk_score: 80 }] })));
    await click('Find route'); expect(host.textContent).toContain('No lower-exposure route found. Travel safety cannot be confirmed.');
    expect(host.textContent).toContain('Dangerous: for information only'); expect(host.textContent).not.toContain('preferred candidate');
  });
  it('Cancel does not retry or change selected locations', async () => {
    await mount(); fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ ...response, routes: [], snap_proposals: [snap] })));
    await click('Find route'); expect(host.textContent).toContain('56 meters'); await click('Cancel');
    expect(api.origin).toMatchObject(snap.original); expect(requests).toHaveLength(0);
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/api/routes'))).toHaveLength(1);
  });
  it('requires public entrance confirmation and retains originals when accepting snaps', async () => {
    await mount(); fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ ...response, routes: [], snap_proposals: [snap] })));
    await click('Find route');
    expect((([...host.querySelectorAll('button')].find(b => b.textContent === 'Accept')) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => (host.querySelector('input[type="checkbox"]') as HTMLInputElement).click());
    await click('Accept');
    expect(requests[0]).toMatchObject({ origin: snap.proposed, accepted_snaps: [{ ...snap, public_access_confirmed: true }] });
    expect(api.origin).toMatchObject(snap.original);
  });
  it('shows backend errors instead of inventing a route', async () => {
    await mount(); fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'No drivable route. Select a public entrance.' }), { status: 422 }));
    await click('Find route'); expect(host.textContent).toContain('No drivable route. Select a public entrance.');
    expect(JSON.parse(host.querySelector('[data-testid="map"]')!.textContent!).routes).toEqual([]);
  });
  it('clears returned geometry when selected endpoints change', async () => {
    await mount(); await click('Find route'); await act(async () => api.setOrigin(null)); await settle();
    expect(JSON.parse(host.querySelector('[data-testid="map"]')!.textContent!).routes).toEqual([]);
  });
  it.each(['balanced', 'fastest'])('sends %s preference to backend', async preference => {
    await mount(); await act(async () => (host.querySelector(`input[value="${preference}"]`) as HTMLInputElement).click());
    await click('Find route'); expect(requests[0]).toMatchObject({ preference });
  });
  it('selects coordinates returned by geocoding instead of changing a demo label', async () => {
    await mount();
    fetcher.mockImplementation(async (url: string) => new Response(JSON.stringify(url.includes('/api/geocode')
      ? [{ name: 'Provider school entrance', lat: 30.236, lon: -93.377 }] : [])));
    const input = host.querySelector('input') as HTMLInputElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'school entrance');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => { await new Promise(r => setTimeout(r, 350)); }); await settle();
    await click('Provider school entrance');
    expect(api.origin).toEqual({ name: 'Provider school entrance', lat: 30.236, lon: -93.377 });
    expect(fetcher.mock.calls.some(([url]) => url.includes('/api/geocode?q=school%20entrance'))).toBe(true);
  });
  it('rejects stale route responses after endpoints change', async () => {
    await mount(); let resolve!: (value: Response) => void;
    fetcher.mockImplementationOnce(() => new Promise<Response>(r => { resolve = r; }));
    await click('Find route');
    await act(async () => api.setOrigin(null));
    await act(async () => resolve(new Response(JSON.stringify(response)))); await settle();
    expect(JSON.parse(host.querySelector('[data-testid="map"]')!.textContent!).routes).toEqual([]);
  });
  it('blocks fixture-mode responses even with a healthy database', async () => {
    await mount();
    fetcher.mockImplementation(async (url: string) => new Response(JSON.stringify(url.endsWith('/health')
      ? { database: true, postgis: true, ors: true } : url.endsWith('/api/flood-zones') ? [{ source: 'demo' }] : [])));
    await act(async () => { await api.refresh(); }); await settle();
    expect(host.textContent).toContain('Backend returned demo warnings');
    expect(JSON.parse(host.querySelector('[data-testid="map"]')!.textContent!).zones).toEqual([]);
  });
  it('does not use stale successful health data after a failed refresh', async () => {
    await mount(); fetcher.mockResolvedValueOnce(new Response('Unavailable', { status: 503 }));
    await act(async () => { await api.refresh(); }); await settle();
    expect(api.routingAvailable).toBe(false); expect(host.textContent).toContain('Orion unavailable');
  });
});
