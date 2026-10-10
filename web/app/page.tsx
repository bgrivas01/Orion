"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  orderRoutes,
  quickestDuration,
  type FloodZone,
  type FloodReport,
  type Gauge,
  type LatLng,
  type Place,
  type RoutePreference,
  type RouteResponse,
} from "@orion/shared";
import PlaceSearch from "../components/PlaceSearch";
import RouteCard from "../components/RouteCard";
import FloodReports from "../components/FloodReports";
import { api } from "../lib/client";

// MapLibre touches `window` on import, so it cannot be server-rendered.
const MapView = dynamic(() => import("../components/MapView"), {
  ssr: false,
  loading: () => <div className="h-full w-full" style={{ background: "var(--grid)" }} />,
});

const PREFERENCES: Array<{ value: RoutePreference; label: string }> = [
  { value: "safest", label: "Safest" },
  { value: "balanced", label: "Balanced" },
  { value: "fastest", label: "Fastest" },
];

export default function Home() {
  const [origin, setOrigin] = useState<LatLng | null>(null);
  const [destination, setDestination] = useState<LatLng | null>(null);
  const [originLabel, setOriginLabel] = useState("");
  const [destLabel, setDestLabel] = useState("");
  const [preference, setPreference] = useState<RoutePreference>("safest");

  const [result, setResult] = useState<RouteResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [floodZones, setFloodZones] = useState<FloodZone[]>([]);
  const [gauges, setGauges] = useState<Gauge[]>([]);
  const [floodReports, setFloodReports] = useState<FloodReport[]>([]);
  const [reportsLoading, setReportsLoading] = useState(true);
  const [reportsError, setReportsError] = useState<string | null>(null);
  const reportsRequest = useRef(0);

  const refreshReports = useCallback(async () => {
    const request = ++reportsRequest.current;
    setReportsLoading(true);
    try {
      const reports = await api.floodReports();
      if (request !== reportsRequest.current) return;
      setFloodReports(reports);
      setReportsError(null);
    } catch (e) {
      if (request !== reportsRequest.current) return;
      setFloodReports([]);
      setReportsError(e instanceof Error ? e.message : "Could not load flood reports.");
    } finally {
      if (request === reportsRequest.current) setReportsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshReports();
    const timer = window.setInterval(() => void refreshReports(), 60_000);
    return () => {
      window.clearInterval(timer);
      reportsRequest.current++;
    };
  }, [refreshReports]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Conditions load straight away — the map should show flooding before the
  // user has typed anything.
  useEffect(() => {
    api.floodZones().then(setFloodZones).catch(() => setFloodZones([]));
    api.gauges().then(setGauges).catch(() => setGauges([]));
  }, []);

  const plan = useCallback(async () => {
    if (!origin || !destination) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.planRoutes({ origin, destination, preference, profile: "driving-car" });
      setResult(res);
      setSelectedId(res.recommended_id ?? res.routes[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not plan a route.");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, [origin, destination, preference]);

  const routes = result ? orderRoutes(result) : [];
  const quickest = routes.length ? quickestDuration(routes) : 0;
  const alerting = gauges.filter((g) => g.status === "flood" || g.status === "action").length;

  const pickOrigin = (p: Place) => {
    setOrigin({ lat: p.lat, lon: p.lon });
    setOriginLabel(p.name);
  };
  const pickDestination = (p: Place) => {
    setDestination({ lat: p.lat, lon: p.lon });
    setDestLabel(p.name);
  };

  return (
    <main className="flex h-screen flex-col lg:flex-row">
      {/* ----------------------------------------------------------- panel -- */}
      <aside
        className="order-2 flex w-full shrink-0 flex-col overflow-y-auto lg:order-1 lg:h-full lg:w-[380px]"
        style={{ background: "var(--page)", borderRight: "1px solid var(--border)" }}
      >
        <header className="px-4 pb-3 pt-4">
          <h1 className="text-lg font-semibold tracking-tight" style={{ color: "var(--text-primary)" }}>
            Orion
          </h1>
          <p className="mt-0.5 text-xs" style={{ color: "var(--text-secondary)" }}>
            The safest way there, not just the fastest.
          </p>

          <div className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
            <span
              className="rounded-full px-2 py-0.5"
              style={{
                background: floodZones.length ? "rgba(208, 59, 59, 0.12)" : "var(--grid)",
                color: "var(--text-primary)",
              }}
            >
              {floodZones.length
                ? `${floodZones.length} active flood zone${floodZones.length === 1 ? "" : "s"}`
                : "No active flood zones"}
            </span>
            {alerting > 0 && (
              <span
                className="rounded-full px-2 py-0.5"
                style={{ background: "rgba(250, 178, 25, 0.16)", color: "var(--text-primary)" }}
              >
                {alerting} gauge{alerting === 1 ? "" : "s"} rising
              </span>
            )}
          </div>
        </header>

        <div className="space-y-3 px-4">
          <PlaceSearch
            label="From"
            value={originLabel}
            onPick={pickOrigin}
            onUseLocation={(at) => {
              setOrigin(at);
              setOriginLabel("My location");
            }}
          />
          <PlaceSearch label="To" value={destLabel} onPick={pickDestination} />

          <div>
            <span
              className="mb-1 block text-[11px] font-medium uppercase tracking-wide"
              style={{ color: "var(--text-secondary)" }}
            >
              Priority
            </span>
            <div className="flex gap-1" role="group">
              {PREFERENCES.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  onClick={() => setPreference(p.value)}
                  aria-pressed={preference === p.value}
                  className="flex-1 rounded-lg px-2 py-1.5 text-xs font-medium"
                  style={{
                    background: preference === p.value ? "var(--text-primary)" : "var(--surface)",
                    color: preference === p.value ? "var(--surface)" : "var(--text-secondary)",
                    border: "1px solid var(--border)",
                  }}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          <button
            type="button"
            onClick={plan}
            disabled={!origin || !destination || loading}
            className="w-full rounded-lg py-2.5 text-sm font-semibold disabled:opacity-40"
            style={{ background: "var(--series-1)", color: "#ffffff" }}
          >
            {loading ? "Checking conditions…" : "Find the safest route"}
          </button>

          {error && (
            <p
              className="rounded-lg p-2 text-xs"
              style={{ background: "rgba(208, 59, 59, 0.12)", color: "var(--text-primary)" }}
            >
              {error}
            </p>
          )}
        </div>

        {result && result.warnings.length > 0 && (
          <ul className="mt-3 space-y-1 px-4">
            {result.warnings.map((w, i) => (
              <li
                key={i}
                className="rounded-lg p-2 text-[11px]"
                style={{ background: "rgba(250, 178, 25, 0.14)", color: "var(--text-primary)" }}
              >
                {w}
              </li>
            ))}
          </ul>
        )}

        <div className="mt-3 space-y-2 px-4 pb-6">
          {routes.map((r) => (
            <RouteCard
              key={r.id}
              route={r}
              selected={r.id === selectedId}
              recommended={r.id === result?.recommended_id}
              quickest={quickest}
              onSelect={() => setSelectedId(r.id === selectedId ? null : r.id)}
            />
          ))}

          {!routes.length && !loading && (
            <p className="pt-2 text-xs" style={{ color: "var(--muted)" }}>
              Pick a start and a destination. Orion checks live flood warnings, river gauges and
              terrain, then ranks the options by how risky they actually are.
            </p>
          )}
        </div>
        <FloodReports reports={floodReports} loading={reportsLoading}
          error={reportsError} onRefresh={() => void refreshReports()} />
      </aside>

      {/* ------------------------------------------------------------- map -- */}
      <div className="order-1 h-[45vh] w-full lg:order-2 lg:h-full lg:flex-1">
        <MapView
          routes={routes}
          selectedId={selectedId}
          floodZones={floodZones}
          gauges={gauges}
          floodReports={floodReports}
          origin={origin}
          destination={destination}
          onSelect={setSelectedId}
        />
      </div>
    </main>
  );
}
