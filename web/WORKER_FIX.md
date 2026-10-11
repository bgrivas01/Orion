## MapLibre worker loading

MapLibre 6.13.0 emits `Worker failed to load. Check that the worker URL is
correct.` when its worker raises a loading error. Its default module-worker
URL is a sibling of `import.meta.url`. In the reproduced Next.js 16.4.0
Turbopack baseline, its automatic URL detection returned an empty string:
the browser constructed `new Worker("")` and emitted two loading errors from
the MapLibre chunk. This was not a missing `/maplibre-gl-worker.mjs` request:
there was no valid worker-file URL. The empty relative URL resolves to the
page rather than the worker JavaScript. Explicitly supplying the public
worker URL removes the dependency on bundled `import.meta.url` detection.

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

Verification on Windows in Next.js 16.4.0:

- Baseline Turbopack development: constructor URL was empty and two MapLibre
  worker-loading errors were captured.
- Fixed Turbopack development: `/maplibre-gl-worker.mjs` returned HTTP 200,
  `application/javascript; charset=UTF-8`, with no captured errors.
- Turbopack production build: compilation, TypeScript and static page generation
  passed.
- Production server: the same worker returned HTTP 200 with JavaScript MIME
  type and no captured errors. Map canvas screenshots were captured.
- Earlier Webpack preview: the basemap and report markers rendered.

The browser checks mocked frontend API requests; they did not contact or alter
the backend or database. The older preview's `Spacing_Mark` error came from a
temporary Babel configuration and is a separate compile failure.
