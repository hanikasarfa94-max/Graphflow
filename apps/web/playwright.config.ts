import { defineConfig, devices } from "@playwright/test";

const WEB_PORT = Number(process.env.WORKGRAPH_WEB_PORT ?? 3100);
const API_PORT = Number(process.env.WORKGRAPH_API_PORT ?? 8100);
const BASE_URL = `http://127.0.0.1:${WEB_PORT}`;

// Playwright boots the API + web dev servers on non-default ports so local
// dev can keep :3000 + :8000 running. The web server uses WORKGRAPH_API_BASE
// to reach the API on its alt port.

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "list",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: [
    {
      command: `uv run uvicorn workgraph_api.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: "../..",
      port: API_PORT,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        WORKGRAPH_ENV: "dev",
        WORKGRAPH_DATABASE_URL:
          process.env.WORKGRAPH_E2E_DATABASE_URL ??
          "sqlite+aiosqlite:///./data/workgraph-e2e.sqlite",
      },
    },
    {
      command: `bun run dev -- --port ${WEB_PORT}`,
      cwd: ".",
      port: WEB_PORT,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        WORKGRAPH_API_BASE: `http://127.0.0.1:${API_PORT}`,
      },
    },
  ],
});
