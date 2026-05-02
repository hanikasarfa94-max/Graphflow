import type { Metadata, Viewport } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";

import { AppShell } from "@/components/shell/AppShell";
import { AppShellVNext } from "@/components/shell/v-next/AppShell";
import { ServiceWorkerRegister } from "@/components/pwa/ServiceWorkerRegister";

// SHELL_VNEXT env flag (server-side; build-time toggle).
// When "true", the prototype-faithful 4-column shell mounts globally
// per docs/shell-v-next.txt. Default off — old per-project sidebar
// shell stays the production default during transition (spec §7
// "do not delete"). Phase 2 will add a runtime cookie toggle.
const SHELL_VARIANT = process.env.SHELL_VNEXT === "true" ? "vnext" : "legacy";

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

  const ShellComponent = SHELL_VARIANT === "vnext" ? AppShellVNext : AppShell;

  return (
    <html lang={locale}>
      <body>
        <ServiceWorkerRegister />
        <NextIntlClientProvider locale={locale} messages={messages}>
          {/* Phase Q — AppShell wraps the entire app under the i18n
              provider. Switches between legacy (projects-as-primary-nav)
              and v-next (4-column prototype-faithful) shell based on
              SHELL_VNEXT env. Both detect auth via /api/auth/me and
              fall through to plain children on /login and /register. */}
          <ShellComponent>{children}</ShellComponent>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
