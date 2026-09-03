/** Pure data shaping for the story page's CSS/SVG charts — no chart library.
 *
 * Every function here takes API data and returns plain numbers or strings a
 * component can render directly, so the shaping itself stays unit-testable
 * without mounting anything.
 */

import type {
  AirlineCount,
  DailyMovementCount,
  HourlyHeatCell,
} from "./api/client";

export interface TrendPoint {
  /** 0 (oldest day) .. 1 (most recent day) along the x-axis. */
  x: number;
  /** 0..1, normalised against the window's busiest day. */
  yTotal: number;
  yInteresting: number;
}

/** Normalises a daily trend into 0..1 plot coordinates for an SVG line chart. */
export function trendPoints(daily: DailyMovementCount[]): TrendPoint[] {
  if (daily.length === 0) return [];
  const max = Math.max(1, ...daily.map((d) => d.total_count));
  const lastIndex = Math.max(1, daily.length - 1);
  return daily.map((d, i) => ({
    x: i / lastIndex,
    yTotal: d.total_count / max,
    yInteresting: d.interesting_count / max,
  }));
}

/** An SVG `points` attribute for a polyline, mapped into a pixel viewport (y flipped). */
export function polylinePoints(
  points: TrendPoint[],
  key: "yTotal" | "yInteresting",
  width: number,
  height: number,
): string {
  return points
    .map(
      (p) =>
        `${(p.x * width).toFixed(1)},${(height - p[key] * height).toFixed(1)}`,
    )
    .join(" ");
}

/** Shading step (0 = nothing heard, 4 = the grid's busiest cell). */
export function heatBucket(count: number, max: number): 0 | 1 | 2 | 3 | 4 {
  if (count <= 0 || max <= 0) return 0;
  const ratio = count / max;
  if (ratio > 0.75) return 4;
  if (ratio > 0.5) return 3;
  if (ratio > 0.25) return 2;
  return 1;
}

/** Tailwind classes for each shading step, using the named `interesting` token. */
export const HEAT_BUCKET_CLASSES: Record<0 | 1 | 2 | 3 | 4, string> = {
  0: "bg-muted",
  1: "bg-interesting/20",
  2: "bg-interesting/40",
  3: "bg-interesting/65",
  4: "bg-interesting",
};

/** Hour × frequency lookup built from the sparse cell list the API returns. */
export function heatLookup(cells: HourlyHeatCell[]): Map<string, number> {
  const map = new Map<string, number>();
  for (const cell of cells) {
    map.set(`${cell.freq_id}:${cell.hour}`, cell.count);
  }
  return map;
}

export function maxHeatCount(cells: HourlyHeatCell[]): number {
  return cells.reduce((max, c) => Math.max(max, c.count), 0);
}

/** Airline counts as 0..1 fractions of the busiest airline, for bar widths. */
export function airlineFractions(
  airlines: AirlineCount[],
): Array<AirlineCount & { fraction: number }> {
  if (airlines.length === 0) return [];
  const max = Math.max(1, ...airlines.map((a) => a.count));
  return airlines.map((a) => ({ ...a, fraction: a.count / max }));
}
