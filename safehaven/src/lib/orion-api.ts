import type { components } from '../../../packages/shared/src/api';

type Schema = components['schemas'];
export type Place = Schema['Place'];
export type FloodZone = Schema['FloodZone'];
export type Gauge = Schema['Gauge'];
export type FloodReport = Schema['FloodReport'];
export type RouteRequest = Schema['RouteRequest'];
export type RouteResponse = Schema['RouteResponse'];
export type RouteCandidate = Schema['RouteCandidate'];
export type SnapConfirmation = Schema['SnapConfirmation'];
export type SnapProposal = Schema['SnapProposal'];
export type HealthResponse = Schema['HealthResponse'];
export type RoutePreference = Schema['RoutePreference'];
export type LatLng = Schema['LatLng'];

export class OrionApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'OrionApiError';
    this.status = status;
  }
}

// Only a public backend origin is configured here. ORS/database keys stay in Python.
export const ORION_API_BASE = import.meta.env.VITE_ORION_API_BASE || 'http://127.0.0.1:8081';

export function createOrionClient(base: string, transport: typeof fetch = fetch) {
  const origin = base.replace(/\/$/, '');
  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const controller = new AbortController();
    const abort = () => controller.abort();
    init.signal?.addEventListener('abort', abort, { once: true });
    if (init.signal?.aborted) controller.abort();
    const timer = setTimeout(abort, 90_000);
    try {
      const response = await transport(`${origin}${path}`, {
        ...init, signal: controller.signal, credentials: 'omit',
        headers: { 'Content-Type': 'application/json', ...init.headers },
      });
      if (!response.ok) {
        let message = `Orion request failed (${response.status}).`;
        try {
          const error = await response.json();
          if (typeof error.detail === 'string') message = error.detail;
        } catch { /* retain status message for non-JSON failures */ }
        throw new OrionApiError(message, response.status);
      }
      return await response.json() as T;
    } finally {
      clearTimeout(timer);
      init.signal?.removeEventListener('abort', abort);
    }
  }
  return {
    health: () => request<HealthResponse>('/health'),
    floodZones: () => request<FloodZone[]>('/api/flood-zones'),
    gauges: () => request<Gauge[]>('/api/gauges'),
    floodReports: () => request<FloodReport[]>('/api/flood-reports?limit=100'),
    geocode: (query: string, signal?: AbortSignal) => request<Place[]>(`/api/geocode?q=${encodeURIComponent(query)}`, { signal }),
    routes: (body: RouteRequest, signal?: AbortSignal) => request<RouteResponse>('/api/routes', {
      method: 'POST', body: JSON.stringify(body), signal,
    }),
  };
}
export type OrionClient = ReturnType<typeof createOrionClient>;
