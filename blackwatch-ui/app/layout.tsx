import type { Metadata, Viewport } from "next";
// Self-hosted via @fontsource — no network calls at build time. Switching
// away from next/font/google because Lightsail build env can't reach
// fonts.googleapis.com reliably and the build would fail.
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";

import { AppShell } from "@/components/layout/AppShell";
import "./globals.css";

export const metadata: Metadata = {
  title: "BlackWatch",
  description: "Security telemetry",
};

export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#0A0B0F",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <a
          href="#main-content"
          className="sr-only z-50 rounded bg-signal px-3 py-2 text-sm text-canvas focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
        >
          Skip to main content
        </a>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
