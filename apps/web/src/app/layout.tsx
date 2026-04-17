import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "WorkGraph",
  description: "Coordination as a graph, not a document.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
