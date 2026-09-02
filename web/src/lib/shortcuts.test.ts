import { describe, expect, it } from "vitest";

import { isTypingTarget, shortcutFor } from "./shortcuts";

describe("isTypingTarget", () => {
  it("ignores shortcuts while typing in inputs, textareas, and selects", () => {
    expect(isTypingTarget({ tagName: "INPUT" })).toBe(true);
    expect(isTypingTarget({ tagName: "TEXTAREA" })).toBe(true);
    expect(isTypingTarget({ tagName: "SELECT" })).toBe(true);
    expect(isTypingTarget({ tagName: "input" })).toBe(true);
  });

  it("ignores shortcuts inside contenteditable regions", () => {
    expect(isTypingTarget({ tagName: "DIV", isContentEditable: true })).toBe(true);
  });

  it("allows shortcuts on non-typing elements", () => {
    expect(isTypingTarget({ tagName: "BUTTON" })).toBe(false);
    expect(isTypingTarget({ tagName: "DIV" })).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
    expect(isTypingTarget(undefined)).toBe(false);
  });
});

describe("shortcutFor", () => {
  it("maps the player keys", () => {
    expect(shortcutFor(" ")).toBe("toggle");
    expect(shortcutFor("Spacebar")).toBe("toggle");
    expect(shortcutFor("ArrowLeft")).toBe("back5");
    expect(shortcutFor("ArrowRight")).toBe("forward5");
    expect(shortcutFor("j")).toBe("next");
    expect(shortcutFor("k")).toBe("prev");
    expect(shortcutFor("K")).toBe("prev");
  });

  it("returns null for keys that are not shortcuts", () => {
    expect(shortcutFor("a")).toBeNull();
    expect(shortcutFor("Enter")).toBeNull();
    expect(shortcutFor("Escape")).toBeNull();
  });
});
