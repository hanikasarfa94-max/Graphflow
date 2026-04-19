import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages } from "next-intl/server";

import { AppShell } from "@/components/shell/AppShell";

import "./globals.css";

export const metadata: Metadata = {
  title: "WorkGraph",
  description: "Coordination as a graph, not a document.",
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
        <NextIntlClientProvider locale={locale} messages={messages}>
          {/* Phase Q — AppShell wraps the entire app under the i18n
              provider. It renders the left sidebar + drawer for authed
              routes and gracefully falls through to plain children on
              /login and /register (auth detection uses /api/auth/me). */}
          <AppShell>{children}</AppShell>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
