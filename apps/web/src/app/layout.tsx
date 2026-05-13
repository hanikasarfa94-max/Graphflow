import type { Metadata, Viewport } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";

import { AppShellV3 } from "@/components/shell/v062/AppShellV3";
import { ServiceWorkerRegister } from "@/components/pwa/ServiceWorkerRegister";

import "./globals.css";

export const metadata: Metadata = {
  title: "GraphFlow",
  description: "Coordination as a graph, not a document.",
  manifest: "/manifest.json",
  applicationName: "GraphFlow",
  appleWebApp: {
    // iOS doesn't read manifest.json the same way Android does — these meta
    // tags are what give "Add to Home Screen" a proper title + status bar.
    capable: true,
    title: "GraphFlow",
    statusBarStyle: "default",
  },
  icons: {
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }],
  },
};

export const viewport: Viewport = {
  // v3 palette — paper + accent blue. Matches --wg-paper / --wg-accent
  // in globals.css (light) and the dark-mode paper (dark).
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#F7F6F2" },
    { media: "(prefers-color-scheme: dark)", color: "#0D1018" },
  ],
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Locale + message catalog are resolved in src/i18n/request.ts.
  // getLocale / getMessages just read that request-scoped config.
  const locale = await getLocale();
  const messages = await getMessages();

  return (
    <html lang={locale}>
      <body>
        <ServiceWorkerRegister />
        <NextIntlClientProvider locale={locale} messages={messages}>
          {/* AppShellV3 — v0.6.2 5-surface IA. Replaces the project-
              centered AppShell. Detects auth via /api/auth/me and
              falls through to plain children on /login and /register.
              The old AppShell + AppSidebar files remain in the tree
              for Phase F cleanup; they are no longer mounted. */}
          <AppShellV3>{children}</AppShellV3>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
