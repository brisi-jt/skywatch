/**
 * Plain-word presentation of scores. Raw numbers stay inside the technical
 * drawer; the card face speaks in words.
 */

export type Tier = "probably" | "possibly" | "unsure";

export function matchTier(confidence: number): Tier {
  if (confidence >= 0.65) return "probably";
  if (confidence >= 0.35) return "possibly";
  return "unsure";
}

export const TIER_WORD: Record<Tier, string> = {
  probably: "Probably",
  possibly: "Possibly",
  unsure: "Unsure",
};

/** Whisper average log-probability below this reads as a rough transcript. */
export function isRoughTranscript(avgLogprob: number | null | undefined): boolean {
  return avgLogprob != null && avgLogprob < -0.7;
}

const CATEGORY_WORDS: Record<string, string> = {
  routine: "Routine",
  emergency: "Emergency",
  urgency: "Urgency",
  go_around: "Go-around",
  medical: "Medical",
  fuel: "Fuel",
  guard_activity: "Guard activity",
  unusual: "Unusual",
  other: "Other",
};

export function categoryWord(category: string): string {
  return CATEGORY_WORDS[category] ?? category;
}

const FACILITY_WORDS: Record<string, string> = {
  guard: "Guard",
  tower: "Tower",
  ground: "Ground",
  approach: "Approach",
  radar: "Radar",
  atis: "ATIS",
  area_control: "Area control",
  airfield: "Airfield",
};

export function facilityWord(category: string): string {
  return FACILITY_WORDS[category] ?? category;
}

const STAGE_WORDS: Record<string, string> = {
  captured: "Captured",
  enriching: "Checking nearby aircraft",
  transcribing: "Transcribing",
  transcribed: "Transcribed",
  classifying: "Being assessed",
  classified: "Assessed",
  failed_enrich: "Aircraft lookup failed",
  failed_transcribe: "Transcription failed",
  failed_classify: "Assessment failed",
};

export function stageWord(stage: string): string {
  return STAGE_WORDS[stage] ?? stage;
}
