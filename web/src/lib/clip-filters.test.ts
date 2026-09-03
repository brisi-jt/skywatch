import { describe, expect, it } from "vitest";

import {
  buildClipFilters,
  emptyFilters,
  filtersFromSearchParams,
  filtersToSearchParams,
  hasActiveFilters,
  type FilterState,
} from "./clip-filters";

const populated: FilterState = {
  q: 'mayday freq:121.5',
  fromDate: "2026-07-10",
  toDate: "2026-07-12",
  freqId: "3",
  category: "emergency",
  interestingOnly: true,
  hasAircraft: true,
  starredOnly: true,
};

describe("hasActiveFilters", () => {
  it("is false for the empty state", () => {
    expect(hasActiveFilters(emptyFilters)).toBe(false);
  });

  it("is true once any filter is set", () => {
    expect(hasActiveFilters({ ...emptyFilters, q: "tower" })).toBe(true);
    expect(hasActiveFilters({ ...emptyFilters, interestingOnly: true })).toBe(true);
    expect(hasActiveFilters({ ...emptyFilters, freqId: "2" })).toBe(true);
    expect(hasActiveFilters({ ...emptyFilters, starredOnly: true })).toBe(true);
  });

  it("ignores a blank search string", () => {
    expect(hasActiveFilters({ ...emptyFilters, q: "   " })).toBe(false);
  });
});

describe("buildClipFilters", () => {
  it("omits everything for the empty state", () => {
    expect(buildClipFilters(emptyFilters)).toEqual({});
  });

  it("maps a populated state to API params", () => {
    expect(buildClipFilters(populated)).toEqual({
      q: "mayday freq:121.5",
      from_date: "2026-07-10",
      to_date: "2026-07-12",
      freq_id: 3,
      category: "emergency",
      interesting: true,
      has_match: true,
      starred: true,
    });
  });

  it("omits starred when not set", () => {
    expect(buildClipFilters({ ...emptyFilters, starredOnly: false })).toEqual({});
  });

  it("trims the search string and drops it when blank", () => {
    expect(buildClipFilters({ ...emptyFilters, q: "  mayday  " })).toEqual({ q: "mayday" });
    expect(buildClipFilters({ ...emptyFilters, q: "   " })).toEqual({});
  });
});

describe("URL round-trip", () => {
  it("restores the empty state from empty params", () => {
    expect(filtersFromSearchParams(new URLSearchParams())).toEqual(emptyFilters);
  });

  it("round-trips a populated state through URL params", () => {
    const restored = filtersFromSearchParams(filtersToSearchParams(populated));
    expect(restored).toEqual(populated);
  });

  it("omits default values from the query string", () => {
    const params = filtersToSearchParams({ ...emptyFilters, q: "tower" });
    expect(params.toString()).toBe("q=tower");
  });

  it("honours the legacy ?date= single-day link", () => {
    const params = new URLSearchParams("date=2026-07-11");
    const restored = filtersFromSearchParams(params);
    expect(restored.fromDate).toBe("2026-07-11");
    expect(restored.toDate).toBe("2026-07-11");
  });

  it("round-trips the starred filter through the URL", () => {
    const params = filtersToSearchParams({ ...emptyFilters, starredOnly: true });
    expect(params.toString()).toBe("starred=1");
    expect(filtersFromSearchParams(params).starredOnly).toBe(true);
  });

  it("an explicit range wins over the legacy date param", () => {
    const params = new URLSearchParams("date=2026-07-11&from=2026-07-01&to=2026-07-05");
    const restored = filtersFromSearchParams(params);
    expect(restored.fromDate).toBe("2026-07-01");
    expect(restored.toDate).toBe("2026-07-05");
  });
});
