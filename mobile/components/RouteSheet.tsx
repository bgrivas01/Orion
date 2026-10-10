import React from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import {
  RISK_COMPONENTS,
  ROUTE_LABELS,
  bandStyle,
  formatDelta,
  formatDistance,
  formatDuration,
  totalFloodedMeters,
  type RouteCandidate,
  type RouteResponse,
} from "@orion/shared";
import { useTheme } from "../lib/theme";


export default function RouteSheet({
  result,
  selectedId,
  onSelect,
}: {
  result: RouteResponse;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const t = useTheme();
  const quickest = Math.min(...result.routes.map((r) => r.duration_s));

  return (
    <View style={[styles.sheet, { backgroundColor: t.page, borderColor: t.border }]}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.row}
      >
        {result.routes.map((route) => (
          <Card
            key={route.id}
            route={route}
            selected={route.id === selectedId}
            recommended={route.id === result.recommended_id}
            quickest={quickest}
            onPress={() => onSelect(route.id)}
          />
        ))}
      </ScrollView>
    </View>
  );
}

function Card({
  route,
  selected,
  recommended,
  quickest,
  onPress,
}: {
  route: RouteCandidate;
  selected: boolean;
  recommended: boolean;
  quickest: number;
  onPress: () => void;
}) {
  const t = useTheme();
  const band = bandStyle(route.risk_band);
  const floodedM = totalFloodedMeters(route);

  return (
    <Pressable
      onPress={onPress}
      style={[
        styles.card,
        {
          backgroundColor: t.surface,
          borderColor: selected ? band.mark : t.border,
          borderWidth: selected ? 2 : 1,
        },
      ]}
    >
      <View style={styles.cardHead}>
        <Text style={[styles.label, { color: t.textPrimary }]}>
          {ROUTE_LABELS[route.label]}
        </Text>
        {recommended && (
          <Text style={[styles.pill, { backgroundColor: t.grid, color: t.textSecondary }]}>
            PICK
          </Text>
        )}
      </View>

      {/* Icon + word, so the band never rests on colour alone */}
      <View style={[styles.bandRow, { backgroundColor: band.bg }]}>
        <Text style={{ color: band.mark, fontWeight: "700", fontSize: 12 }}>{band.icon}</Text>
        <Text style={{ color: t.textPrimary, fontWeight: "600", fontSize: 12 }}>
          {band.label}
        </Text>
        <Text style={{ color: t.textSecondary, fontSize: 11, fontVariant: ["tabular-nums"] }}>
          {route.risk_score.toFixed(0)}/100
        </Text>
      </View>

      <View style={styles.statRow}>
        <Text style={[styles.time, { color: t.textPrimary }]}>
          {formatDuration(route.duration_s)}
        </Text>
        <Text style={[styles.sub, { color: t.textSecondary }]}>
          {formatDistance(route.distance_m)}
        </Text>
        <Text style={[styles.sub, { color: t.muted }]}>
          {formatDelta(route.duration_s, quickest)}
        </Text>
      </View>

      {floodedM > 0 ? (
        <Text style={[styles.note, { color: t.statusCritical }]}>
          ✕ {formatDistance(floodedM)} through floodwater
        </Text>
      ) : route.avoidance_verified ? (
        <Text style={[styles.note, { color: t.statusGood }]}>✓ Verified clear of flooding</Text>
      ) : (
        <Text style={[styles.note, { color: t.textSecondary }]}>{band.blurb}</Text>
      )}

      {selected && <Breakdown route={route} />}
    </Pressable>
  );
}

/** Stacked contributions out of 100, with the value printed beside each label. */
function Breakdown({ route }: { route: RouteCandidate }) {
  const t = useTheme();
  const values = RISK_COMPONENTS.map((c, i) => ({
    ...c,
    value: (route.risk_breakdown[c.key] as number) ?? 0,
    color: t.series[i],
  }));

  return (
    <View style={{ marginTop: 10, gap: 6 }}>
      <View style={[styles.bar, { backgroundColor: t.grid }]}>
        {values
          .filter((v) => v.value > 0.05)
          .map((v) => (
            <View
              key={v.key}
              style={{ flex: v.value, backgroundColor: v.color, marginRight: 2 }}
            />
          ))}
        {/* Remainder keeps the bar scaled to 100 rather than to the total. */}
        <View style={{ flex: Math.max(100 - route.risk_breakdown.total, 0.01) }} />
      </View>

      {values.map((v) => (
        <View key={v.key} style={styles.legendRow}>
          <View style={[styles.chip, { backgroundColor: v.color }]} />
          <Text style={[styles.legendLabel, { color: t.textPrimary }]}>{v.label}</Text>
          <Text style={[styles.legendValue, { color: t.textSecondary }]}>
            {v.value.toFixed(1)}
            <Text style={{ color: t.muted }}>/{v.max}</Text>
          </Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  sheet: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    paddingTop: 10,
    paddingBottom: 26,
    borderTopWidth: 1,
  },
  row: { paddingHorizontal: 12, gap: 10 },
  card: { width: 250, borderRadius: 14, padding: 12 },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  label: { fontSize: 15, fontWeight: "700" },
  pill: {
    fontSize: 9,
    fontWeight: "700",
    paddingHorizontal: 5,
    paddingVertical: 2,
    borderRadius: 6,
    overflow: "hidden",
  },
  bandRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    alignSelf: "flex-start",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 999,
    marginTop: 8,
  },
  statRow: { flexDirection: "row", alignItems: "baseline", gap: 8, marginTop: 8 },
  time: { fontSize: 17, fontWeight: "600", fontVariant: ["tabular-nums"] },
  sub: { fontSize: 12, fontVariant: ["tabular-nums"] },
  note: { fontSize: 11, marginTop: 6, lineHeight: 15 },
  bar: { flexDirection: "row", height: 8, borderRadius: 999, overflow: "hidden" },
  legendRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  chip: { width: 8, height: 8, borderRadius: 2 },
  legendLabel: { flex: 1, fontSize: 11 },
  legendValue: { fontSize: 11, fontVariant: ["tabular-nums"] },
});
