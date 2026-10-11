# SafeHaven frontend

A desktop/mobile React 19 + TanStack Start safety UI. Orion's existing web/, mobile/, backend/ and shared packages remain unchanged.

## Run independently

```sh
cd safehaven
npm install
npm run dev
```

Open http://localhost:3001. `npm run build` creates the Cloudflare-targeted production bundle using the original Lovable Vite configuration. Start the dev server once to generate the route tree, then run `npm test`.

This app is deliberately not part of the root npm workspace yet, keeping Orion's existing lockfile and commands unchanged. A compact copy of the original go-bag image is bundled.

Copy `.env.example` to `.env` for an optional origin-restricted Google Maps browser key. Missing keys show a fallback. No GitHub credentials or private keys belong in the app.

## Safety limits

Scores, forecasts, shelter destinations, directions, searches and offline downloads are frontend demos, not backend API responses. Offline mode does not download map tiles. Always follow official emergency guidance.

Orion risk scores use 0=safest, 100=worst; SafeHaven demo safety scores use 100=safest. Never wire the values directly. Backend integration and replacement of the existing Orion web application are intentionally outside this change.
