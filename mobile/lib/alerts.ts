import { useCallback, useEffect, useRef, useState } from "react";
import * as Notifications from "expo-notifications";
import type { AlertCheckResponse, LatLng, LineString } from "@orion/shared";
import { api } from "./api";

/**
 * Flood proximity alerts.
 *
 * Remote push notifications were removed from Expo Go in SDK 53, so this uses
 * *local* notifications driven by a foreground poll. That works in Expo Go with
 * no dev build, which is what we need for the demo. Moving to real background
 * push later means a development build plus expo-task-manager — the server side
 * (POST /api/alerts/subscribe) is already in place for it.
 */

const POLL_MS = 60_000;

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

export async function requestNotificationPermission(): Promise<boolean> {
  const existing = await Notifications.getPermissionsAsync();
  if (existing.granted) return true;
  const asked = await Notifications.requestPermissionsAsync();
  return asked.granted;
}

async function notify(title: string, body: string): Promise<void> {
  await Notifications.scheduleNotificationAsync({
    content: { title, body, sound: true },
    trigger: null, // fire now
  });
}

export interface FloodWatch {
  status: AlertCheckResponse | null;
  checking: boolean;
  error: string | null;
  /** Force an immediate check, e.g. from a pull-to-refresh. */
  refresh: () => void;
}

export function useFloodWatch(
  location: LatLng | null,
  activeRoute: LineString | null,
  radiusM = 5000,
): FloodWatch {
  const [status, setStatus] = useState<AlertCheckResponse | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  // Zones we have already alerted on, so the phone does not buzz every minute.
  const notified = useRef<Set<string>>(new Set());

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!location) return;
    let cancelled = false;

    (async () => {
      setChecking(true);
      try {
        const res = await api.checkAlerts(location.lat, location.lon, radiusM);
        if (cancelled) return;
        setStatus(res);
        setError(null);

        // Alert once per zone, and only for zones we are inside or close to.
        for (const zone of res.zones) {
          const near = (zone.distance_m ?? Infinity) < radiusM;
          if (!near || notified.current.has(zone.id)) continue;
          notified.current.add(zone.id);

          const where = res.in_flood_zone
            ? "You are inside this flood zone."
            : `About ${((zone.distance_m ?? 0) / 1609.344).toFixed(1)} mi away.`;
          await notify(`${zone.event} nearby`, `${where} ${zone.headline ?? ""}`.trim());
        }

        // Tell the backend where we are, so a future push build can find us.
        api
          .subscribe({
            device_id: deviceId(),
            location,
            radius_m: radiusM,
            active_route: activeRoute,
          })
          .catch(() => {
            /* best effort */
          });
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not check conditions");
      } finally {
        if (!cancelled) setChecking(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [location?.lat, location?.lon, radiusM, tick, activeRoute]);

  // Poll while the app is in the foreground.
  useEffect(() => {
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  return { status, checking, error, refresh };
}

let cachedId: string | null = null;
function deviceId(): string {
  if (!cachedId) {
    cachedId = `expo-${Math.random().toString(36).slice(2, 10)}`;
  }
  return cachedId;
}
