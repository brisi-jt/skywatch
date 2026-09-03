import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/hooks";

import {
  MAX_QUESTION_LENGTH,
  askErrorMessage,
  retryAfterSeconds,
  sanitizeQuestion,
} from "./ask";

describe("sanitizeQuestion", () => {
  it("trims surrounding whitespace", () => {
    expect(sanitizeQuestion("  was there a mayday today?  ")).toBe(
      "was there a mayday today?",
    );
  });

  it("is null for blank or whitespace-only input", () => {
    expect(sanitizeQuestion("")).toBeNull();
    expect(sanitizeQuestion("   ")).toBeNull();
  });

  it("caps length at the backend limit", () => {
    const long = "a".repeat(MAX_QUESTION_LENGTH + 50);
    expect(sanitizeQuestion(long)?.length).toBe(MAX_QUESTION_LENGTH);
  });
});

describe("retryAfterSeconds", () => {
  it("reads the retry_after_s extension off a 429", () => {
    const error = new ApiError(429, {
      type: "about:blank",
      title: "Too Many Requests",
      status: 429,
      detail: "asked again too soon",
      code: "ask_rate_limited",
      retry_after_s: 12,
    } as never);
    expect(retryAfterSeconds(error)).toBe(12);
  });

  it("is null for a non-ApiError or a missing/invalid field", () => {
    expect(retryAfterSeconds(new Error("boom"))).toBeNull();
    expect(retryAfterSeconds(new ApiError(429, null))).toBeNull();
  });
});

describe("askErrorMessage", () => {
  it("names the retry countdown on a rate limit", () => {
    const error = new ApiError(429, {
      type: "about:blank",
      title: "Too Many Requests",
      status: 429,
      detail: "asked again too soon",
      code: "ask_rate_limited",
      retry_after_s: 8,
    } as never);
    expect(askErrorMessage(error)).toContain("8s");
  });

  it("explains a budget-exhausted 503 plainly", () => {
    const error = new ApiError(503, null);
    expect(askErrorMessage(error)).toMatch(/budget/i);
  });

  it("flags an empty question as not a question", () => {
    const error = new ApiError(422, null);
    expect(askErrorMessage(error)).toMatch(/question/i);
  });

  it("falls back to a generic message for anything else", () => {
    expect(askErrorMessage(new Error("network down"))).toMatch(/went wrong/i);
  });
});
