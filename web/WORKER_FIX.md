## MapLibre worker loading

MapLibre 6.13.0 emits `Worker failed to load. Check that the worker URL is
correct.` when its worker raises a loading error. Its default module-worker
URL is a sibling of `import.meta.url`; a Next.js bundle can relocate that URL
without serving the matching worker alongside it. This error alone does not
prove a 404: CSP, MIME type and worker execution errors can also cause it.

Orion sets the URL to `/maplibre-gl-worker.mjs` immediately before creating
the map. `scripts/copy-map-worker.mjs` copies that worker from the installed
MapLibre package into `public/`, so the worker and library versions match.
The npm `predev` and `prebuild` hooks run the copy automatically. The generated
worker is ignored by Git. No backend or database change is required.

### Verify

1. From the repository root run `npm install`, then `npm run web`. This uses
   Next.js's default Turbopack development server and runs the workspace's
   `predev` hook. Direct `npx next dev` skips that hook; run
   `node scripts/copy-map-worker.mjs` from `web/` first if using that command.
2. In browser DevTools, open Network and reload. The request for
   `/maplibre-gl-worker.mjs` must return HTTP 200 with a JavaScript MIME type
   and JavaScript content (not an HTML error page).
3. The basemap and report markers should render. The Console should have no
   worker loading errors. Check CSP errors if loading still fails; module
   workers require an allowed same-origin worker URL.
4. For production run `npm run build -w web`, then `npm run start -w web`.
   The prebuild hook creates the worker before the build.

The local preview was verified in Next.js 16.4.0 with Webpack: the worker
endpoint returned 200, the map and report markers rendered, and the browser
console had no captured errors. Turbopack was not independently verified in
this restricted Windows session. The older preview's `Spacing_Mark` error
came from a temporary Babel configuration and is a separate compile failure.
