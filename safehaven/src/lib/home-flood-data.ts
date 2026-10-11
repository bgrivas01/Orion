import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ORION_API_BASE, type LatLng, type FloodZone, type Gauge, type FloodReport } from './orion-api';
import { HOME_POLICY, homeFloodIndicator } from './home-flood-indicator';

export function homeBounds(point: LatLng) {
  if (!Number.isFinite(point.lat) || !Number.isFinite(point.lon)) return null;
  // Slightly oversized spherical envelope; exact haversine radius is filtered later.
  const dy = HOME_POLICY.gaugeRadiusM / 110000, dx = HOME_POLICY.gaugeRadiusM / (110000 * Math.cos(point.lat * Math.PI / 180));
  if (!Number.isFinite(dx) || Math.abs(point.lat) + dy >= 85 || Math.abs(point.lon) + dx >= 180) return null;
  return { warnings: [point.lon - .0001, point.lat - .0001, point.lon + .0001, point.lat + .0001].join(','),
    gauges: [point.lon - dx, point.lat - dy, point.lon + dx, point.lat + dy].join(',') };
}
async function get<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(ORION_API_BASE.replace(/\/$/, '') + path, {
    signal: AbortSignal.any([signal, AbortSignal.timeout(20_000)]), credentials: 'omit',
  });
  if (!response.ok) throw new Error(`Home observations unavailable (${response.status}).`);
  const data = await response.json();
  if (!Array.isArray(data)) throw new Error('Home observation response is incomplete.');
  return data as T;
}
// Home-only requests/cache. Never modify Map's queries, selected endpoints or routing.
export function useHomeFloodIndicator(point: LatLng | null, available: boolean, healthUpdatedAt: number) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 30_000); return () => clearInterval(timer); }, []);
  const bounds = point ? homeBounds(point) : null;
  const enabled = available && bounds != null;
  const options = { enabled, retry: false, staleTime: 30_000, refetchInterval: enabled ? 60_000 : false as const };
  const zones = useQuery({ ...options, queryKey: ['home-flood', ORION_API_BASE, 'zones', bounds?.warnings],
    queryFn: ({ signal }) => get<FloodZone[]>(`/api/flood-zones?bbox=${bounds!.warnings}&limit=${HOME_POLICY.zoneLimit}`, signal) });
  const gauges = useQuery({ ...options, queryKey: ['home-flood', ORION_API_BASE, 'gauges', bounds?.gauges],
    queryFn: ({ signal }) => get<Gauge[]>(`/api/gauges?bbox=${bounds!.gauges}&limit=${HOME_POLICY.gaugeLimit}`, signal) });
  const reports = useQuery({ ...options, queryKey: ['home-flood', ORION_API_BASE, 'reports'],
    queryFn: ({ signal }) => get<FloodReport[]>(`/api/flood-reports?limit=${HOME_POLICY.reportLimit}`, signal) });
  const complete = enabled && zones.isSuccess && gauges.isSuccess && reports.isSuccess
    && !zones.isError && !gauges.isError && !reports.isError && now - healthUpdatedAt <= HOME_POLICY.healthAgeMs;
  const indicator = homeFloodIndicator({ point, zones: zones.data ?? [], gauges: gauges.data ?? [], reports: reports.data ?? [],
    now, refreshedAt: Math.min(zones.dataUpdatedAt, gauges.dataUpdatedAt, reports.dataUpdatedAt), available: complete });
  return { ...indicator, refreshing: zones.isFetching || gauges.isFetching || reports.isFetching,
    refresh: () => enabled ? Promise.all([zones.refetch(), gauges.refetch(), reports.refetch()]) : Promise.resolve([]) };
}
