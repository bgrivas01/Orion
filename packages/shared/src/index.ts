/**
 * Shared contract and helpers for the Orion web and mobile clients.
 *
 * `api.ts` is generated from the backend's OpenAPI schema — never hand-edit it.
 * Regenerate with `npm run generate` (backend running on :8000).
 *
 * Everything else in here is logic both clients must agree on: how a risk score
 * is labelled and coloured, and how distances and times are written.
 */

import type { components } from "./api";

type S = components["schemas"];

export type LatLng = S["LatLng"];
export type Place = S["Place"];
export type LineString = S["LineString"];
export type MultiPolygon = S["MultiPolygon"];

export type RouteRequest = S["RouteRequest"];
export type RouteResponse = S["RouteResponse"];
export type RouteCandidate = S["RouteCandidate"];
export type RiskBreakdown = S["RiskBreakdown"];
export type FlaggedSegment = S["FlaggedSegment"];
export type ElevationPoint = S["ElevationPoint"];

export type FloodZone = S["FloodZone"];
export type FloodZoneSummary = S["FloodZoneSummary"];
export type FloodReport = S["FloodReport"];
export type Gauge = S["Gauge"];
export type GaugeReading = S["GaugeReading"];

export type AlertCheckResponse = S["AlertCheckResponse"];
export type HealthResponse = S["HealthResponse"];

export type RiskBand = S["RiskBand"];
export type RouteLabel = S["RouteLabel"];
export type RoutePreference = S["RoutePreference"];
export type FloodSeverity = S["FloodSeverity"];
export type GaugeStatus = S["GaugeStatus"];
export type GaugeTrend = S["GaugeTrend"];

/* -------------------------------------------------------------------------- */
/* Presentation of risk                                                        */
/* -------------------------------------------------------------------------- */

export interface BandStyle {
  label: string;
  /** Why this band was assigned, in words a driver would use. */
  blurb: string;
  /** Status-palette hex for chips, strokes and map lines. Never used for text. */
  mark: string;
  /** Tint for card backgrounds. */
  bg: string;
  /** A glyph, so the band never depends on colour alone. */
  icon: string;
}

/**
 * Risk bands use the reserved status palette (good / warning / critical), never
 * categorical series colours. Each ships with an icon and a label because two of
 * these hexes sit below 3:1 on a light surface — colour alone is not allowed to
 * carry the meaning.
 */
export const RISK_BANDS: Record<RiskBand, BandStyle> = {
  safe: {
    label: "Safe",
    blurb: "Clear of active flooding and low-lying ground.",
    mark: "#0ca30c",
    bg: "rgba(12, 163, 12, 0.10)",
    icon: "✓",
  },
  caution: {
    label: "Caution",
    blurb: "Passes near flooding or through low ground. Conditions can change.",
    mark: "#fab219",
    bg: "rgba(250, 178, 25, 0.14)",
    icon: "!",
  },
  dangerous: {
    label: "Dangerous",
    blurb: "Crosses active floodwater. Do not drive this route.",
    mark: "#d03b3b",
    bg: "rgba(208, 59, 59, 0.12)",
    icon: "✕",
  },
};

/**
 * Chart tokens, validated against both surfaces with the palette validator.
 * Categorical slots 1-4 in fixed order; the adjacent-pair gate passes in both
 * modes at this ordering, so do not reorder them.
 */
export const VIZ = {
  light: {
    surface: "#fcfcfb",
    textPrimary: "#0b0b0b",
    textSecondary: "#52514e",
    muted: "#898781",
    grid: "#e1e0d9",
    axis: "#c3c2b7",
    series: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"],
    /** Single-series elevation line uses the sequential blue. */
    elevation: "#2a78d6",
    elevationFill: "rgba(42, 120, 214, 0.14)",
  },
  dark: {
    surface: "#1a1a19",
    textPrimary: "#ffffff",
    textSecondary: "#c3c2b7",
    muted: "#898781",
    grid: "#2c2c2a",
    axis: "#383835",
    series: ["#3987e5", "#d95926", "#199e70", "#c98500"],
    elevation: "#3987e5",
    elevationFill: "rgba(57, 135, 229, 0.18)",
  },
} as const;

export function bandStyle(band: RiskBand): BandStyle {
  return RISK_BANDS[band] ?? RISK_BANDS.caution;
}

/** The four scoring components, with their maximums, for a breakdown bar chart. */
export const ROUTE_LABELS: Record<RouteLabel, string> = {
  safest: "Safest",
  balanced: "Balanced",
  fastest: "Fastest",
};

/** Flood severity is a state, so it draws from the reserved status palette. */
export const SEVERITY_COLORS: Record<FloodSeverity, string> = {
  extreme: "#d03b3b",
  severe: "#d03b3b",
  moderate: "#ec835a",
  minor: "#fab219",
  unknown: "#898781",
};

export const GAUGE_STATUS_COLORS: Record<GaugeStatus, string> = {
  flood: "#d03b3b",
  action: "#fab219",
  normal: "#0ca30c",
  unknown: "#898781",
};

/** Paired with the colour so gauge state never relies on hue alone. */
export const GAUGE_STATUS_LABELS: Record<GaugeStatus, string> = {
  flood: "Above flood stage",
  action: "Approaching flood stage",
  normal: "Normal",
  unknown: "No recent reading",
};

export const TREND_ARROWS: Record<GaugeTrend, string> = {
  rising: "\u2191",
  falling: "\u2193",
  steady: "\u2192",
  unknown: "\u00b7",
};

export const RISK_COMPONENTS: Array<{
  key: keyof Omit<RiskBreakdown, "total">;
  label: string;
  max: number;
  explain: string;
}> = [
  {
    key: "flood_exposure",
    label: "Flood exposure",
    max: 50,
    explain: "Distance this route travels inside an active flood zone.",
  },
  {
    key: "low_lying",
    label: "Low-lying terrain",
    max: 25,
    explain: "Dips where the road sits below the ground around it, so water collects.",
  },
  {
    key: "gauge_proximity",
    label: "River gauges",
    max: 20,
    explain: "Nearby river gauges currently at or above flood stage.",
  },
  {
    key: "approach_margin",
    label: "Close approach",
    max: 5,
    explain: "How closely the route skirts the edge of a flood zone.",
  },
];

/* -------------------------------------------------------------------------- */
/* Formatting                                                                  */
/* -------------------------------------------------------------------------- */

export function formatDistance(meters: number, imperial = true): string {
  if (imperial) {
    const miles = meters / 1609.344;
    return miles < 0.2 ? `${Math.round(meters * 3.28084)} ft` : `${miles.toFixed(1)} mi`;
  }
  return meters < 950 ? `${Math.round(meters)} m` : `${(meters / 1000).toFixed(1)} km`;
}

export function formatDuration(seconds: number): string {
  const total = Math.round(seconds / 60);
  if (total < 60) return `${total} min`;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return m ? `${h} hr ${m} min` : `${h} hr`;
}

/** Signed minutes relative to the quickest candidate, e.g. "+8 min". */
export function formatDelta(seconds: number, baseline: number): string {
  const delta = Math.round((seconds - baseline) / 60);
  if (delta === 0) return "fastest";
  return delta > 0 ? `+${delta} min` : `${delta} min`;
}

export function formatElevation(meters: number | null | undefined): string {
  if (meters === null || meters === undefined) return "—";
  return `${Math.round(meters * 3.28084)} ft`;
}

/** The quickest candidate's duration, used as the baseline for deltas. */
export function quickestDuration(routes: RouteCandidate[]): number {
  return routes.reduce((min, r) => Math.min(min, r.duration_s), Infinity);
}

/**
 * Order routes for display: recommended first, then by risk.
 * The backend already sorts by risk, so this only lifts the recommendation.
 */
export function orderRoutes(res: RouteResponse): RouteCandidate[] {
  const routes = [...res.routes];
  const idx = routes.findIndex((r) => r.id === res.recommended_id);
  if (idx > 0) routes.unshift(routes.splice(idx, 1)[0]);
  return routes;
}

export function totalFloodedMeters(route: RouteCandidate): number {
  return (route.flagged_segments ?? []).reduce((sum, s) => sum + s.length_m, 0);
}

/* -------------------------------------------------------------------------- */
/* API client                                                                  */
/* -------------------------------------------------------------------------- */

export class OrionApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "OrionApiError";
  }
}

export function createClient(baseUrl: string) {
  const base = baseUrl.replace(/\/$/, "");

  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${base}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
    if (!res.ok) {
      let detail = `Request failed (${res.status})`;
      try {
        const body = await res.json();
        if (body?.detail) detail = String(body.detail);
      } catch {
        /* keep the status-based message */
      }
      throw new OrionApiError(detail, res.status);
    }
    return (await res.json()) as T;
  }

  return {
    health: () => request<HealthResponse>("/health"),

    planRoutes: (body: RouteRequest) =>
      request<RouteResponse>("/api/routes", {
        method: "POST",
        body: JSON.stringify(body),
      }),

    geocode: (q: string) => request<Place[]>(`/api/geocode?q=${encodeURIComponent(q)}`),

    floodZones: (bbox?: string) =>
      request<FloodZone[]>(`/api/flood-zones${bbox ? `?bbox=${encodeURIComponent(bbox)}` : ""}`),

    floodReports: (limit = 100) =>
      request<FloodReport[]>(`/api/flood-reports?limit=${limit}`),

    gauges: (bbox?: string) =>
      request<Gauge[]>(`/api/gauges${bbox ? `?bbox=${encodeURIComponent(bbox)}` : ""}`),

    checkAlerts: (lat: number, lon: number, radiusM = 5000) =>
      request<AlertCheckResponse>(
        `/api/alerts/check?lat=${lat}&lon=${lon}&radius_m=${radiusM}`,
      ),

    subscribe: (body: {
      device_id: string;
      location: LatLng;
      radius_m?: number;
      active_route?: LineString | null;
    }) => request<{ status: string }>("/api/alerts/subscribe", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  };
}

export type OrionClient = ReturnType<typeof createClient>;
