import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { createOrionClient, ORION_API_BASE, type Place } from '@/lib/orion-api';
import { useSafety } from './safety-context';

function useOrionState() {
  const { offline } = useSafety();
  const client = useMemo(() => createOrionClient(ORION_API_BASE), []);
  const options = { retry: false, staleTime: Infinity, refetchOnWindowFocus: false, refetchOnReconnect: false };
  // /health exercises ORS and consumes quota. Check once, then refresh explicitly.
  const health = useQuery({ ...options, queryKey: ['orion', ORION_API_BASE, 'health'], queryFn: client.health, enabled: !offline });
  const databaseAvailable = !offline && !health.isError && health.data?.database === true && health.data?.postgis === true;
  const zones = useQuery({ ...options, queryKey: ['orion', ORION_API_BASE, 'zones'], queryFn: client.floodZones, enabled: databaseAvailable });
  const gauges = useQuery({ ...options, queryKey: ['orion', ORION_API_BASE, 'gauges'], queryFn: client.gauges, enabled: databaseAvailable });
  const reports = useQuery({ ...options, queryKey: ['orion', ORION_API_BASE, 'reports'], queryFn: client.floodReports, enabled: databaseAvailable });
  const fixtureMode = zones.data?.some(z => z.source === 'demo') === true;
  const dataAvailable = databaseAvailable && !fixtureMode;
  const [origin, setOrigin] = useState<Place | null>(null);
  const [destination, setDestination] = useState<Place | null>(null);
  const routingAvailable = dataAvailable && health.data?.ors === true && zones.isSuccess && !zones.isError;
  async function refresh() {
    if (offline) return;
    const checked = await health.refetch();
    if (!checked.isError && checked.data?.database && checked.data?.postgis) {
      await Promise.all([zones.refetch(), gauges.refetch(), reports.refetch()]);
    }
  }
  return { client, health, zones, gauges, reports, dataAvailable, routingAvailable, fixtureMode, offline,
    origin, setOrigin, destination, setDestination, refresh };
}
const OrionContext = createContext<ReturnType<typeof useOrionState> | null>(null);
export function OrionProvider({ children }: { children: ReactNode }) {
  const state = useOrionState();
  return <OrionContext.Provider value={state}>{children}</OrionContext.Provider>;
}
export function useOrion() {
  const state = useContext(OrionContext);
  if (!state) throw new Error('OrionProvider missing');
  return state;
}

export function ConnectionStatus() {
  const o = useOrion();
  const checking = o.health.isFetching || o.zones.isFetching || o.gauges.isFetching || o.reports.isFetching;
  const label = o.offline ? 'Offline preview — live routing disabled' : o.health.isPending ? 'Checking Orion connection…'
    : o.health.isError ? 'Orion unavailable. Check that the backend is running on port 8081.'
    : o.fixtureMode ? 'Backend returned demo warnings. Live routing disabled; demo data is not shown.'
    : !o.dataAvailable ? 'Flood database unavailable. Demo fallback data is not shown.'
    : !o.health.data?.ors ? 'Flood data connected; geocoding/routing service unavailable.'
    : !o.routingAvailable ? 'Warning data unavailable or loading; routing disabled.' : 'Orion connected';
  const errors = [o.zones.isError && 'warnings', o.gauges.isError && 'gauges', o.reports.isError && 'reports'].filter(Boolean);
  return <div className="panel orion-status" role="status">
    <p>{label}</p>
    {errors.length > 0 && <p>Could not load {errors.join(', ')}. Missing data does not mean conditions are clear.</p>}
    <button type="button" disabled={checking || o.offline} onClick={() => void o.refresh()} className="text-primary min-h-10">
      {checking ? 'Loading…' : 'Refresh connection & observations'}
    </button>
  </div>;
}
