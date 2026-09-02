import { describe, expect, it } from "vitest";

import {
  activeSegmentIndex,
  isLowConfidenceSegment,
  tokenizeWithCallsigns,
} from "./transcript";

const segments = [
  { start_s: 0, end_s: 2 },
  { start_s: 2, end_s: 4.5 },
  { start_s: 4.5, end_s: 6 },
];

describe("activeSegmentIndex", () => {
  it("finds the segment covering the position", () => {
    expect(activeSegmentIndex(segments, 0)).toBe(0);
    expect(activeSegmentIndex(segments, 3)).toBe(1);
    expect(activeSegmentIndex(segments, 4.5)).toBe(2);
  });

  it("is inclusive of the start and exclusive of the end", () => {
    expect(activeSegmentIndex(segments, 2)).toBe(1);
    expect(activeSegmentIndex(segments, 1.999)).toBe(0);
  });

  it("returns -1 before the first and after the last", () => {
    expect(activeSegmentIndex(segments, -1)).toBe(-1);
    expect(activeSegmentIndex(segments, 6)).toBe(-1);
    expect(activeSegmentIndex([], 1)).toBe(-1);
  });
});

describe("isLowConfidenceSegment", () => {
  it("shades only genuinely low probabilities", () => {
    expect(isLowConfidenceSegment(0.4)).toBe(true);
    expect(isLowConfidenceSegment(0.9)).toBe(false);
    expect(isLowConfidenceSegment(null)).toBe(false);
    expect(isLowConfidenceSegment(undefined)).toBe(false);
  });
});

describe("tokenizeWithCallsigns", () => {
  const candidates = [
    { id: 7, callsign: "BAW2761", registration: "G-EUYW", flight_number_guess: "BA2761" },
  ];

  it("tags a matching callsign token with its candidate id", () => {
    const tokens = tokenizeWithCallsigns("this is BAW2761 landing", candidates);
    const tagged = tokens.filter((t) => t.matchId !== null);
    expect(tagged).toHaveLength(1);
    expect(tagged[0].text).toBe("BAW2761");
    expect(tagged[0].matchId).toBe(7);
  });

  it("matches registration and flight number, ignoring punctuation and case", () => {
    const tokens = tokenizeWithCallsigns("g-euyw, ba2761.", candidates);
    expect(tokens.filter((t) => t.matchId === 7)).toHaveLength(2);
  });

  it("reassembles to the original text", () => {
    const text = "speedbird two seven six one";
    expect(tokenizeWithCallsigns(text, candidates).map((t) => t.text).join("")).toBe(text);
  });

  it("tags nothing when there are no candidates", () => {
    const tokens = tokenizeWithCallsigns("BAW2761 landing", []);
    expect(tokens.every((t) => t.matchId === null)).toBe(true);
  });
});
