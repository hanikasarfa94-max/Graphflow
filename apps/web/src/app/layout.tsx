import type { Metadata, Viewport } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";

import { AppShell } from "@/components/shell/AppShell";
import { ServiceWorkerRegister } from "@/components/pwa/ServiceWorkerRegister";

import "./globals.css";

export const metadata: Metadata = {
  title: "WorkGraph",
  description: "Coordination as a graph, not a document.",
  manifest: "/manifest.json",
  applicationName: "graphflow",
  appleWebApp: {
    // iOS doesn't read manifest.json the same way Android does — these meta
    // tags are what give "Add to Home Screen" a proper title + status bar.
    capable: true,
    title: "graphflow",
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
  // Warm paper / amber — matches --wg-paper / --wg-amber in globals.css.
  // Chrome uses themeColor for the Android status bar once installed.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#d97706" },
    { media: "(prefers-color-scheme: dark)", color: "#0f0e0d" },
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
          {/* AppShell wraps the entire app under the i18n provider.
              Detects auth via /api/auth/me and falls through to plain
              children on /login and /register. */}
          <AppShell>{children}</AppShell>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
