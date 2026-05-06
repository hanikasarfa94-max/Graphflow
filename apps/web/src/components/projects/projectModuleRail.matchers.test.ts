import { describe, expect, test } from "bun:test";

import {
  MODULE_MATCHERS,
  activeModuleKeys,
} from "./projectModuleRail.matchers";

const PID = "e749cfad-304f-436e-843e-04df8e1f3355";
const BASE = `/projects/${PID}`;

describe("ProjectModuleRail matchers — orphaned /detail/im fix", () => {
  test("Reviews module is in the matchers list", () => {
    const reviews = MODULE_MATCHERS.find((m) => m.key === "reviews");
    expect(reviews).toBeDefined();
    expect(reviews!.href(BASE)).toBe(`${BASE}/detail/im`);
  });

  test("Reviews href is /detail/im", () => {
    expect(activeModuleKeys(`${BASE}/detail/im`, PID)).toEqual(["reviews"]);
  });

  test("on /detail/im, Reviews is active and Audit is NOT", () => {
    const active = activeModuleKeys(`${BASE}/detail/im`, PID);
    expect(active).toContain("reviews");
    expect(active).not.toContain("audit");
  });

  test("Audit href is /detail/graph", () => {
    const audit = MODULE_MATCHERS.find((m) => m.key === "audit");
    expect(audit!.href(BASE)).toBe(`${BASE}/detail/graph`);
  });

  test("Audit fires on graph / plan / risks / decisions / conflicts / events / delivery", () => {
    for (const sub of [
      "graph",
      "plan",
      "risks",
      "decisions",
      "conflicts",
      "events",
      "delivery",
    ]) {
      const active = activeModuleKeys(`${BASE}/detail/${sub}`, PID);
      expect(active).toContain("audit");
      expect(active).not.toContain("reviews");
    }
  });

  test("Audit does NOT fire on /detail/im or /detail/tasks", () => {
    expect(activeModuleKeys(`${BASE}/detail/im`, PID)).not.toContain("audit");
    expect(activeModuleKeys(`${BASE}/detail/tasks`, PID)).not.toContain(
      "audit",
    );
  });

  test("Tasks shortcut owns /detail/tasks", () => {
    expect(activeModuleKeys(`${BASE}/detail/tasks`, PID)).toEqual(["tasks"]);
  });

  test("Stream owns the bare project route + sub-rooms but not /detail/*", () => {
    expect(activeModuleKeys(BASE, PID)).toEqual(["stream"]);
    expect(activeModuleKeys(`${BASE}/`, PID)).toEqual(["stream"]);
    expect(activeModuleKeys(`${BASE}/rooms/abc`, PID)).toEqual(["stream"]);
    expect(activeModuleKeys(`${BASE}/detail/graph`, PID)).not.toContain(
      "stream",
    );
  });

  test("KB / status / team / settings / renders / meetings / skills each own their prefix", () => {
    for (const key of [
      "kb",
      "status",
      "team",
      "settings",
      "renders",
      "meetings",
      "skills",
    ]) {
      const path = `${BASE}/${key === "kb" ? "kb" : key}`;
      const active = activeModuleKeys(path, PID);
      expect(active).toEqual([key]);
    }
  });
});
