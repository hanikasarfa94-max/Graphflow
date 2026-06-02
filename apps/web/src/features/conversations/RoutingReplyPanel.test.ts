import { describe, expect, test } from "bun:test";

import { parseRoutingHash } from "./RoutingReplyPanel";

describe("parseRoutingHash (routing reply deep-link activation)", () => {
  test("extracts the signal id from a #routing-{id} hash", () => {
    expect(parseRoutingHash("#routing-abc123")).toBe("abc123");
  });

  test("URL-decodes the id", () => {
    expect(parseRoutingHash("#routing-sig%2F9")).toBe("sig/9");
  });

  test("returns null for unrelated or empty hashes", () => {
    expect(parseRoutingHash("")).toBeNull();
    expect(parseRoutingHash("#proposal-1")).toBeNull();
    expect(parseRoutingHash("#routing-")).toBeNull();
    expect(parseRoutingHash("#")).toBeNull();
  });
});
