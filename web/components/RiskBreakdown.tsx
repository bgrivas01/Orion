"use client";

import { useState } from "react";
import { RISK_COMPONENTS, type RiskBreakdown as Breakdown } from "@orion/shared";

const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];

/**
 * Where a route's risk score comes from: one stacked bar out of 100, plus a
 * labelled row per component.
 *
 * The rows are the legend *and* the direct labels — two of the four light-mode
 * slots sit below 3:1 on the surface, so the numbers have to be visible in ink
 * rather than inferred from the bar.
 */
export default function RiskBreakdown({ breakdown }: { breakdown: Breakdown }) {
  const [hover, setHover] = useState<string | null>(null);

  const values = RISK_COMPONENTS.map((c, i) => ({
    ...c,
    value: (breakdown[c.key] as number) ?? 0,
    color: SERIES[i],
  }));
  const contributing = values.filter((v) => v.value > 0.05);

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <h4 className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-secondary)" }}>
          Why this score
        </h4>
        <span className="tabular text-xs" style={{ color: "var(--text-secondary)" }}>
          {breakdown.total.toFixed(0)} / 100
        </span>
      </div>

      {/* Stacked bar. 2px surface gaps keep adjacent fills separable. */}
      <div
        className="flex h-2.5 w-full overflow-hidden rounded-full"
        style={{ background: "var(--grid)" }}
        role="img"
        aria-label={`Risk score ${breakdown.total.toFixed(0)} of 100: ${contributing
          .map((v) => `${v.label} ${v.value.toFixed(0)}`)
          .join(", ")}`}
      >
        {contributing.map((v) => (
          <div
            key={v.key}
            onMouseEnter={() => setHover(v.key)}
            onMouseLeave={() => setHover(null)}
            style={{
              width: `${v.value}%`,
              background: v.color,
              marginRight: 2,
              opacity: hover && hover !== v.key ? 0.55 : 1,
              transition: "opacity 120ms",
            }}
          />
        ))}
      </div>

      <ul className="mt-2.5 space-y-1.5">
        {values.map((v) => (
          <li
            key={v.key}
            onMouseEnter={() => setHover(v.key)}
            onMouseLeave={() => setHover(null)}
            className="flex items-start gap-2 text-[11px]"
            style={{ opacity: v.value > 0.05 ? 1 : 0.55 }}
          >
            <span
              className="mt-[3px] h-2 w-2 shrink-0 rounded-sm"
              style={{ background: v.color }}
              aria-hidden
            />
            <span className="flex-1" style={{ color: "var(--text-primary)" }}>
              {v.label}
              {hover === v.key && (
                <span className="block" style={{ color: "var(--text-secondary)" }}>
                  {v.explain}
                </span>
              )}
            </span>
            <span className="tabular shrink-0" style={{ color: "var(--text-secondary)" }}>
              {v.value.toFixed(1)}
              <span style={{ color: "var(--muted)" }}> /{v.max}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
