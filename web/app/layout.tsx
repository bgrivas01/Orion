import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Orion — Flood-Safe Routing",
  description:
    "Routes ranked by flood risk, using live NWS flood warnings, USGS river gauges and terrain elevation.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
