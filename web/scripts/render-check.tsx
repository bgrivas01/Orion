/**
 * Smoke test for the chart components: server-renders every route card returned
 * by the API and fails if any SVG path contains a non-finite number.
 *
 * Catches the classic chart bug — NaN in path data from an empty or flat series —
 * without needing a browser.
 *
 * Usage: API_BASE=http://localhost:8000 npm run check:charts -w web
 */
import { renderToStaticMarkup } from "react-dom/server";
import React from "react";
import RouteCard from "../components/RouteCard";
import type { RouteCandidate } from "@orion/shared";

async function main() {
const res = await fetch(`${process.env.API_BASE ?? "http://localhost:8000"}/api/routes`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    origin: { lat: 29.7604, lon: -95.3698 },
    destination: { lat: 29.9902, lon: -95.3368 },
  }),
});
const data = await res.json();

let failures = 0;
for (const route of data.routes as RouteCandidate[]) {
  const html = renderToStaticMarkup(
    React.createElement(RouteCard, {
      route,
      selected: true, // expanded, so both charts render
      recommended: route.id === data.recommended_id,
      quickest: Math.min(...data.routes.map((r: RouteCandidate) => r.duration_s)),
      onSelect: () => {},
    }),
  );

  const problems: string[] = [];
  if (/NaN|Infinity|undefined/.test(html)) {
    problems.push("non-finite value in output: " + (html.match(/.{0,40}(NaN|Infinity|undefined).{0,40}/) ?? [])[0]);
  }
  // Every <path d="..."> must be made of finite numbers.
  for (const m of html.matchAll(/ d="([^"]+)"/g)) {
    for (const n of m[1].matchAll(/-?\d+\.?\d*(e-?\d+)?/g)) {
      if (!Number.isFinite(Number(n[0]))) problems.push(`bad path number: ${n[0]}`);
    }
  }
  const paths = [...html.matchAll(/ d="/g)].length;
  const rects = [...html.matchAll(/<rect/g)].length;

  console.log(
    `${route.label.padEnd(9)} score=${String(route.risk_score).padStart(5)} ` +
      `html=${String(html.length).padStart(5)}B paths=${paths} floodBands=${rects} ` +
      (problems.length ? `FAIL ${problems.slice(0, 2).join("; ")}` : "ok"),
  );
  failures += problems.length;
}
console.log(failures === 0 ? "\nALL CHARTS RENDER CLEAN" : `\n${failures} PROBLEM(S)`);
process.exit(failures === 0 ? 0 : 1);
}
main();
