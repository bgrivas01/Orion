"use client";

import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import type { Map as MlMap, MapLayerMouseEvent } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  GAUGE_STATUS_COLORS,
  GAUGE_STATUS_LABELS,
  SEVERITY_COLORS,
  bandStyle,
  formatDistance,
  type FloodZone,
  type FloodReport,
  type Gauge,
  type LatLng,
  type RouteCandidate,
} from "@orion/shared";

// OpenFreeMap serves vector tiles with no key and no signup — one less thing to
// break on demo day than a Mapbox token.
const STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";

const EMPTY = { type: "FeatureCollection", features: [] } as const;

interface Props {
  routes: RouteCandidate[];
  selectedId: string | null;
  floodZones: FloodZone[];
  gauges: Gauge[];
  floodReports: FloodReport[];
  origin: LatLng | null;
  destination: LatLng | null;
  onSelect: (id: string) => void;
}

export default function MapView({
  routes,
  selectedId,
  floodZones,
  gauges,
  floodReports,
  origin,
  destination,
  onSelect,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MlMap | null>(null);
  const ready = useRef(false);
  const fitted = useRef<string | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  /* ---------------------------------------------------------------- setup -- */
  useEffect(() => {
    if (!container.current || map.current) return;

    // MapLibre derives its default worker URL from import.meta.url, which
    // Next.js can relocate into a chunk. The predev/prebuild script serves
    // the matching installed worker at a stable same-origin URL instead.
    maplibregl.setWorkerUrl("/maplibre-gl-worker.mjs");

    const m = new maplibregl.Map({
      container: container.current,
      style: STYLE_URL,
      center: [-95.3698, 29.7604],
      zoom: 9.5,
      attributionControl: { compact: true },
    });
    map.current = m;

    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.addControl(new maplibregl.GeolocateControl({ trackUserLocation: false }), "top-right");

    m.on("load", () => {
      // Flood polygons sit under the routes so a flagged route stays readable.
      m.addSource("flood-zones", { type: "geojson", data: EMPTY as never });
      m.addLayer({
        id: "flood-fill",
        type: "fill",
        source: "flood-zones",
        paint: { "fill-color": ["get", "color"], "fill-opacity": 0.22 },
      });
      m.addLayer({
        id: "flood-outline",
        type: "line",
        source: "flood-zones",
        paint: { "line-color": ["get", "color"], "line-width": 1.5, "line-opacity": 0.9 },
      });

      m.addSource("routes", { type: "geojson", data: EMPTY as never });
      // A surface-coloured casing underneath keeps overlapping routes separable.
      m.addLayer({
        id: "route-casing",
        type: "line",
        source: "routes",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "#fcfcfb",
          "line-width": ["case", ["get", "selected"], 9, 6],
          "line-opacity": ["case", ["get", "selected"], 0.9, 0.5],
        },
      });
      m.addLayer({
        id: "route-line",
        type: "line",
        source: "routes",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["get", "color"],
          "line-width": ["case", ["get", "selected"], 5, 3],
          "line-opacity": ["case", ["get", "selected"], 1, 0.45],
        },
      });

      // Flagged stretches draw on top, dashed, to show warning / hazard overlap
      // survives being the same colour family as the route.
      m.addSource("flagged", { type: "geojson", data: EMPTY as never });
      m.addLayer({
        id: "flagged-line",
        type: "line",
        source: "flagged",
        layout: { "line-cap": "butt" },
        paint: {
          "line-color": "#d03b3b",
          "line-width": 7,
          "line-opacity": ["case", ["get", "selected"], 0.95, 0.3],
          "line-dasharray": [1.5, 0.8],
        },
      });

      m.addSource("gauges", { type: "geojson", data: EMPTY as never });
      m.addLayer({
        id: "gauge-dot",
        type: "circle",
        source: "gauges",
        paint: {
          "circle-radius": ["case", ["get", "alerting"], 7, 5],
          "circle-color": ["get", "color"],
          "circle-stroke-width": 2,
          "circle-stroke-color": "#fcfcfb",
        },
      });

      m.addSource("endpoints", { type: "geojson", data: EMPTY as never });
      m.addLayer({
        id: "endpoint-dot",
        type: "circle",
        source: "endpoints",
        paint: {
          "circle-radius": 7,
          "circle-color": ["case", ["==", ["get", "role"], "origin"], "#0b0b0b", "#2a78d6"],
          "circle-stroke-width": 3,
          "circle-stroke-color": "#fcfcfb",
        },
      });

      ready.current = true;
      m.resize();
    });

    // Clicking a route selects it; the hit target is the fat casing, not the line.
    m.on("click", "route-casing", (e: MapLayerMouseEvent) => {
      const id = e.features?.[0]?.properties?.id;
      if (typeof id === "string") onSelectRef.current(id);
    });
    m.on("mouseenter", "route-casing", () => {
      m.getCanvas().style.cursor = "pointer";
    });
    m.on("mouseleave", "route-casing", () => {
      m.getCanvas().style.cursor = "";
    });

    const popup = new maplibregl.Popup({ closeButton: false, offset: 12 });
    m.on("mouseenter", "gauge-dot", (e: MapLayerMouseEvent) => {
      const p = e.features?.[0]?.properties;
      if (!p) return;
      m.getCanvas().style.cursor = "pointer";
      popup
        .setLngLat((e.features![0].geometry as GeoJSON.Point).coordinates as [number, number])
        .setHTML(
          `<strong>${escapeHtml(String(p.name))}</strong><br/>` +
            `${escapeHtml(String(p.statusLabel))}<br/>` +
            `<span class="tabular">${p.current ?? "—"} ft</span>` +
            (p.flood ? ` · flood stage <span class="tabular">${p.flood} ft</span>` : ""),
        )
        .addTo(m);
    });
    m.on("mouseleave", "gauge-dot", () => {
      m.getCanvas().style.cursor = "";
      popup.remove();
    });

    m.on("mouseenter", "flood-fill", (e: MapLayerMouseEvent) => {
      const p = e.features?.[0]?.properties;
      if (!p) return;
      popup
        .setLngLat(e.lngLat)
        .setHTML(
          `<strong>${escapeHtml(String(p.event))}</strong>` +
            (p.headline ? `<br/>${escapeHtml(String(p.headline))}` : "") +
            `<br/>Severity: ${escapeHtml(String(p.severity ?? "unknown"))}` +
            (p.source === "nws"
              ? "<br/>NWS alert region, not confirmed floodwater on roads."
              : "<br/>Recorded hazard area; crossing routes are excluded. Check current road closures."),
        )
        .addTo(m);
    });
    m.on("mouseleave", "flood-fill", () => popup.remove());

    return () => {
      m.remove();
      map.current = null;
      ready.current = false;
    };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const markers = floodReports.flatMap((report) => {
      if (report.latitude == null || report.longitude == null) return [];
      const element = document.createElement("div");
      element.style.cssText = "width:14px;height:14px;background:#eb6834;border:2px solid #fcfcfb;border-radius:2px;";
      const details = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = report.location_name || "Flood report";
      details.append(title);
      const observation = document.createElement("p");
      observation.textContent = `${report.severity || "Severity unknown"} · ${
        report.water_depth_inches == null ? "Depth unknown" : `${report.water_depth_inches} inches`}`;
      details.append(observation);
      if (report.description) {
        const description = document.createElement("p");
        description.textContent = report.description;
        details.append(description);
      }
      const time = document.createElement("p");
      time.textContent = report.reported_at
        ? new Date(report.reported_at).toLocaleString() : "Report time unknown";
      details.append(time);
      const popup = new maplibregl.Popup({ offset: 12 }).setDOMContent(details);
      const marker = new maplibregl.Marker({ element })
        .setLngLat([report.longitude, report.latitude]).setPopup(popup).addTo(m);
      return [{ marker, popup }];
    });
    return () => markers.forEach(({ marker, popup }) => { popup.remove(); marker.remove(); });
  }, [floodReports]);

  /* ------------------------------------------------------------ flood data -- */
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const apply = () => {
      const src = m.getSource("flood-zones") as maplibregl.GeoJSONSource | undefined;
      src?.setData({
        type: "FeatureCollection",
        features: floodZones.map((z) => ({
          type: "Feature" as const,
          geometry: z.geometry as GeoJSON.MultiPolygon,
          properties: {
            id: z.id,
            source: z.source,
            severity: z.severity,
            event: z.event,
            headline: z.headline ?? "",
            color: SEVERITY_COLORS[z.severity] ?? SEVERITY_COLORS.unknown,
          },
        })),
      });
    };
    if (ready.current) apply();
    else m.once("idle", apply);
  }, [floodZones]);

  /* ----------------------------------------------------------- gauge data -- */
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const apply = () => {
      const src = m.getSource("gauges") as maplibregl.GeoJSONSource | undefined;
      src?.setData({
        type: "FeatureCollection",
        features: gauges.map((g) => ({
          type: "Feature" as const,
          geometry: { type: "Point" as const, coordinates: [g.lon, g.lat] },
          properties: {
            name: g.name,
            statusLabel: GAUGE_STATUS_LABELS[g.status] ?? "",
            color: GAUGE_STATUS_COLORS[g.status] ?? GAUGE_STATUS_COLORS.unknown,
            alerting: g.status === "flood" || g.status === "action",
            current: g.current_ft,
            flood: g.flood_stage_ft,
          },
        })),
      });
    };
    if (ready.current) apply();
    else m.once("idle", apply);
  }, [gauges]);

  /* ---------------------------------------------------------- route data --- */
  useEffect(() => {
    const m = map.current;
    if (!m) return;

    const apply = () => {
      const routeSrc = m.getSource("routes") as maplibregl.GeoJSONSource | undefined;
      const flaggedSrc = m.getSource("flagged") as maplibregl.GeoJSONSource | undefined;
      const endSrc = m.getSource("endpoints") as maplibregl.GeoJSONSource | undefined;

      // Draw the selected route last so it wins the z-order.
      const ordered = [...routes].sort((a, b) =>
        a.id === selectedId ? 1 : b.id === selectedId ? -1 : 0,
      );

      routeSrc?.setData({
        type: "FeatureCollection",
        features: ordered.map((r) => ({
          type: "Feature" as const,
          geometry: { type: "LineString" as const, coordinates: strip(r.geometry.coordinates) },
          properties: {
            id: r.id,
            selected: r.id === selectedId,
            color: bandStyle(r.risk_band).mark,
            label: r.label,
          },
        })),
      });

      flaggedSrc?.setData({
        type: "FeatureCollection",
        features: ordered.flatMap((r) =>
          (r.flagged_segments ?? []).map((s, i) => ({
            type: "Feature" as const,
            geometry: { type: "LineString" as const, coordinates: strip(s.geometry.coordinates) },
            properties: {
              id: `${r.id}-flag-${i}`,
              selected: r.id === selectedId,
              event: s.event,
              length: formatDistance(s.length_m),
            },
          })),
        ),
      });

      endSrc?.setData({
        type: "FeatureCollection",
        features: [
          ...(origin
            ? [
                {
                  type: "Feature" as const,
                  geometry: { type: "Point" as const, coordinates: [origin.lon, origin.lat] },
                  properties: { role: "origin" },
                },
              ]
            : []),
          ...(destination
            ? [
                {
                  type: "Feature" as const,
                  geometry: {
                    type: "Point" as const,
                    coordinates: [destination.lon, destination.lat],
                  },
                  properties: { role: "destination" },
                },
              ]
            : []),
        ],
      });

      // Fit once per result set, not on every selection change.
      const key = routes.map((r) => r.id).join("|");
      if (routes.length && fitted.current !== key) {
        const bounds = new maplibregl.LngLatBounds();
        routes.forEach((r) =>
          r.geometry.coordinates.forEach((c) => bounds.extend([c[0], c[1]])),
        );
        m.fitBounds(bounds, { padding: 64, duration: 700, maxZoom: 13 });
        fitted.current = key;
      }
    };

    if (ready.current) apply();
    else m.once("idle", apply);
  }, [routes, selectedId, origin, destination]);

  return <div ref={container} className="h-full w-full" />;
}

/** Drop the elevation ordinate — MapLibre only needs [lon, lat]. */
function strip(coords: number[][]): number[][] {
  return coords.map((c) => [c[0], c[1]]);
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c,
  );
}
