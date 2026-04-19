// Auto-tour of the Moonshot demo — logs in as maya, screenshots every key
// page, captures any JS console errors per page.
//
// Run: cd apps/web && node ../../scripts/demo/tour.mjs
// Output: PNGs + console log in /tmp/moonshot-tour/
//
// Uses the web app's vendored playwright (apps/web/node_modules/playwright).

import { chromium } from "playwright";
import { mkdirSync } from "fs";
import { resolve } from "path";

const BASE = process.env.WORKGRAPH_WEB_URL || "http://localhost:3000";
const PROJECT_ID = "6fb72b5a-82b4-43ca-92af-5185f14a1099";
const OUT = "/tmp/moonshot-tour";
mkdirSync(OUT, { recursive: true });

const routes = [
  { name: "01-landing",   path: "/" },
  { name: "02-login",     path: "/login" },
  { name: "03-projects",  path: "/projects" },
  { name: "04-overview",  path: `/projects/${PROJECT_ID}` },
  { name: "05-graph",     path: `/projects/${PROJECT_ID}/graph` },
  { name: "06-plan",      path: `/projects/${PROJECT_ID}/plan` },
  { name: "07-im",        path: `/projects/${PROJECT_ID}/im` },
  { name: "08-console",   path: `/console/${PROJECT_ID}` },
  { name: "09-health",    path: `/health` },
];

const results = [];

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 } });
const page = await ctx.newPage();

const consoleBuckets = new Map();
page.on("console", (msg) => {
  if (msg.type() === "error" || msg.type() === "warning") {
    const key = page.url();
    if (!consoleBuckets.has(key)) consoleBuckets.set(key, []);
    consoleBuckets.get(key).push(`[${msg.type()}] ${msg.text()}`);
  }
});
page.on("pageerror", (err) => {
  const key = page.url();
  if (!consoleBuckets.has(key)) consoleBuckets.set(key, []);
  consoleBuckets.get(key).push(`[pageerror] ${err.message}`);
});

// Step 1 — login as maya
console.log(">>> logging in as maya");
await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
await page.fill('input[name="username"]', "maya");
await page.fill('input[name="password"]', "moonshot2026");
await page.click('button[type="submit"]');
await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
console.log(`    landed at ${page.url()}`);

for (const route of routes) {
  const url = BASE + route.path;
  consoleBuckets.set(url, []);
  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20000 });
    await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
    // Slight settle for ReactFlow / dashboard charts.
    await page.waitForTimeout(1500);
    const shotPath = resolve(OUT, `${route.name}.png`);
    await page.screenshot({ path: shotPath, fullPage: false });
    const errors = consoleBuckets.get(page.url()) || consoleBuckets.get(url) || [];
    const bodyText = (await page.locator("body").innerText().catch(() => "")).slice(0, 200);
    results.push({
      name: route.name,
      url,
      shot: shotPath,
      errors,
      bodyPreview: bodyText,
    });
    console.log(`  ✓ ${route.name} — ${errors.length} console errors`);
  } catch (err) {
    results.push({ name: route.name, url, shot: null, errors: [String(err)], bodyPreview: "" });
    console.log(`  ✗ ${route.name} — ${err.message}`);
  }
}

await browser.close();

console.log("\n=== tour summary ===");
for (const r of results) {
  console.log(`\n[${r.name}] ${r.url}`);
  console.log(`  shot: ${r.shot || "(none)"}`);
  if (r.errors.length > 0) {
    console.log(`  errors:`);
    for (const e of r.errors.slice(0, 5)) console.log(`    - ${e.slice(0, 200)}`);
  }
  if (r.bodyPreview) console.log(`  preview: ${r.bodyPreview.replace(/\s+/g, " ").slice(0, 120)}`);
}
