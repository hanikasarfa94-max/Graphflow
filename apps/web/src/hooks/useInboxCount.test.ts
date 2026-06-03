import { describe, expect, test } from "bun:test";

import { formatBadgeCount } from "./useInboxCount";

describe("formatBadgeCount (inbox badge display)", () => {
  test("hides at zero / negative / non-finite", () => {
    expect(formatBadgeCount(0)).toBeNull();
    expect(formatBadgeCount(-3)).toBeNull();
    expect(formatBadgeCount(NaN)).toBeNull();
  });
  test("shows the count for 1..99", () => {
    expect(formatBadgeCount(1)).toBe("1");
    expect(formatBadgeCount(99)).toBe("99");
  });
  test("clamps above 99", () => {
    expect(formatBadgeCount(100)).toBe("99+");
    expect(formatBadgeCount(5000)).toBe("99+");
  });
});
