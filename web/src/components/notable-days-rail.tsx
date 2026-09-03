import Link from "next/link";

import type { NotableDay } from "@/lib/api/client";
import { friendlyDate } from "@/lib/format";

export function NotableDaysRail({ days }: { days: NotableDay[] }) {
  return (
    <div className="mt-3 flex gap-3 overflow-x-auto pb-1">
      {days.map((day) => (
        <Link
          key={day.date}
          href={`/?date=${day.date}`}
          className="flex min-w-40 flex-col gap-1 rounded-xl border bg-card px-4 py-3 transition-colors hover:bg-accent"
        >
          <span className="text-sm text-muted-foreground">
            {friendlyDate(day.date)}
          </span>
          <span className="font-mono text-lg text-readout">
            {day.interesting_count}{" "}
            {day.interesting_count === 1 ? "clip" : "clips"}
          </span>
        </Link>
      ))}
    </div>
  );
}
