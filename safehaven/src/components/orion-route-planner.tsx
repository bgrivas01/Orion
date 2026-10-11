import { useEffect, useRef, useState } from 'react';
import { useOrion, ConnectionStatus } from './orion-context';
import { OrionPlaceSearch } from './orion-place-search';
import { EvacuationMap } from './evacuation-map';
import { Button } from './ui/button';
import type { RoutePreference, RouteResponse, SnapConfirmation } from '@/lib/orion-api';

const miles = (m: number) => (m / 1609.344).toFixed(2);
export function OrionRoutePlanner() {
  const o = useOrion();
  const [preference, setPreference] = useState<RoutePreference>('safest');
  const [result, setResult] = useState<RouteResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [accepted, setAccepted] = useState<SnapConfirmation[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const active = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const proposals = result?.snap_proposals ?? [];
  function invalidate() {
    generation.current++; active.current?.abort();
    setResult(null); setSelectedId(null); setAccepted([]); setConfirmed(false); setLoading(false); setError('');
  }
  useEffect(() => { invalidate(); }, [o.origin, o.destination, preference, o.routingAvailable]);
  useEffect(() => () => { generation.current++; active.current?.abort(); }, []);
  async function calculate(snaps: SnapConfirmation[] = []) {
    if (!o.origin || !o.destination || !o.routingAvailable) return;
    active.current?.abort();
    const controller = new AbortController(); active.current = controller;
    const id = ++generation.current;
    setLoading(true); setError(''); setResult(null); setConfirmed(false); setSelectedId(null); setAccepted(snaps);
    const point = (endpoint: 'origin' | 'destination') => snaps.find(s => s.endpoint === endpoint)?.proposed
      ?? { lat: o[endpoint]!.lat, lon: o[endpoint]!.lon };
    try {
      const response = await o.client.routes({ origin: point('origin'), destination: point('destination'),
        preference, profile: 'driving-car', accepted_snaps: snaps }, controller.signal);
      if (id !== generation.current || controller.signal.aborted) return;
      setResult(response);
      setSelectedId(response.routes.find(r => r.id === response.recommended_id)?.id ?? response.routes[0]?.id ?? null);
    } catch (e) {
      if (id === generation.current && !controller.signal.aborted) setError(e instanceof Error ? e.message : 'Routing unavailable.');
    } finally { if (id === generation.current) setLoading(false); }
  }
  const routes = result?.routes ?? [];
  const endpoint = (name: 'origin' | 'destination') => accepted.find(s => s.endpoint === name)?.proposed ?? o[name];
  return <div className="page orion-planner">
    <div><h1 className="text-2xl font-extrabold">Flood-aware route planner</h1>
      <p className="text-sm text-muted-foreground mt-2">Real road routes assessed by Orion. Lower exposure does not guarantee road safety.</p></div>
    <ConnectionStatus />
    <div className="orion-routing-grid">
      <section className="panel orion-controls" aria-label="Route planning">
        <OrionPlaceSearch label="From" value={o.origin} onSelect={o.setOrigin} />
        <OrionPlaceSearch label="To" value={o.destination} onSelect={o.setDestination} />
        <fieldset className="orion-preferences"><legend>Routing priority</legend>
          {(['safest', 'balanced', 'fastest'] as const).map(p => <label key={p}><input type="radio" name="preference" value={p}
            checked={preference === p} onChange={() => setPreference(p)} /> {p[0].toUpperCase() + p.slice(1)}</label>)}
        </fieldset>
        <Button disabled={!o.routingAvailable || !o.origin || !o.destination || loading} onClick={() => void calculate()}>
          {loading ? 'Assessing routes…' : 'Find route'}
        </Button>
        <p className="text-xs text-muted-foreground">Select geocoded locations first. Flood observations and warnings have limited coverage; follow official guidance.</p>
        {error && <p role="alert">{error}</p>}
      </section>
      <EvacuationMap offline={o.offline} data={{ zones: o.dataAvailable ? o.zones.data ?? [] : [],
        gauges: o.dataAvailable ? o.gauges.data ?? [] : [], reports: o.dataAvailable ? o.reports.data ?? [] : [],
        routes, selectedId, origin: endpoint('origin'), destination: endpoint('destination') }} />
    </div>
    {result && <section className="orion-results" aria-label="Route results">
      <p className="text-xs text-muted-foreground">Assessed {new Date(result.generated_at).toLocaleString()} · {result.flood_zones_considered} flood areas considered</p>
      {result.no_lower_risk_route_found && <p role="alert" className="panel warning-panel">No lower-exposure route found. Travel safety cannot be confirmed.</p>}
      {result.warnings.map((warning, i) => <p role="alert" key={i}>{warning}</p>)}
      {proposals.length > 0 && <div className="panel warning-panel" role="region" aria-label="Confirm road point">
        {proposals.map(s => <div key={s.endpoint}>
          <h2>We found a nearby drivable road {Math.round(s.distance_m)} meters from your selected {s.endpoint}. Use this point?</h2>
          <p>Original: {s.original.lat}, {s.original.lon}. Proposed: {s.proposed.lat}, {s.proposed.lon}.</p>
        </div>)}
        <p>Nearest road does not establish building access. Highways, barriers or restricted entrances may make it inaccessible. Select an entrance manually if uncertain. The new route will receive a full flood-risk assessment.</p>
        <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /> I have verified these points are appropriate public-road entrances.</label>
        <div className="flex gap-3 mt-4"><Button disabled={!confirmed || loading} onClick={() => void calculate(proposals.map(p => ({ ...p, public_access_confirmed: true })))}>Accept</Button>
          <Button variant="secondary" onClick={invalidate}>Cancel</Button></div>
      </div>}
      {!routes.length && !proposals.length && <p>No route returned. Select a public-road entrance or nearby address.</p>}
      {(result.accepted_snaps ?? []).map(s => <p key={s.endpoint}>Confirmed {s.endpoint} moved {Math.round(s.distance_m)} meters. Original: {s.original.lat}, {s.original.lon}. Building access remains unverified.</p>)}
      <div className="orion-route-cards">{routes.map(route => <article className={`panel ${selectedId === route.id ? 'orion-selected' : ''}`} key={route.id}>
        <h2 className="font-bold">{route.label} · {route.risk_band}</h2>
        {route.id === result.recommended_id && route.risk_band !== 'dangerous' && !result.no_lower_risk_route_found && <p>Orion preferred candidate — not a safety guarantee</p>}
        {route.risk_band === 'dangerous' && <p role="alert">Dangerous: for information only. Travel safety cannot be confirmed.</p>}
        <p>{miles(route.distance_m)} miles · {Math.round(route.duration_s / 60)} min</p>
        <p>Risk {route.risk_score}/100 (higher means greater risk)</p>
        <p>Unique warning exposure: {miles(route.warning_exposure_m)} miles ({route.warning_exposure_percent.toFixed(1)}%)</p>
        <p>Warning severity: {Object.entries(route.warning_severity_m ?? {}).filter(([, m]) => m > 0).map(([severity, m]) => `${severity}: ${miles(m)} mi`).join(', ') || 'No warning overlap reported'}</p>
        <p>{route.warning_avoidance_achieved ? 'Warning-area avoidance achieved in the assessed geometry.' : 'Complete warning avoidance not verified.'} This does not prove road passability.</p>
        <p>Recorded hazard exposure: {miles(route.hazard_exposure_m)} miles. NWS warning regions are not confirmed flooded roads.</p>
        {route.initial_warning_exit_m > 0 && <p>Initial warning exit after {miles(route.initial_warning_exit_m)} miles; {route.warning_reentries} re-entries.</p>}
        {route.warnings.map((w, i) => <p role="alert" key={i}>{w}</p>)}
        <Button variant="secondary" onClick={() => setSelectedId(route.id)}>Show on map</Button>
      </article>)}</div>
    </section>}
  </div>;
}
