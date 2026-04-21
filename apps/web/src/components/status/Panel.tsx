// Panel / EmptyState — thin compatibility shims over the shared `Card`
// and `EmptyState` primitives in components/ui. Existing status code
// imports `{Panel, EmptyState}` from here; rather than chase every
// call site, we keep the named exports and forward to the primitive.
//
// New code should import from `@/components/ui` directly.

import type { ReactNode } from "react";

import { Card, EmptyState as UiEmptyState } from "@/components/ui";

export function Panel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <Card title={title} subtitle={subtitle}>
      {children}
    </Card>
  );
}

export const EmptyState = UiEmptyState;
