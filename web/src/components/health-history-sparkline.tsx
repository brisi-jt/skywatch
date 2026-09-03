"use client";

import { clockTime, localDay, weekday } from "@/lib/format";
import { lastDrop, recentTicks, uptimeFraction } from "@/lib/health-sparkline";
import { useHealthHistory } from "@/lib/api/hooks";
import { cn } from "@/lib/utils";

/** "Tuesday 03:12" from a UTC timestamp. */
function dropLabel(utc: string): string {
  return `${weekday(localDay(utc))} ${clockTime(utc)}`;
}

/** A week of capture-uptime ticks, for a quick glance at the Station view. */
export function HealthHistorySparkline() {
  const history = useHealthHistory();

  if (history.isPending) {
    return <div className="h-12 animate-pulse rounded-lg bg-muted" aria-hidden />;
  }
  if (history.isError || !history.data) {
    return null; // the full Station view already surfaces a load failure
  }

  const items = history.data.items;
  if (items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No health history yet — it builds up as the worker runs.
      </p>
    );
  }

  const ticks = recentTicks(items);
  const uptime = uptimeFraction(items);
  const drop = lastDrop(items);

  return (
    <div className="flex flex-col gap-2" aria-label="Capture uptime over the last week">
      <div className="flex h-6 items-stretch gap-px overflow-hidden rounded-md" role="img">
        {ticks.map((tick, i) => (
          <span
            key={`${tick.recorded_at}-${i}`}
            className={cn("flex-1 rounded-[1px]", tick.up ? "bg-health-good" : "bg-health-bad")}
            title={`${tick.up ? "listening" : "not listening"} — ${dropLabel(tick.recorded_at)}`}
          />
        ))}
      </div>
      <p className="text-sm text-muted-foreground">
        {uptime != null && `${Math.round(uptime * 100)}% listening this window`}
        {drop && ` · last drop: ${dropLabel(drop.recorded_at)}`}
        {!drop && uptime === 1 && " · no drops in this window"}
      </p>
    </div>
  );
}
