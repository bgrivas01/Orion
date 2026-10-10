import React, { useEffect, useRef } from "react";
import MapView, { Marker, Polygon, Polyline, type Region } from "react-native-maps";
import { StyleSheet } from "react-native";
import {
  GAUGE_STATUS_COLORS,
  SEVERITY_COLORS,
  bandStyle,
  type FloodZone,
  type Gauge,
  type LatLng,
  type RouteCandidate,
} from "@orion/shared";

interface Props {
  routes: RouteCandidate[];
  selectedId: string | null;
  floodZones: FloodZone[];
  gauges: Gauge[];
  origin: LatLng | null;
  destination: LatLng | null;
  onSelect: (id: string) => void;
}

type Point = { latitude: number; longitude: number };

const toPoints = (coords: number[][]): Point[] =>
  coords.map((c) => ({ longitude: c[0], latitude: c[1] }));

export default function FloodMap({
  routes,
  selectedId,
  floodZones,
  gauges,
  origin,
  destination,
  onSelect,
}: Props) {
  const map = useRef<MapView>(null);
  const fitted = useRef<string | null>(null);

  // Frame the result once per route set.
  useEffect(() => {
    if (!routes.length || !map.current) return;
    const key = routes.map((r) => r.id).join("|");
    if (fitted.current === key) return;
    fitted.current = key;

    const points = routes.flatMap((r) => toPoints(r.geometry.coordinates));
    map.current.fitToCoordinates(points, {
      edgePadding: { top: 70, right: 50, bottom: 260, left: 50 },
      animated: true,
    });
  }, [routes]);

  const initialRegion: Region = {
    latitude: origin?.lat ?? 29.7604,
    longitude: origin?.lon ?? -95.3698,
    latitudeDelta: 0.4,
    longitudeDelta: 0.4,
  };

  // Draw the selected route last so it sits on top.
  const ordered = [...routes].sort((a, b) =>
    a.id === selectedId ? 1 : b.id === selectedId ? -1 : 0,
  );

  return (
    <MapView
      ref={map}
      style={StyleSheet.absoluteFill}
      initialRegion={initialRegion}
      showsUserLocation
      showsMyLocationButton={false}
      toolbarEnabled={false}
    >
      {floodZones.flatMap((zone, zi) =>
        zone.geometry.coordinates.map((polygon, pi) => (
          <Polygon
            key={`${zone.id}-${zi}-${pi}`}
            coordinates={toPoints(polygon[0])}
            holes={polygon.slice(1).map(toPoints)}
            fillColor={`${SEVERITY_COLORS[zone.severity] ?? SEVERITY_COLORS.unknown}3A`}
            strokeColor={SEVERITY_COLORS[zone.severity] ?? SEVERITY_COLORS.unknown}
            strokeWidth={1.5}
          />
        )),
      )}

      {ordered.map((route) => {
        const selected = route.id === selectedId;
        return (
          <Polyline
            key={route.id}
            coordinates={toPoints(route.geometry.coordinates)}
            strokeColor={bandStyle(route.risk_band).mark}
            strokeWidth={selected ? 6 : 3}
            tappable
            onPress={() => onSelect(route.id)}
            zIndex={selected ? 3 : 1}
          />
        );
      })}

      {/* Flooded stretches drawn on top of their route */}
      {ordered.flatMap((route) =>
        (route.flagged_segments ?? []).map((seg, i) => (
          <Polyline
            key={`${route.id}-flag-${i}`}
            coordinates={toPoints(seg.geometry.coordinates)}
            strokeColor="#d03b3b"
            strokeWidth={route.id === selectedId ? 8 : 4}
            lineDashPattern={[8, 6]}
            zIndex={route.id === selectedId ? 4 : 2}
          />
        )),
      )}

      {gauges
        .filter((g) => g.status === "flood" || g.status === "action")
        .map((g) => (
          <Marker
            key={g.site_id}
            coordinate={{ latitude: g.lat, longitude: g.lon }}
            pinColor={GAUGE_STATUS_COLORS[g.status]}
            title={g.name}
            description={
              g.current_ft != null
                ? `${g.current_ft} ft${g.flood_stage_ft ? ` · flood stage ${g.flood_stage_ft} ft` : ""}`
                : "No recent reading"
            }
          />
        ))}

      {destination && (
        <Marker
          coordinate={{ latitude: destination.lat, longitude: destination.lon }}
          title="Destination"
          pinColor="#2a78d6"
        />
      )}
    </MapView>
  );
}
