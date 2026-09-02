/** Bridges a recording summary to the player's clip shape. */

import type { RecordingSummary } from "./api/client";
import { clockTime, friendlyDate, localDay, mhz } from "./format";
import type { PlayerClip } from "./player";

export function toPlayerClip(clip: RecordingSummary): PlayerClip {
  return {
    id: clip.id,
    title: `${clockTime(clip.started_at_utc)} · ${clip.frequency.label}`,
    subtitle: `${mhz(clip.frequency.mhz)} MHz · ${friendlyDate(localDay(clip.started_at_utc))}`,
    interesting: clip.classification?.is_interesting ?? false,
  };
}

/** The playable, ordered queue for a list of clips (skips pruned audio). */
export function playableQueue(clips: RecordingSummary[]): PlayerClip[] {
  return clips.filter((clip) => clip.audio_available).map(toPlayerClip);
}
