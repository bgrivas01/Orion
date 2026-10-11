import { useEffect, useRef, useState } from 'react';
import type { FeatureCollection } from 'geojson';
import type { Map, GeoJSONSource } from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import 'maplibre-gl/dist/maplibre-gl.css';
import { buildOrionMapData, type OrionMapData } from '@/lib/orion-map-data';

// Vite serves the installed worker as a separate asset; web/'s Next.js fix is independent.
export function EvacuationMap({ data, offline }: { data: OrionMapData; offline: boolean }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<Map | null>(null);
  const latest = useRef(data); latest.current = data;
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    if (offline) return;
    let disposed = false;
    setReady(false); setError('');
    void import('maplibre-gl').then(ml => {
      if (disposed || !container.current) return;
      ml.setWorkerUrl(workerUrl);
      const instance = new ml.Map({ container: container.current, center: [-95.3698, 29.7604], zoom: 10,
        style: 'https://tiles.openfreemap.org/styles/liberty' });
      map.current = instance;
      instance.addControl(new ml.NavigationControl());
      instance.on('error', () => setError('Some map resources could not load. Missing layers do not mean conditions are clear.'));
      instance.on('load', () => {
        for (const [id, collection] of Object.entries(buildOrionMapData(latest.current))) {
          instance.addSource(id, { type: 'geojson', data: collection as FeatureCollection });
        }
        instance.addLayer({ id: 'warning-fill', type: 'fill', source: 'zones', paint: { 'fill-color': ['get', 'color'], 'fill-opacity': .23 } });
        instance.addLayer({ id: 'warning-outline', type: 'line', source: 'zones', paint: { 'line-color': ['get', 'color'], 'line-width': 1 } });
        instance.addLayer({ id: 'route-lines', type: 'line', source: 'routes', paint: { 'line-color': ['get', 'color'],
          'line-width': ['case', ['get', 'selected'], 6, 3], 'line-opacity': ['case', ['get', 'selected'], 1, .4] } });
        instance.addLayer({ id: 'flagged-lines', type: 'line', source: 'flagged', filter: ['==', ['get', 'selected'], true],
          paint: { 'line-color': '#f5b53c', 'line-width': 8, 'line-dasharray': [1, 2] } });
        for (const id of ['gauges', 'reports', 'endpoints']) {
          instance.addLayer({ id: id + '-points', type: 'circle', source: id, paint: {
            'circle-radius': id === 'endpoints' ? 8 : 5, 'circle-color': id === 'gauges' ? ['get', 'color'] : id === 'reports' ? '#ec835a' : '#19BCA0',
            'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2,
          } });
        }
        for (const id of ['warning-fill', 'flagged-lines', 'gauges-points', 'reports-points', 'endpoints-points']) {
          instance.on('click', id, e => {
            const p = e.features?.[0]?.properties;
            if (!p) return;
            const label = id === 'warning-fill' ? p.event + ' · ' + p.severity + ' · source: ' + p.source + (p.source === 'nws'
              ? '. NWS warnings are precautionary regions, not confirmed flooded roads.' : '. Recorded hazard footprint; this does not verify individual road closures.')
              : id === 'flagged-lines' ? p.event + ' · evidence: ' + p.evidence + ' · source: ' + p.source
              : id === 'reports-points' ? p.name + ' · reported depth: ' + (p.depth ?? 'unknown') + ' inches · ' + p.reported + '. Conditions may have changed.'
              : id === 'gauges-points' ? p.name + ' · ' + p.status + ' · ' + (p.current ?? 'unknown') + ' ft. A gauge is not a road-closure report.' : p.role;
            const content = document.createElement('div'); content.textContent = label;
            new ml.Popup().setLngLat(e.lngLat).setDOMContent(content).addTo(instance);
          });
        }
        setReady(true);
      });
    }).catch(() => setError('Map could not initialize. Route details remain available below.'));
    return () => { disposed = true; map.current?.remove(); map.current = null; };
  }, [offline]);
  useEffect(() => {
    if (!ready || !map.current || offline) return;
    for (const [id, collection] of Object.entries(buildOrionMapData(data))) {
      (map.current.getSource(id) as GeoJSONSource)?.setData(collection as FeatureCollection);
    }
  }, [data, ready, offline]);
  useEffect(() => {
    if (!ready || !map.current || offline) return;
    const route = data.routes.find(r => r.id === data.selectedId);
    const coordinates = route?.geometry.coordinates ?? [data.origin, data.destination].flatMap(p => p ? [[p.lon, p.lat]] : []);
    if (!coordinates.length) return;
    const bounds = coordinates.reduce((b, p) => [Math.min(b[0], p[0]), Math.min(b[1], p[1]), Math.max(b[2], p[0]), Math.max(b[3], p[1])], [Infinity, Infinity, -Infinity, -Infinity]);
    map.current.fitBounds([[bounds[0], bounds[1]], [bounds[2], bounds[3]]], { padding: 45, maxZoom: 15, duration: 0 });
  }, [ready, offline, data.selectedId, data.origin?.lat, data.origin?.lon, data.destination?.lat, data.destination?.lon]);
  return <div className="orion-map-wrap">
    <div ref={container} className="map-canvas orion-map" aria-label="Orion flood warnings and provider-generated routes" />
    <p role="status">{offline ? 'Offline preview: map and live routing unavailable. No tiles or routes have been downloaded.'
      : error || (!ready ? 'Loading map…' : 'Shading: NWS warning regions or recorded hazard footprints (click for source). NWS warnings are not confirmed floodwater. Reports are dated observations.')}</p>
  </div>;
}
