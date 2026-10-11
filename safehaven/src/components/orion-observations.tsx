import { Link } from '@tanstack/react-router';
import { ConnectionStatus, useOrion } from './orion-context';
import { OrionPlaceSearch } from './orion-place-search';
import { useHomeFloodIndicator } from '@/lib/home-flood-data';
import { ChevronRight, MapPin, ShieldCheck, TriangleAlert, Waves } from 'lucide-react';

export function OrionHomeScreen() {
  const o = useOrion();
  const indicator = useHomeFloodIndicator(o.origin, o.dataAvailable, o.health.dataUpdatedAt);
  return <div className="page home-page home-flood-indicator" data-concern={indicator.status}>
    <div className="home-location"><p className="eyebrow mb-2">Selected location</p>
      <Link to="/explore" className="flex items-center gap-2 text-sm font-semibold min-h-12"><MapPin size={16} className="text-primary" />
        {o.origin?.name ?? 'Choose a location'}<ChevronRight size={14} /><span className="sr-only">Choose another location</span></Link></div>
    <div className="score-wrap">
      <h1 className="text-sm font-semibold text-muted-foreground mb-4">Your safety score</h1>
      <div className="score-ring" role="img" aria-label={indicator.score == null ? 'Score unavailable' : `Flood-safety indicator ${indicator.score} out of 100`}>
        <svg viewBox="0 0 208 208" aria-hidden="true"><circle className="ring-track" cx="104" cy="104" r="90" />
          {indicator.score != null && <circle className="ring-value" cx="104" cy="104" r="90" strokeDashoffset={565.5 * (1 - indicator.score / 100)} />}</svg>
        <div className="score-number">{indicator.score == null ? <strong className="home-score-unavailable">Score unavailable</strong>
          : <><strong>{indicator.score}</strong><span>out of 100</span></>}</div>
      </div>
      {indicator.score != null && <span className="risk-chip"><TriangleAlert size={13} />{indicator.status}</span>}
      <p className="mt-3 text-xs text-muted-foreground">Flood-safety indicator · higher means fewer observed flood-risk indicators.</p>
      <p className="text-xs text-muted-foreground mt-2">A transparent heuristic, not a flooding probability or safety guarantee.</p>
    </div>
    <section className="panel warning-panel home-current-warnings" aria-label="Warnings at selected location">
      <div className="flex items-center gap-3"><Waves className="text-warning" /><h2 className="font-bold">Current flood-warning information</h2></div>
      {indicator.score == null ? <p className="text-sm mt-4">{indicator.reasons[0]} Warning absence cannot be confirmed.</p>
        : indicator.zones.length ? indicator.zones.map((z, i) => <div className="mt-4" key={`${z.id}:${i}`}>
          <h3 className="font-bold text-sm">{z.event} · {z.severity}</h3><p className="text-xs text-muted-foreground">{z.headline}</p>
          <p className="text-xs text-muted-foreground">Source: {z.source} · Expires: {z.expires ? new Date(z.expires).toLocaleString() : 'Not supplied'}</p></div>)
          : <p className="text-sm mt-4">No active warning or recorded hazard footprint returned at this point. This is not an all-clear.</p>}
      <p className="text-xs text-muted-foreground mt-4">NWS warning polygons indicate concern, not confirmed floodwater on a road.</p>
    </section>
    <section className="panel home-score-explanation"><h2 className="font-bold">What affects this indicator</h2>
      <p className="text-sm mt-3">Start at 100 and subtract the strongest area concern, nearby gauge-stage concern and recent local report concern. Overlapping warnings count once.</p>
      <ul className="text-xs text-muted-foreground space-y-2 mt-3">{indicator.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
      <details className="text-xs mt-4"><summary>Scoring rules and data limits</summary>
        <p className="mt-2">NWS minor/moderate/severe/extreme: 20/40/60/75 points; a recorded NOAA hazard footprint: 70. Areas use the strongest value once. Gauge action/flood stage: 25/60 points, using the strongest site within 10 km and readings no older than 3 hours. Recent reports within 2 km: 15 for positive depth below 6 inches, 30 at 6–11 inches or medium severity, 60 at 12+ inches or high severity. Reports must be within 24 hours; the strongest report counts once. Scores are capped at zero. 90–100: Low Concern; 41–89: Caution; 0–40: High Concern. These thresholds are UI policy, not a scientifically calibrated model.</p>
        <p className="mt-2">Nearby gauges may belong to different watersheds; hourly readings and community reports are imperfect and delayed. No reports does not prove no flooding. The backend does not expose a coverage or ingestion-freshness guarantee. Missing gauges, stale/unknown observations, known demo data, failed requests or potentially truncated results prevent a score. Refresh the connection if its check is older than 10 minutes.</p>
      </details>
    </section>
    <Link to="/map" className="panel safe-panel home-map-link flex items-center gap-3"><MapPin className="text-primary" />
      <div className="flex-1"><h2 className="font-bold text-sm">Open the flood-aware map</h2><p className="text-xs text-muted-foreground mt-1">Assess a real road route; this location indicator is not a route score.</p></div><ChevronRight size={17} /></Link>
    <Link to="/plan" className="panel safe-panel home-plan-link flex items-center gap-3"><ShieldCheck className="text-primary" />
      <div className="flex-1"><h2 className="font-bold text-sm">Your emergency checklist</h2><p className="text-xs text-muted-foreground mt-1">A little preparation. A lot of peace.</p></div><ChevronRight size={17} /></Link>
    <div className="home-connection"><button className="text-primary min-h-12 text-sm" type="button" disabled={!o.origin || !o.dataAvailable || indicator.refreshing}
      onClick={() => void indicator.refresh()}>{indicator.refreshing ? 'Updating Home observations…' : 'Refresh Home observations'}</button><ConnectionStatus /></div>
  </div>;
}
export function OrionThreatScreen() {
  const o = useOrion();
  return <div className="page orion-observations">
    <h1 className="text-2xl font-extrabold">Warnings and observations</h1><ConnectionStatus />
    <p>Data across Orion coverage; this list does not establish whether your current location is affected. Warning regions are precautionary, not confirmed flooded roads.</p>
    <h2 className="font-bold mt-6">Active warning areas</h2>
    {o.dataAvailable && !o.zones.isError && (o.zones.data ?? []).map(z => <article className="panel warning-panel mt-3" key={z.id}>
      <h3>{z.event} · {z.severity}</h3><p>{z.headline}</p><p>Source: {z.source} · Effective: {z.effective ?? 'Unknown'} · Expires: {z.expires ?? 'Unknown'}</p></article>)}
    {o.dataAvailable && o.zones.isSuccess && o.zones.data.length === 0 && <p>No active warnings returned for Orion coverage. This is not an all-clear.</p>}
    <h2 className="font-bold mt-6">Gauge observations</h2><p>River gauges indicate water conditions, not road passability.</p>
    {o.dataAvailable && !o.gauges.isError && (o.gauges.data ?? []).slice(0, 20).map(g => <article className="panel mt-3" key={g.site_id}>
      <h3>{g.name}</h3><p>{g.current_ft ?? 'Unknown'} ft · {g.status} · {g.trend}</p><p>Latest reading: {g.series.at(-1)?.time ?? 'Unknown'}</p></article>)}
    <p className="text-xs">Up to 20 gauges listed here; all returned gauges appear on the map.</p>
    <h2 className="font-bold mt-6">Reported flood observations</h2>
    {o.dataAvailable && !o.reports.isError && (o.reports.data ?? []).map(r => <article className="panel mt-3" key={String(r.id)}>
      <h3>{r.location_name ?? 'Flood observation'}</h3><p>{r.water_depth_inches ?? 'Unknown'} inches · {r.severity ?? 'Unspecified severity'}</p>
      <p>{r.description}</p><p>Reported: {r.reported_at ?? 'Unknown'}. Conditions may have changed; observations do not currently alter Orion route scores.</p></article>)}
    <Link to="/map" className="text-primary min-h-12 inline-flex items-center">View observations and routes on map</Link>
  </div>;
}
export function OrionExploreScreen() {
  const o = useOrion();
  return <div className="page"><h1 className="text-2xl font-extrabold">Explore a location</h1><ConnectionStatus />
    <OrionPlaceSearch label="Search address or place" value={o.origin} onSelect={o.setOrigin} />
    {o.origin && <div className="panel mt-6"><h2>{o.origin.name}</h2><p>{o.origin.lat}, {o.origin.lon}</p><Link to="/map" className="text-primary min-h-12 inline-flex items-center">Use as route origin</Link></div>}
    <p className="mt-6">Geocoding does not establish public-road access. Personal safety scores, shelter availability and future flood predictions are not provided by Orion.</p>
  </div>;
}
