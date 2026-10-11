import { useEffect, useState } from 'react';
import { type Place } from '@/lib/orion-api';
import { useOrion } from './orion-context';

export function OrionPlaceSearch({ label, value, onSelect }: {
  label: string; value: Place | null; onSelect: (place: Place | null) => void;
}) {
  const { client, routingAvailable } = useOrion();
  const [query, setQuery] = useState(value?.name ?? '');
  const [places, setPlaces] = useState<Place[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  useEffect(() => { if (value) setQuery(value.name); }, [value]);
  useEffect(() => {
    setPlaces([]); setError(''); setLoading(false);
    if (!routingAvailable || query.trim().length < 2 || query === value?.name) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const results = await client.geocode(query.trim(), controller.signal);
        if (!controller.signal.aborted) setPlaces(results);
      } catch (failure) {
        if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Address search failed.');
      } finally { if (!controller.signal.aborted) setLoading(false); }
    }, 300);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query, value?.name, client, routingAvailable]);
  return <div className="orion-place-search">
    <label className="text-xs font-semibold">{label}
      <input value={query} disabled={!routingAvailable} autoComplete="off" placeholder="Search an address or public-road entrance"
        onChange={event => { setQuery(event.target.value); onSelect(null); }}
        className="w-full min-h-12 rounded-xl border bg-card px-3 text-sm mt-2" />
    </label>
    {loading && <p role="status" className="text-xs">Searching Orion geocoding…</p>}
    {error && <p role="alert" className="text-xs text-warning">{error}</p>}
    {places.length > 0 && <ul aria-label={`${label} search results`} className="orion-search-results">
      {places.map((place, index) => <li key={`${place.lon}:${place.lat}:${index}`}>
        <button type="button" className="w-full min-h-12 text-left p-3" onClick={() => { onSelect(place); setQuery(place.name); setPlaces([]); }}>
          {place.name}{place.region && <span className="block text-xs text-muted-foreground">{place.region}</span>}
        </button>
      </li>)}
    </ul>}
  </div>;
}
