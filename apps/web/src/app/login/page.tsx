import { Suspense } from "react";

import { PublicSplit } from "@/components/public/PublicSplit";

import { LoginForm } from "./LoginForm";

export const dynamic = "force-dynamic";

export default function LoginPage() {
  return (
    <PublicSplit>
      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>
    </PublicSplit>
  );
}
