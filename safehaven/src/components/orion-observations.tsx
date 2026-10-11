import { Link } from '@tanstack/react-router';
import { ConnectionStatus, useOrion } from './orion-context';
import { OrionPlaceSearch } from './orion-place-search';

export function OrionHomeScreen() {
  const o = useOrion();
  const zones = o.dataAvailable ? o.zones.data ?? [] : [];
  return <div className="page orion-home">
    <h1 className="text-2xl font-extrabold">Your flood-awareness workspace</h1><ConnectionStatus />
    <Link to="/explore" className="panel block">Choose a location: {o.origin?.name ?? 'No location selected'}</Link>
    <Link to="/threat" className="panel warning-panel block mt-6"><h2 className="font-bold">Flood warnings in Orion coverage</h2>
      <p>{o.dataAvailable && o.zones.isSuccess && !o.zones.isError ? `${zones.length} active areas returned` : 'Warning data unavailable or loading'}</p>
      <p className="text-sm">Regional warning areas are not your personal risk score or confirmed flooded roads.</p></Link>
    <div className="panel mt-6"><h2 className="font-bold">Plan a real road route</h2><p className="text-sm">Orion assesses provider-generated routes using warning exposure and hazard evidence.</p>
      <Link to="/map" className="text-primary min-h-12 inline-flex items-center">Open flood-aware map</Link></div>
    <Link to="/plan" className="panel safe-panel block mt-6"><h2 className="font-bold">Your emergency checklist</h2><p>Prepare essentials and follow local authorities.</p></Link>
    <div className="panel mt-6"><h2>Personal safety score and forecasts</h2><p>Not available from Orion. Profile preferences remain demonstrations; no live personal predictions are generated.</p></div>
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
