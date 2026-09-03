import type { DailyMovementCount } from "@/lib/api/client";
import { friendlyDate } from "@/lib/format";
import { polylinePoints, trendPoints } from "@/lib/stats-chart";

const WIDTH = 600;
const HEIGHT = 140;

/** A daily movements trend as a plain two-line SVG chart — no chart library. */
export function StatsTrend({ daily }: { daily: DailyMovementCount[] }) {
  if (daily.length === 0) return null;
  const points = trendPoints(daily);
  const first = daily[0];
  const last = daily[daily.length - 1];

  return (
    <div className="mt-3 rounded-xl border bg-card p-4">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        className="h-32 w-full"
        role="img"
        aria-label={`Transmissions per day, ${friendlyDate(first.date)} to ${friendlyDate(last.date)}`}
      >
        <polyline
          points={polylinePoints(points, "yTotal", WIDTH, HEIGHT)}
          fill="none"
          strokeWidth={2}
          className="stroke-muted-foreground"
        />
        <polyline
          points={polylinePoints(points, "yInteresting", WIDTH, HEIGHT)}
          fill="none"
          strokeWidth={2.5}
          className="stroke-interesting"
        />
      </svg>
      <div className="mt-2 flex items-center justify-between text-sm text-muted-foreground">
        <span>{friendlyDate(first.date)}</span>
        <span className="flex items-center gap-4">
          <span className="flex items-center gap-1.5">
            <span
              className="size-2 rounded-full bg-muted-foreground"
              aria-hidden
            />
            all transmissions
          </span>
          <span className="flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-interesting" aria-hidden />
            interesting
          </span>
        </span>
        <span>{friendlyDate(last.date)}</span>
      </div>
    </div>
  );
}
