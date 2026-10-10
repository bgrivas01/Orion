import { useColorScheme } from "react-native";
import { VIZ } from "@orion/shared";

/**
 * Theme tokens, taken from the same validated palette the web app uses so the
 * two clients cannot drift. Dark mode is a selected set of steps, not a flip.
 */
export const THEME = {
  light: {
    ...VIZ.light,
    page: "#f9f9f7",
    border: "rgba(11, 11, 11, 0.10)",
    statusGood: "#0ca30c",
    statusWarning: "#fab219",
    statusCritical: "#d03b3b",
    onAccent: "#ffffff",
  },
  dark: {
    ...VIZ.dark,
    page: "#0d0d0d",
    border: "rgba(255, 255, 255, 0.10)",
    statusGood: "#0ca30c",
    statusWarning: "#fab219",
    statusCritical: "#d03b3b",
    onAccent: "#ffffff",
  },
} as const;

export type Theme = (typeof THEME)["light"] | (typeof THEME)["dark"];

export function useTheme(): Theme {
  return useColorScheme() === "dark" ? THEME.dark : THEME.light;
}
