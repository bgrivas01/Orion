import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  SafeAreaView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { StatusBar } from "expo-status-bar";
import * as Location from "expo-location";
import type {
  FloodZone,
  Gauge,
  LatLng,
  Place,
  RouteResponse,
} from "@orion/shared";
import DestinationSearch from "./components/DestinationSearch";
import FloodMap from "./components/FloodMap";
import RouteSheet from "./components/RouteSheet";
import { API_BASE, api } from "./lib/api";
import { requestNotificationPermission, useFloodWatch } from "./lib/alerts";
import { useTheme } from "./lib/theme";

export default function App() {
  const t = useTheme();

  const [origin, setOrigin] = useState<LatLng | null>(null);
  const [locationDenied, setLocationDenied] = useState(false);
  const [destination, setDestination] = useState<LatLng | null>(null);
  const [destLabel, setDestLabel] = useState("");

  const [result, setResult] = useState<RouteResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [floodZones, setFloodZones] = useState<FloodZone[]>([]);
  const [gauges, setGauges] = useState<Gauge[]>([]);
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedRoute = result?.routes.find((r) => r.id === selectedId) ?? null;
  const watch = useFloodWatch(origin, selectedRoute?.geometry ?? null);

  /* ------------------------------------------------- location + permissions */
  useEffect(() => {
    (async () => {
      await requestNotificationPermission();

      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== "granted") {
        setLocationDenied(true);
        return;
      }
      const pos = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });
      setOrigin({ lat: pos.coords.latitude, lon: pos.coords.longitude });

      // Keep the origin current as the user moves.
      const sub = await Location.watchPositionAsync(
        { accuracy: Location.Accuracy.Balanced, distanceInterval: 250 },
        (p) => setOrigin({ lat: p.coords.latitude, lon: p.coords.longitude }),
      );
      return () => sub.remove();
    })();
  }, []);

  /* -------------------------------------------------------- live conditions */
  useEffect(() => {
    api.floodZones().then(setFloodZones).catch(() => setFloodZones([]));
    api.gauges().then(setGauges).catch(() => setGauges([]));
  }, []);

  /* ------------------------------------------------------------- plan route */
  const plan = useCallback(
    async (to: LatLng) => {
      if (!origin) {
        setError("Waiting for your location.");
        return;
      }
      setPlanning(true);
      setError(null);
      try {
        const res = await api.planRoutes({
          origin,
          destination: to,
          preference: "safest",
          profile: "driving-car",
        });
        setResult(res);
        setSelectedId(res.recommended_id ?? res.routes[0]?.id ?? null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not plan a route.");
        setResult(null);
      } finally {
        setPlanning(false);
      }
    },
    [origin],
  );

  const pickDestination = (p: Place) => {
    const to = { lat: p.lat, lon: p.lon };
    setDestination(to);
    setDestLabel(p.name);
    plan(to);
  };

  const alerting = watch.status?.in_flood_zone ?? false;

  return (
    <View style={[styles.root, { backgroundColor: t.page }]}>
      <StatusBar style="auto" />

      <FloodMap
        routes={result?.routes ?? []}
        selectedId={selectedId}
        floodZones={floodZones}
        gauges={gauges}
        origin={origin}
        destination={destination}
        onSelect={setSelectedId}
      />

      {/* --------------------------------------------------- alert banner -- */}
      <SafeAreaView style={styles.topLayer} pointerEvents="box-none">
        {watch.status && (
          <View
            style={[
              styles.banner,
              {
                backgroundColor: alerting ? t.statusCritical : t.surface,
                borderColor: alerting ? t.statusCritical : t.border,
              },
            ]}
          >
            <Text
              style={{
                color: alerting ? "#ffffff" : t.textPrimary,
                fontSize: 12,
                fontWeight: alerting ? "700" : "500",
              }}
            >
              {alerting ? "⚠  " : ""}
              {watch.status.message}
            </Text>
          </View>
        )}
      </SafeAreaView>

      <DestinationSearch value={destLabel} onPick={pickDestination} />

      {/* ------------------------------------------------------- statuses -- */}
      {(locationDenied || error || planning) && (
        <View style={[styles.toast, { backgroundColor: t.surface, borderColor: t.border }]}>
          {planning && <ActivityIndicator size="small" color={t.series[0]} />}
          <Text style={{ color: t.textPrimary, fontSize: 12, flex: 1 }}>
            {planning
              ? "Checking flood conditions…"
              : locationDenied
                ? "Location permission denied — Orion needs it to use your position as the start."
                : error}
          </Text>
          {error && !planning && destination && (
            <Pressable onPress={() => plan(destination)}>
              <Text style={{ color: t.series[0], fontSize: 12, fontWeight: "600" }}>Retry</Text>
            </Pressable>
          )}
        </View>
      )}

      {result && (
        <RouteSheet result={result} selectedId={selectedId} onSelect={setSelectedId} />
      )}

      {!result && !planning && (
        <View style={[styles.hint, { backgroundColor: t.page, borderColor: t.border }]}>
          <Text style={{ color: t.textPrimary, fontSize: 13, fontWeight: "600" }}>
            {floodZones.length
              ? `${floodZones.length} active flood zone${floodZones.length === 1 ? "" : "s"} nearby`
              : "No active flood zones nearby"}
          </Text>
          <Text style={{ color: t.textSecondary, fontSize: 11, marginTop: 3, lineHeight: 15 }}>
            Search a destination and Orion ranks the ways there by flood risk, using live
            warnings, river gauges and terrain.
          </Text>
          <Text style={{ color: t.muted, fontSize: 9, marginTop: 6 }}>{API_BASE}</Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  topLayer: { position: "absolute", top: 0, left: 0, right: 0 },
  banner: {
    marginHorizontal: 12,
    marginTop: 4,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 10,
    borderWidth: 1,
  },
  toast: {
    position: "absolute",
    left: 12,
    right: 12,
    bottom: 130,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 12,
    borderWidth: 1,
  },
  hint: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 30,
    borderTopWidth: 1,
  },
});
