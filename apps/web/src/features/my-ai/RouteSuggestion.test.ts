import { describe, expect, test } from "bun:test";

import { resolveDraft } from "./RouteSuggestion";

const target = {
  user_id: "u1",
  display_name: "Alice",
  b_facing_draft: "Alice — bandwidth for the export?",
};

describe("resolveDraft (B-facing disclosure-gate precedence)", () => {
  test("user edit wins over everything", () => {
    expect(resolveDraft("  my edit  ", target, "framing")).toBe("my edit");
  });

  test("falls back to the agent b_facing_draft when no edit", () => {
    expect(resolveDraft(undefined, target, "framing")).toBe(
      "Alice — bandwidth for the export?",
    );
  });

  test("empty/whitespace edit is ignored, falls through", () => {
    expect(resolveDraft("   ", target, "framing")).toBe(
      "Alice — bandwidth for the export?",
    );
  });

  test("falls back to framing when no edit and no b_facing_draft", () => {
    const bare = { user_id: "u2", display_name: "Bob" };
    expect(resolveDraft(undefined, bare, "the framing")).toBe("the framing");
  });
});
