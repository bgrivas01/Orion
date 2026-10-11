"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { RouteCandidate } from "@orion/shared";

/**
 * Elevation along the route, with the flooded stretches marked.
 *
 * One series, so no legend — the heading names it. The flood shading is a
 * status colour, not a second series, and it is labelled in the caption so the
 * red is never the only thing carrying that meaning.
 */
export default function ElevationProfile({ route }: { route: RouteCandidate }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  const profile = route.elevation_profile ?? [];

  /** Which profile points sit inside a flagged (flooded) segment. */
  const flooded = useMemo(() => {
    const keys = new Set<string>();
    for (const seg of route.flagged_segments ?? []) {
      for (const c of seg.geometry.coordinates) {
        keys.add(`${c[0].toFixed(5)},${c[1].toFixed(5)}`);
      }
    }
    if (!keys.size) return new Set<number>();

    const out = new Set<number>();
    // elevation_profile is built from the 3D coordinates in order, so indices line up.
    const coords = route.geometry.coordinates.filter((c) => c.length > 2);
    coords.forEach((c, i) => {
      if (keys.has(`${c[0].toFixed(5)},${c[1].toFixed(5)}`)) out.add(i);
    });
    return out;
  }, [route]);

  if (profile.length < 2) {
    return (
      <p className="text-xs" style={{ color: "var(--muted)" }}>
        No elevation data for this route.
      </p>
    );
  }

  const H = 132;
  const PAD = { top: 10, right: 8, bottom: 22, left: 38 };
  const W = Math.max(width, 240);
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const feet = profile.map((p) => p.elevation_m * 3.28084);
  const miles = profile.map((p) => p.distance_m / 1609.344);

  const minFt = Math.min(...feet);
  const maxFt = Math.max(...feet);
  // Pad the band so a flat route does not render as a line on the axis.
  const span = Math.max(maxFt - minFt, 10);
  const lo = minFt - span * 0.15;
  const hi = maxFt + span * 0.15;
  const totalMi = miles[miles.length - 1] || 1;

  const x = (i: number) => PAD.left + (miles[i] / totalMi) * plotW;
  const y = (ft: number) => PAD.top + plotH - ((ft - lo) / (hi - lo)) * plotH;

  const line = feet.map((ft, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(ft).toFixed(1)}`).join("");
  const area = `${line}L${x(feet.length - 1).toFixed(1)},${(PAD.top + plotH).toFixed(1)}L${x(0).toFixed(1)},${(PAD.top + plotH).toFixed(1)}Z`;

  // Contiguous flooded runs become shaded bands.
  const bands: Array<[number, number]> = [];
  let start: number | null = null;
  for (let i = 0; i < feet.length; i++) {
    const wet = flooded.has(i);
    if (wet && start === null) start = i;
    if (!wet && start !== null) {
      bands.push([start, i - 1]);
      start = null;
    }
  }
  if (start !== null) bands.push([start, feet.length - 1]);

  const ticks = [lo + (hi - lo) * 0.1, (lo + hi) / 2, hi - (hi - lo) * 0.1];
  const lowestIdx = feet.indexOf(minFt);

  return (
    <div ref={wrap} className="relative w-full">
      <svg
        width={W}
        height={H}
        role="img"
        aria-label={`Elevation along the ${route.label} route, ${Math.round(minFt)} to ${Math.round(maxFt)} feet`}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const px = e.clientX - rect.left;
          const ratio = (px - PAD.left) / plotW;
          if (ratio < 0 || ratio > 1) return setHover(null);
          const targetMi = ratio * totalMi;
          let best = 0;
          let bestD = Infinity;
          miles.forEach((mi, i) => {
            const d = Math.abs(mi - targetMi);
            if (d < bestD) {
              bestD = d;
              best = i;
            }
          });
          setHover(best);
        }}
      >
        {/* Recessive gridlines */}
        {ticks.map((t, i) => (
          <line
            key={i}
            x1={PAD.left}
            x2={PAD.left + plotW}
            y1={y(t)}
            y2={y(t)}
            stroke="var(--grid)"
            strokeWidth={1}
          />
        ))}

        {/* Flooded stretches, behind the line */}
        {bands.map(([a, b], i) => (
          <rect
            key={i}
            x={x(a)}
            y={PAD.top}
            width={Math.max(x(b) - x(a), 2)}
            height={plotH}
            fill="#d03b3b"
            opacity={0.16}
          />
        ))}

        <path d={area} fill="var(--elevation-fill)" />
        <path d={line} fill="none" stroke="var(--elevation)" strokeWidth={2} strokeLinejoin="round" />

        {/* Baseline */}
        <line
          x1={PAD.left}
          x2={PAD.left + plotW}
          y1={PAD.top + plotH}
          y2={PAD.top + plotH}
          stroke="var(--axis)"
          strokeWidth={1}
        />

        {/* y ticks */}
        {ticks.map((t, i) => (
          <text
            key={i}
            x={PAD.left - 6}
            y={y(t) + 3}
            textAnchor="end"
            fontSize={9}
            fill="var(--muted)"
            className="tabular"
          >
            {Math.round(t)}
          </text>
        ))}

        {/* x ticks */}
        {[0, totalMi / 2, totalMi].map((mi, i) => (
          <text
            key={i}
            x={PAD.left + (mi / totalMi) * plotW}
            y={H - 6}
            textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"}
            fontSize={9}
            fill="var(--muted)"
            className="tabular"
          >
            {mi.toFixed(mi < 10 ? 1 : 0)} mi
          </text>
        ))}

        {/* One selective direct label: the low point, which is what matters here */}
        {hover === null && (
          <>
            <circle
              cx={x(lowestIdx)}
              cy={y(minFt)}
              r={3.5}
              fill="var(--elevation)"
              stroke="var(--surface)"
              strokeWidth={2}
            />
            <text
              x={Math.min(Math.max(x(lowestIdx), PAD.left + 16), PAD.left + plotW - 16)}
              y={y(minFt) + 15}
              textAnchor="middle"
              fontSize={9}
              fill="var(--text-secondary)"
              className="tabular"
            >
              low {Math.round(minFt)} ft
            </text>
          </>
        )}

        {/* Hover crosshair */}
        {hover !== null && (
          <>
            <line
              x1={x(hover)}
              x2={x(hover)}
              y1={PAD.top}
              y2={PAD.top + plotH}
              stroke="var(--axis)"
              strokeWidth={1}
            />
            <circle
              cx={x(hover)}
              cy={y(feet[hover])}
              r={4}
              fill="var(--elevation)"
              stroke="var(--surface)"
              strokeWidth={2}
            />
          </>
        )}
      </svg>

      {hover !== null && (
        <div
          className="pointer-events-none absolute z-10 rounded-md px-2 py-1 text-[11px] shadow-lg"
          style={{
            left: Math.min(Math.max(x(hover) - 52, 0), Math.max(W - 112, 0)),
            top: 0,
            background: "var(--surface)",
            border: "1px solid var(--border)",
            color: "var(--text-primary)",
          }}
        >
          <span className="tabular">{miles[hover].toFixed(1)} mi</span>
          {" · "}
          <span className="tabular">{Math.round(feet[hover])} ft</span>
          {flooded.has(hover) && (
            <span style={{ color: "var(--status-critical)" }}> · warning / hazard overlap</span>
          )}
        </div>
      )}

      {bands.length > 0 && (
        <p className="mt-1 text-[11px]" style={{ color: "var(--text-secondary)" }}>
          <span
            className="mr-1 inline-block h-2 w-2 rounded-sm align-middle"
            style={{ background: "#d03b3b", opacity: 0.5 }}
          />
          Shaded stretches intersect warning / hazard areas, not necessarily flooded roads.
        </p>
      )}
    </div>
  );
}
