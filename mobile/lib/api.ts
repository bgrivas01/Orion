import Constants from "expo-constants";
import { Platform } from "react-native";
import { createClient } from "@orion/shared";

/**
 * Work out where the backend is.
 *
 * On a physical phone `localhost` points at the phone, not your laptop, so we
 * reuse the host Expo is already serving the bundle from and swap in the API
 * port. That means a teammate can clone, run `npx expo start`, and it works
 * with no per-machine config.
 *
 * Override explicitly by setting `extra.apiBase` in app.json when the backend
 * is deployed somewhere else.
 */
const API_PORT = 8000;

function inferBase(): string {
  const configured = (Constants.expoConfig?.extra as { apiBase?: string } | undefined)?.apiBase;
  if (configured) return configured;

  // e.g. "192.168.1.14:8081" while running `expo start`
  const hostUri = Constants.expoConfig?.hostUri ?? Constants.expoGoConfig?.debuggerHost;
  const host = hostUri?.split(":")[0];
  if (host && host !== "localhost" && host !== "127.0.0.1") {
    return `http://${host}:${API_PORT}`;
  }

  // Simulators can reach the host machine directly.
  return Platform.OS === "android"
    ? `http://10.0.2.2:${API_PORT}`
    : `http://localhost:${API_PORT}`;
}

export const API_BASE = inferBase();
export const api = createClient(API_BASE);
