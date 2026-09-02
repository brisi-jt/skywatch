/** Pure helpers for the follow-along transcript: active segment, low
 * confidence shading, and linking spoken callsign tokens to their candidate. */

export interface TimedSegment {
  start_s: number;
  end_s: number;
  avg_word_prob?: number | null;
}

/** Index of the segment covering `position` seconds, or -1 if none. */
export function activeSegmentIndex(segments: TimedSegment[], position: number): number {
  for (let i = 0; i < segments.length; i++) {
    if (position >= segments[i].start_s && position < segments[i].end_s) return i;
  }
  return -1;
}

/** Below this mean per-word probability a segment reads as "rough". */
export const LOW_CONFIDENCE_WORD_PROB = 0.6;

export function isLowConfidenceSegment(avgWordProb: number | null | undefined): boolean {
  return avgWordProb != null && avgWordProb < LOW_CONFIDENCE_WORD_PROB;
}

export interface CallsignToken {
  text: string;
  /** The aircraft match id when this token names a candidate, else null. */
  matchId: number | null;
}

export interface CallsignCandidate {
  id: number;
  callsign?: string | null;
  registration?: string | null;
  flight_number_guess?: string | null;
}

/** Split text into tokens, tagging any that name a candidate's callsign,
 * registration, or guessed flight number (whitespace-delimited, punctuation
 * and case ignored). */
export function tokenizeWithCallsigns(
  text: string,
  candidates: CallsignCandidate[],
): CallsignToken[] {
  const needles = new Map<string, number>();
  for (const c of candidates) {
    for (const raw of [c.callsign, c.registration, c.flight_number_guess]) {
      const key = raw?.trim().toUpperCase();
      if (key && !needles.has(key)) needles.set(key, c.id);
    }
  }
  return text.split(/(\s+)/).map((part) => {
    const clean = part.replace(/[^A-Za-z0-9-]/g, "").toUpperCase();
    return { text: part, matchId: clean ? (needles.get(clean) ?? null) : null };
  });
}
