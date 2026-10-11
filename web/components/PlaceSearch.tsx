"use client";

import { useEffect, useRef, useState } from "react";
import type { LatLng, Place } from "@orion/shared";
import { api } from "../lib/client";

interface Props {
  label: string;
  value: string;
  onPick: (place: Place) => void;
  onEdit?: () => void;
  onUseLocation?: (at: LatLng) => void;
}

export default function PlaceSearch({ label, value, onPick, onUseLocation, onEdit }: Props) {
  const [query, setQuery] = useState(value);
  const [results, setResults] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => setQuery(value), [value]);

  // Debounced so typing does not spend the ORS rate limit.
  useEffect(() => {
    if (query.length < 3 || query === value) {
      setResults([]);
      setBusy(false);
      return;
    }
    let active = true;
    const timer = setTimeout(async () => {
      setBusy(true);
      try {
        const places = await api.geocode(query);
        if (active) { setResults(places); setOpen(true); }
      } catch {
        if (active) setResults([]);
      } finally {
        if (active) setBusy(false);
      }
    }, 300);
    return () => { active = false; clearTimeout(timer); };
  }, [query, value]);

  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);

  return (
    <div ref={box} className="relative">
      <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide" style={{ color: "var(--text-secondary)" }}>
        {label}
      </label>
      <div className="flex gap-1.5">
        <input
          value={query}
          onChange={(e) => { setQuery(e.target.value); onEdit?.(); }}
          onFocus={() => results.length && setOpen(true)}
          placeholder="Search an address or place"
          className="w-full rounded-lg px-2.5 py-2 text-sm outline-none"
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            color: "var(--text-primary)",
          }}
        />
        {onUseLocation && (
          <button
            type="button"
            title="Use my location"
            onClick={() =>
              navigator.geolocation?.getCurrentPosition(
                (pos) =>
                  onUseLocation({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
                () => alert("Could not get your location."),
              )
            }
            className="shrink-0 rounded-lg px-2.5 text-sm"
            style={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              color: "var(--text-secondary)",
            }}
          >
            ⌖
          </button>
        )}
      </div>

      {busy && (
        <span className="absolute right-12 top-[30px] text-[10px]" style={{ color: "var(--muted)" }}>
          …
        </span>
      )}

      {open && results.length > 0 && (
        <ul
          className="absolute z-20 mt-1 max-h-56 w-full overflow-auto rounded-lg py-1 shadow-xl"
          style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
        >
          {results.map((p, i) => (
            <li key={`${p.lat},${p.lon},${i}`}>
              <button
                type="button"
                onClick={() => {
                  onPick(p);
                  setQuery(p.name);
                  setOpen(false);
                }}
                className="block w-full px-2.5 py-1.5 text-left text-xs hover:opacity-70"
                style={{ color: "var(--text-primary)" }}
              >
                {p.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
