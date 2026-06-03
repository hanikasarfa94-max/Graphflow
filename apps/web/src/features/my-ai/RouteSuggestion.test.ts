import { describe, expect, test } from "bun:test";

import {
  replyText,
  resolveDraft,
  routedPhase,
  shouldKeepPolling,
} from "./RouteSuggestion";

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

describe("routedPhase (sender-side loop state machine)", () => {
  test("undefined + pending map to waiting", () => {
    expect(routedPhase(undefined)).toBe("waiting");
    expect(routedPhase("pending")).toBe("waiting");
  });
  test("replied / accepted map through", () => {
    expect(routedPhase("replied")).toBe("replied");
    expect(routedPhase("accepted")).toBe("accepted");
  });
  test("declined / expired / unknown collapse to closed", () => {
    expect(routedPhase("declined")).toBe("closed");
    expect(routedPhase("expired")).toBe("closed");
    expect(routedPhase("???")).toBe("closed");
  });
});

describe("replyText (what the sender reads)", () => {
  test("picked option label wins", () => {
    expect(
      replyText({ picked_label: "Accept", custom_text: "ignored" }),
    ).toBe("Accept");
  });
  test("falls back to custom text", () => {
    expect(replyText({ custom_text: "  sure, by Friday  " })).toBe(
      "sure, by Friday",
    );
  });
  test("null reply or empty fields → null", () => {
    expect(replyText(null)).toBeNull();
    expect(replyText({ picked_label: "  ", custom_text: "" })).toBeNull();
  });
});

describe("shouldKeepPolling (bounded poll guard)", () => {
  test("keeps polling while pending and under cap", () => {
    expect(shouldKeepPolling("pending", 0, 60)).toBe(true);
    expect(shouldKeepPolling("pending", 59, 60)).toBe(true);
  });
  test("stops at the cap", () => {
    expect(shouldKeepPolling("pending", 60, 60)).toBe(false);
  });
  test("stops once a reply lands (terminal)", () => {
    expect(shouldKeepPolling("replied", 1, 60)).toBe(false);
    expect(shouldKeepPolling("accepted", 1, 60)).toBe(false);
  });
});
