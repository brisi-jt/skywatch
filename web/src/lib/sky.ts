/** Pure helpers for the Sky view: state derivation, glyph labels, and the
 * clip↔aircraft matching that powers fusion (the "overhead now" chip, the
 * heard-recently accent, and the deep-link jump from a clip to its aircraft).
 *
 * Kept free of React/Leaflet so the branching logic — which is the part most
 * likely to have an off-by-one on a null field — is unit-testable without a
 * DOM or a map instance.
 */

import type { SkyAircraftResource, SkyResponse } from "./api/client";

export type SkyViewState = "loading" | "offline" | "sources-down" | "quiet" | "ready";

const ALT_FORMAT = new Intl.NumberFormat("en-GB");

/**
 * `source: null` and an empty aircraft list look the same on the wire as a
 * genuinely quiet sky — the two states this derives are "sources-down" (the
 * whole chain failed; `source` is null) and "quiet" (a real source answered
 * with nothing in range). `data` from a previous successful poll is trusted
 * over a transient `isError` from the interval's latest tick, so a single
 * dropped poll does not flash the view to "offline".
 */
export function deriveSkyState({
  isPending,
  isError,
  data,
}: {
  isPending: boolean;
  isError: boolean;
  data: SkyResponse | undefined;
}): SkyViewState {
  if (data) {
    if (data.source === null) return "sources-down";
    return data.aircraft.length > 0 ? "ready" : "quiet";
  }
  if (isError) return "offline";
  if (isPending) return "loading";
  return "loading";
}

/** "BAW472 · 3,200ft · A320" — falls back to the hex when no callsign has
 * been assigned yet, and omits any field the source didn't report. */
export function aircraftLabel(aircraft: SkyAircraftResource): string {
  const callsign = aircraft.callsign?.trim() || aircraft.hex.toUpperCase();
  const parts = [callsign];
  if (aircraft.alt_ft != null) {
    parts.push(`${ALT_FORMAT.format(Math.round(aircraft.alt_ft))}ft`);
  }
  if (aircraft.type) parts.push(aircraft.type);
  return parts.join(" · ");
}

/** ICAO hexes are case-insensitive on the wire; every comparison across the
 * fusion boundary (aircraft ↔ clip match) goes through this. */
export function matchesIcao(hex: string, icao24: string | null | undefined): boolean {
  if (!icao24) return false;
  return hex.toLowerCase() === icao24.toLowerCase();
}

/** The live aircraft a clip's top match refers to, if it's still in range —
 * the join behind the "overhead now" clip chip. */
export function findOverheadAircraft(
  icao24: string | null | undefined,
  aircraft: SkyAircraftResource[] | undefined,
): SkyAircraftResource | undefined {
  if (!icao24 || !aircraft) return undefined;
  return aircraft.find((a) => matchesIcao(a.hex, icao24));
}
