"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

type Mode = "login" | "register";

export function LoginForm() {
  const router = useRouter();
  const search = useSearchParams();
  const next = search.get("next") ?? "/projects";

  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      const path = mode === "login" ? "/api/auth/login" : "/api/auth/register";
      const body =
        mode === "login"
          ? { username, password }
          : { username, password, display_name: displayName || username };
      const res = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        credentials: "include",
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setError(j.detail ?? `error ${res.status}`);
        return;
      }
      router.push(next);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "network error");
    } finally {
      setPending(false);
    }
  }

  return (
    <main
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "100vh",
        padding: 24,
      }}
    >
      <form
        onSubmit={handleSubmit}
        style={{
          width: 360,
          padding: 32,
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          background: "#fff",
        }}
      >
        <div
          style={{
            fontSize: 13,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--wg-ink-soft)",
            marginBottom: 24,
          }}
        >
          <span
            style={{
              display: "inline-block",
              width: "var(--wg-dot)",
              height: "var(--wg-dot)",
              borderRadius: "50%",
              background: "var(--wg-accent)",
              marginRight: 8,
              verticalAlign: "middle",
            }}
          />
          WorkGraph — {mode === "login" ? "sign in" : "create account"}
        </div>

        <Field
          label="Username"
          value={username}
          onChange={setUsername}
          required
          minLength={3}
          maxLength={32}
          autoFocus
        />
        {mode === "register" && (
          <Field
            label="Display name"
            value={displayName}
            onChange={setDisplayName}
          />
        )}
        <Field
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          required
          minLength={8}
        />

        {error && (
          <div
            role="alert"
            style={{
              marginTop: 12,
              color: "var(--wg-accent)",
              fontSize: 13,
              fontFamily: "var(--wg-font-mono)",
            }}
          >
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={pending}
          style={{
            marginTop: 20,
            width: "100%",
            padding: "10px 16px",
            background: "var(--wg-accent)",
            color: "#fff",
            border: "none",
            borderRadius: "var(--wg-radius)",
            fontSize: 14,
            fontWeight: 600,
            cursor: pending ? "progress" : "pointer",
            opacity: pending ? 0.7 : 1,
          }}
        >
          {pending ? "…" : mode === "login" ? "Sign in" : "Register"}
        </button>

        <button
          type="button"
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError(null);
          }}
          style={{
            marginTop: 10,
            width: "100%",
            padding: "8px",
            background: "transparent",
            color: "var(--wg-ink-soft)",
            border: "none",
            fontSize: 13,
            cursor: "pointer",
          }}
        >
          {mode === "login"
            ? "No account? Create one."
            : "Have an account? Sign in."}
        </button>
      </form>
    </main>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  required,
  minLength,
  maxLength,
  autoFocus,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  required?: boolean;
  minLength?: number;
  maxLength?: number;
  autoFocus?: boolean;
}) {
  return (
    <label style={{ display: "block", marginBottom: 12 }}>
      <div
        style={{
          fontSize: 12,
          color: "var(--wg-ink-soft)",
          marginBottom: 4,
          fontFamily: "var(--wg-font-mono)",
        }}
      >
        {label}
      </div>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        minLength={minLength}
        maxLength={maxLength}
        autoFocus={autoFocus}
        style={{
          width: "100%",
          padding: "8px 10px",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          fontSize: 14,
          fontFamily: "var(--wg-font-sans)",
          background: "var(--wg-surface)",
        }}
      />
    </label>
  );
}
