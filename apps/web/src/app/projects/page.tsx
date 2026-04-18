import Link from "next/link";

import type { ProjectSummary } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

import { NewProjectForm } from "./NewProjectForm";

export const dynamic = "force-dynamic";

export default async function ProjectsPage() {
  const user = await requireUser("/projects");
  const projects = await serverFetch<ProjectSummary[]>("/api/projects");

  return (
    <main style={{ maxWidth: 860, margin: "0 auto", padding: "56px 24px" }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 32,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 12,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: "var(--wg-ink-soft)",
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
            WorkGraph
          </div>
          <h1 style={{ fontSize: 28, fontWeight: 600, margin: "8px 0 0" }}>
            Projects
          </h1>
        </div>
        <div
          style={{
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
          }}
        >
          signed in as {user.display_name}
          <form
            action="/api/auth/logout"
            method="POST"
            style={{ display: "inline" }}
          >
            <button
              type="submit"
              style={{
                marginLeft: 10,
                background: "transparent",
                border: "none",
                color: "var(--wg-accent)",
                cursor: "pointer",
                fontSize: 12,
                fontFamily: "var(--wg-font-mono)",
              }}
            >
              sign out
            </button>
          </form>
        </div>
      </header>

      <NewProjectForm />

      {projects.length === 0 ? (
        <div
          style={{
            padding: 24,
            border: "1px dashed var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            color: "var(--wg-ink-soft)",
            fontSize: 14,
          }}
        >
          No projects yet. Post the first intake message above to kick one off.
        </div>
      ) : (
        <ul
          style={{
            listStyle: "none",
            padding: 0,
            margin: 0,
            display: "grid",
            gap: 8,
          }}
        >
          {projects.map((p) => (
            <li key={p.id}>
              <Link
                href={`/projects/${p.id}`}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: "14px 16px",
                  border: "1px solid var(--wg-line)",
                  borderRadius: "var(--wg-radius)",
                  textDecoration: "none",
                  color: "var(--wg-ink)",
                  background: "#fff",
                }}
              >
                <div style={{ fontWeight: 600, fontSize: 15 }}>{p.title}</div>
                <div
                  style={{
                    fontSize: 12,
                    fontFamily: "var(--wg-font-mono)",
                    color: "var(--wg-ink-soft)",
                  }}
                >
                  {p.role}
                  {p.updated_at
                    ? ` · ${new Date(p.updated_at).toLocaleString()}`
                    : ""}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
