/** Pure data shaping for the Station view's uptime/health sparkline strip.
 *
 * Heartbeats arrive oldest-first from `GET /health/history`. This module
 * turns that run into plain values a component can render directly.
 */

import type { HeartbeatResource } from "./api/client";

export const MAX_TICKS = 60;

export interface UptimeTick {
  up: boolean;
  recorded_at: string;
}

/** The most recent `MAX_TICKS` snapshots, oldest first, for a fixed-width strip. */
export function recentTicks(items: HeartbeatResource[], max: number = MAX_TICKS): UptimeTick[] {
  return items.slice(-max).map((item) => ({ up: item.capture_running, recorded_at: item.recorded_at }));
}

/** Fraction of the window's snapshots where capture was running, or null with no data. */
export function uptimeFraction(items: HeartbeatResource[]): number | null {
  if (items.length === 0) return null;
  const up = items.filter((item) => item.capture_running).length;
  return up / items.length;
}

/** The most recent snapshot where capture had stopped, or null if it never has. */
export function lastDrop(items: HeartbeatResource[]): HeartbeatResource | null {
  for (let i = items.length - 1; i >= 0; i--) {
    if (!items[i].capture_running) return items[i];
  }
  return null;
}
