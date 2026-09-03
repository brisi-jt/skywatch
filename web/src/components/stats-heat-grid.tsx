import type { FrequencyRef, HourlyHeatCell } from "@/lib/api/client";
import {
  HEAT_BUCKET_CLASSES,
  heatBucket,
  heatLookup,
  maxHeatCount,
} from "@/lib/stats-chart";
import { cn } from "@/lib/utils";

const HOURS = Array.from({ length: 24 }, (_, i) => i);

/** Busiest-hour × frequency heat grid — a plain CSS grid, shaded by count. */
export function StatsHeatGrid({
  frequencies,
  cells,
}: {
  frequencies: FrequencyRef[];
  cells: HourlyHeatCell[];
}) {
  if (frequencies.length === 0) return null;
  const lookup = heatLookup(cells);
  const max = maxHeatCount(cells);

  return (
    <div
      className="mt-3 overflow-x-auto rounded-xl border bg-card p-4"
      role="img"
      aria-label="Transmissions by hour of day and frequency; darker cells are busier"
    >
      <div
        className="grid min-w-[640px] gap-1"
        style={{ gridTemplateColumns: "8rem repeat(24, minmax(0, 1fr))" }}
      >
        <div aria-hidden />
        {HOURS.map((hour) => (
          <div
            key={hour}
            className="text-center font-mono text-xs text-muted-foreground"
          >
            {hour % 3 === 0 ? hour : ""}
          </div>
        ))}
        {frequencies.map((freq) => (
          <div className="contents" key={freq.id}>
            <div
              className="truncate pr-2 text-sm text-muted-foreground"
              title={freq.label}
            >
              {freq.label}
            </div>
            {HOURS.map((hour) => {
              const count = lookup.get(`${freq.id}:${hour}`) ?? 0;
              return (
                <div
                  key={hour}
                  className={cn(
                    "aspect-square rounded-sm",
                    HEAT_BUCKET_CLASSES[heatBucket(count, max)],
                  )}
                  title={`${freq.label}, ${hour.toString().padStart(2, "0")}:00 — ${count} ${
                    count === 1 ? "clip" : "clips"
                  }`}
                />
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
