/**
 * The Clips view's filter state, and how it maps to the API query and to
 * shareable URL parameters.
 *
 * One `FilterState` drives three things: the filter controls, the
 * `GET /recordings` request, and the browser URL. Keeping the URL a faithful
 * serialization of the state is what makes a filtered view shareable — paste
 * the link and the same clips come back.
 */

import type { ClipFilters } from "./api/hooks";

export interface FilterState {
  /** The search box: free text plus the freq:/callsign:/interesting/before:/after: grammar. */
  q: string;
  fromDate: string;
  toDate: string;
  /** "all" or a numeric frequency id as a string (matches the Select value). */
  freqId: string;
  /** "all" or a classification category. */
  category: string;
  interestingOnly: boolean;
  hasAircraft: boolean;
}

export const emptyFilters: FilterState = {
  q: "",
  fromDate: "",
  toDate: "",
  freqId: "all",
  category: "all",
  interestingOnly: false,
  hasAircraft: false,
};

/** Whether any filter is set — used to word the result count and show the reset. */
export function hasActiveFilters(state: FilterState): boolean {
  return (
    state.q.trim() !== "" ||
    state.fromDate !== "" ||
    state.toDate !== "" ||
    state.freqId !== "all" ||
    state.category !== "all" ||
    state.interestingOnly ||
    state.hasAircraft
  );
}

/** The API query parameters for a filter state; omits anything left at its default. */
export function buildClipFilters(state: FilterState): ClipFilters {
  return {
    ...(state.q.trim() && { q: state.q.trim() }),
    ...(state.fromDate && { from_date: state.fromDate }),
    ...(state.toDate && { to_date: state.toDate }),
    ...(state.freqId !== "all" && { freq_id: Number(state.freqId) }),
    ...(state.interestingOnly && { interesting: true as const }),
    ...(state.category !== "all" && { category: state.category }),
    ...(state.hasAircraft && { has_match: true as const }),
  };
}

/** Serialize a filter state to URL query parameters (defaults are omitted). */
export function filtersToSearchParams(state: FilterState): URLSearchParams {
  const params = new URLSearchParams();
  if (state.q.trim()) params.set("q", state.q.trim());
  if (state.fromDate) params.set("from", state.fromDate);
  if (state.toDate) params.set("to", state.toDate);
  if (state.freqId !== "all") params.set("freq", state.freqId);
  if (state.category !== "all") params.set("category", state.category);
  if (state.interestingOnly) params.set("interesting", "1");
  if (state.hasAircraft) params.set("aircraft", "1");
  return params;
}

/**
 * Restore a filter state from URL query parameters. The legacy `date` link
 * (a single day) seeds both ends of the date range when no explicit range is
 * present, so older `/clips?date=` links keep working.
 */
export function filtersFromSearchParams(params: URLSearchParams): FilterState {
  const legacyDate = params.get("date") ?? "";
  return {
    q: params.get("q") ?? "",
    fromDate: params.get("from") ?? legacyDate,
    toDate: params.get("to") ?? legacyDate,
    freqId: params.get("freq") ?? "all",
    category: params.get("category") ?? "all",
    interestingOnly: params.get("interesting") === "1",
    hasAircraft: params.get("aircraft") === "1",
  };
}
