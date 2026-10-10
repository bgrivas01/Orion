import React, { useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import type { Place } from "@orion/shared";
import { api } from "../lib/api";
import { useTheme } from "../lib/theme";

export default function DestinationSearch({
  value,
  onPick,
}: {
  value: string;
  onPick: (place: Place) => void;
}) {
  const t = useTheme();
  const [query, setQuery] = useState(value);
  const [results, setResults] = useState<Place[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => setQuery(value), [value]);

  // Debounced so typing does not burn the geocoding rate limit.
  useEffect(() => {
    if (query.length < 3 || query === value) {
      setResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      setBusy(true);
      try {
        setResults(await api.geocode(query));
      } catch {
        setResults([]);
      } finally {
        setBusy(false);
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [query, value]);

  return (
    <View style={styles.wrap}>
      <View
        style={[
          styles.field,
          { backgroundColor: t.surface, borderColor: t.border, shadowColor: "#000" },
        ]}
      >
        <TextInput
          value={query}
          onChangeText={setQuery}
          placeholder="Where do you need to go?"
          placeholderTextColor={t.muted}
          style={[styles.input, { color: t.textPrimary }]}
          returnKeyType="search"
        />
        {busy && <ActivityIndicator size="small" color={t.muted} />}
      </View>

      {results.length > 0 && (
        <View
          style={[styles.results, { backgroundColor: t.surface, borderColor: t.border }]}
        >
          <FlatList
            data={results.slice(0, 6)}
            keyboardShouldPersistTaps="handled"
            keyExtractor={(p, i) => `${p.lat},${p.lon},${i}`}
            renderItem={({ item }) => (
              <Pressable
                onPress={() => {
                  onPick(item);
                  setQuery(item.name);
                  setResults([]);
                }}
                style={styles.resultRow}
              >
                <Text numberOfLines={1} style={{ color: t.textPrimary, fontSize: 13 }}>
                  {item.name}
                </Text>
              </Pressable>
            )}
          />
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { position: "absolute", top: 54, left: 12, right: 12, zIndex: 10 },
  field: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    shadowOpacity: 0.18,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 4,
  },
  input: { flex: 1, fontSize: 15 },
  results: {
    marginTop: 6,
    borderWidth: 1,
    borderRadius: 12,
    overflow: "hidden",
    maxHeight: 220,
  },
  resultRow: { paddingHorizontal: 12, paddingVertical: 11 },
});
