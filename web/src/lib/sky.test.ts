import { describe, expect, it } from "vitest";

import type { SkyAircraftResource, SkyResponse } from "./api/client";
import { aircraftLabel, deriveSkyState, findOverheadAircraft, matchesIcao } from "./sky";

function aircraft(overrides: Partial<SkyAircraftResource> = {}): SkyAircraftResource {
  return {
    hex: "4009f9",
    callsign: null,
    lat: 51.7,
    lon: 0.05,
    alt_ft: null,
    gs_kt: null,
    track: null,
    type: null,
    registration: null,
    squawk: null,
    seen_s: null,
    heard_recently: false,
    heard_recording_ids: [],
    ...overrides,
  };
}

function response(overrides: Partial<SkyResponse> = {}): SkyResponse {
  return {
    source: "airplanes_live",
    attribution: "Aircraft positions courtesy of airplanes.live.",
    radius_nm: 25,
    station_lat: 51.5,
    station_lon: -0.1,
    generated_at: "2026-09-03T12:00:00+00:00",
    aircraft: [],
    ...overrides,
  };
}

describe("deriveSkyState", () => {
  it("is loading before the first response arrives", () => {
    expect(deriveSkyState({ isPending: true, isError: false, data: undefined })).toBe("loading");
  });

  it("is offline when the first fetch fails outright", () => {
    expect(deriveSkyState({ isPending: false, isError: true, data: undefined })).toBe("offline");
  });

  it("is sources-down when the chain reports null, even mid-poll after prior data", () => {
    expect(
      deriveSkyState({ isPending: false, isError: false, data: response({ source: null }) }),
    ).toBe("sources-down");
  });

  it("is quiet when a real source answers with nothing in range", () => {
    expect(
      deriveSkyState({
        isPending: false,
        isError: false,
        data: response({ source: "adsb_lol", aircraft: [] }),
      }),
    ).toBe("quiet");
  });

  it("is ready once aircraft are in range", () => {
    expect(
      deriveSkyState({ isPending: false, isError: false, data: response({ aircraft: [aircraft()] }) }),
    ).toBe("ready");
  });

  it("trusts stale data over a transient poll error rather than flashing offline", () => {
    expect(
      deriveSkyState({ isPending: false, isError: true, data: response({ aircraft: [aircraft()] }) }),
    ).toBe("ready");
  });
});

describe("aircraftLabel", () => {
  it("falls back to the uppercased hex with no callsign", () => {
    expect(aircraftLabel(aircraft({ hex: "4009f9" }))).toBe("4009F9");
  });

  it("prefers the callsign and appends altitude and type when present", () => {
    expect(
      aircraftLabel(aircraft({ callsign: "BAW472", alt_ft: 3200, type: "A320" })),
    ).toBe("BAW472 · 3,200ft · A320");
  });

  it("omits fields the source did not report", () => {
    expect(aircraftLabel(aircraft({ callsign: "BAW472" }))).toBe("BAW472");
  });

  it("rounds a fractional altitude", () => {
    expect(aircraftLabel(aircraft({ callsign: "BAW472", alt_ft: 3199.6 }))).toBe(
      "BAW472 · 3,200ft",
    );
  });
});

describe("matchesIcao", () => {
  it("compares case-insensitively", () => {
    expect(matchesIcao("4009f9", "4009F9")).toBe(true);
    expect(matchesIcao("4009F9", "4009f9")).toBe(true);
  });

  it("is false against a different hex", () => {
    expect(matchesIcao("4009f9", "aaaaaa")).toBe(false);
  });

  it("is false when there is nothing to compare against", () => {
    expect(matchesIcao("4009f9", null)).toBe(false);
    expect(matchesIcao("4009f9", undefined)).toBe(false);
  });
});

describe("findOverheadAircraft", () => {
  it("finds the live aircraft matching a clip's top match", () => {
    const inRange = aircraft({ hex: "aaaaaa" });
    expect(findOverheadAircraft("AAAAAA", [aircraft({ hex: "bbbbbb" }), inRange])).toBe(inRange);
  });

  it("is undefined when the aircraft has left range", () => {
    expect(findOverheadAircraft("aaaaaa", [aircraft({ hex: "bbbbbb" })])).toBeUndefined();
  });

  it("is undefined with no match icao24 or no live data yet", () => {
    expect(findOverheadAircraft(null, [aircraft()])).toBeUndefined();
    expect(findOverheadAircraft("aaaaaa", undefined)).toBeUndefined();
  });
});
