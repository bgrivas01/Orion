import { createRequire } from "node:module";
import { copyFileSync, mkdirSync } from "node:fs";

const require = createRequire(import.meta.url);
const publicDirectory = new URL("../public/", import.meta.url);
mkdirSync(publicDirectory, { recursive: true });
copyFileSync(
  require.resolve("maplibre-gl/dist/maplibre-gl-worker.mjs"),
  new URL("maplibre-gl-worker.mjs", publicDirectory),
);
