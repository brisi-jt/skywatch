"use client";

import { Radio } from "lucide-react";

import type { StatusResponse } from "@/lib/api/client";

/**
 * Day one: the station is live but nothing has been heard yet. This is the
 * reader's literal first experience, so it gets a designed moment — a live
 * pulse, a real status line, and one explainer that retires itself the
 * moment the first clip lands.
 */
export function EmptyHero({
  status,
  activeCount,
}: {
  status: StatusResponse | undefined;
  activeCount: number | undefined;
}) {
  const listening = status?.capture.running ?? false;

  return (
    <section className="flex flex-col items-center gap-8 py-14 text-center">
      <div className="relative">
        <span className={listening ? "listening-pulse" : undefined} />
        <span className="relative flex size-20 items-center justify-center rounded-full bg-interesting-surface">
          <Radio className="size-9 text-interesting-surface-foreground" aria-hidden />
        </span>
      </div>

      <div className="max-w-xl">
        <h1 className="font-display text-3xl font-semibold tracking-tight">
          {listening ? "The station is listening" : "The station is ready"}
        </h1>
        <p className="mt-3 text-lg text-muted-foreground">
          {listening && activeCount
            ? `Tuned to ${activeCount} ${activeCount === 1 ? "frequency" : "frequencies"} right now. `
            : ""}
          Nothing recorded yet. The moment an aircraft transmits nearby, it appears here.
        </p>
      </div>

      <div className="max-w-xl rounded-xl border bg-card p-6 text-left">
        <h2 className="font-display text-lg font-semibold">What this station does</h2>
        <p className="mt-2 text-base text-muted-foreground">
          It listens to the aviation voice frequencies around you, records each transmission the
          moment it happens, writes down what was said, and flags the ones worth hearing — an
          emergency, a go-around, anything out of the ordinary. Routine chatter is kept for two
          weeks; the interesting moments are kept forever. This card will step aside once your
          first clip arrives.
        </p>
      </div>
    </section>
  );
}
