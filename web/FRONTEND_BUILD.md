## Frontend compiler and CSS

Use `npm run web` for development and `npm run build -w web` followed by
`npm run start -w web` for production. Both compile scripts explicitly use
Turbopack. Keep the native Next.js compiler; do not add a `next/babel`
configuration or append `--webpack` to these commands.

The failing preview used a temporary `.babelrc` with `next/babel`. Its stack
points to Next's Babel loader and bundled regex Unicode-property transform,
which rejects `General_Category=Spacing_Mark` while processing MapLibre.
A minimal regex passed through that bundled Babel preset reproduces the same
error. This is a compile-time Babel failure, separate from MapLibre's worker
URL problem. Switching bundlers alone is insufficient if an external Babel
configuration is still present: remove the temporary preview configuration.
No Babel configuration is tracked in this repository, and MapLibre does not
need a downgrade or a patched node_modules file.

Tailwind v4 also needs the `@tailwindcss/postcss` plugin registered in
`postcss.config.mjs`; installing Tailwind alone does not generate the utility
CSS used by the layout. On small screens the map keeps its 45vh height and
the panel can shrink and scroll; on desktop the sidebar stays 380px wide.
The explicit MapLibre worker URL and predev/prebuild copy hooks are retained.

### Verification

- Install dependencies from the repository root, then use the commands above.
- In development and production, check `/maplibre-gl-worker.mjs` returns 200
  with a JavaScript content type and no worker errors appear in the console.
- At 1280x800 the main layout must be a flex row, with a 380px sidebar and
  a 900x800 map canvas. At narrow widths the map should occupy 45vh while
  the controls scroll below it. Confirm actual basemap tiles render.
- Check generated CSS is loaded and utility classes such as `flex`,
  `lg:flex-row` and `h-[45vh]` have computed styles.

The earlier Windows Turbopack checks passed development worker loading,
production compilation, TypeScript, static generation, and production worker
loading (HTTP 200, JavaScript MIME, no captured errors). Browser inspection
of the updated layout confirmed the desktop dimensions above and a 301px
map at a 668px-high narrow viewport. Test API responses can be stubbed; no
backend or database change is required.
