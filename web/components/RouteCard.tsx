"use client";

import {
  ROUTE_LABELS,
  bandStyle,
  formatDelta,
  formatDistance,
  formatDuration,
  formatElevation,
  totalFloodedMeters,
  type RouteCandidate,
} from "@orion/shared";
import ElevationProfile from "./ElevationProfile";
import RiskBreakdown from "./RiskBreakdown";

interface Props {
  route: RouteCandidate;
  selected: boolean;
  recommended: boolean;
  quickest: number;
  onSelect: () => void;
}

export default function RouteCard({ route, selected, recommended, quickest, onSelect }: Props) {
  const band = bandStyle(route.risk_band);
  const floodedM = totalFloodedMeters(route);

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className="w-full rounded-xl p-3 text-left transition-shadow"
      style={{
        background: "var(--surface)",
        border: `1px solid ${selected ? band.mark : "var(--border)"}`,
        boxShadow: selected ? `0 0 0 1px ${band.mark}` : "none",
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
            {ROUTE_LABELS[route.label]}
          </span>
          {recommended && (
            <span
              className="rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
              style={{ background: "var(--grid)", color: "var(--text-secondary)" }}
            >
              Recommended
            </span>
          )}
        </div>

        {/* Icon + text, so the band never relies on colour alone. */}
        <span
          className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold"
          style={{ background: band.bg, color: "var(--text-primary)" }}
        >
          <span aria-hidden style={{ color: band.mark }}>
            {band.icon}
          </span>
          {band.label}
        </span>
      </div>

      <div className="mt-2 flex items-baseline gap-3 text-sm" style={{ color: "var(--text-primary)" }}>
        <span className="tabular font-medium">{formatDuration(route.duration_s)}</span>
        <span className="tabular" style={{ color: "var(--text-secondary)" }}>
          {formatDistance(route.distance_m)}
        </span>
        <span className="tabular text-xs" style={{ color: "var(--muted)" }}>
          {formatDelta(route.duration_s, quickest)}
        </span>
      </div>

      <p className="mt-1 text-[11px]" style={{ color: "var(--text-secondary)" }}>
        {band.blurb}
      </p>

      {floodedM > 0 && (
        <p className="mt-1.5 text-[11px] font-medium" style={{ color: "var(--status-critical)" }}>
          ✕ {formatDistance(floodedM)} through active floodwater
        </p>
      )}

      {route.avoidance_verified && route.avoidance_requested && (
        <p className="mt-1.5 text-[11px]" style={{ color: "var(--text-secondary)" }}>
          ✓ Verified clear of every active flood zone
        </p>
      )}

      <div className="mt-2 flex gap-3 text-[11px]" style={{ color: "var(--muted)" }}>
        <span className="tabular">
          low {formatElevation(route.min_elevation_m)}
        </span>
        <span className="tabular">
          high {formatElevation(route.max_elevation_m)}
        </span>
      </div>

      {selected && (
        <div className="mt-3 space-y-3 border-t pt-3" style={{ borderColor: "var(--border)" }}>
          <RiskBreakdown breakdown={route.risk_breakdown} />

          <div>
            <h4
              className="mb-1 text-[11px] font-semibold uppercase tracking-wide"
              style={{ color: "var(--text-secondary)" }}
            >
              Elevation along the route
            </h4>
            <ElevationProfile route={route} />
          </div>

          {route.warnings.length > 0 && (
            <ul className="space-y-1">
              {route.warnings.map((w, i) => (
                <li key={i} className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                  • {w}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </button>
  );
}
