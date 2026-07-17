"use client";

import React, { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { BENCH_COPY, WALKTHROUGH_STOPS } from "@/lib/tuning-copy";

/**
 * The first-visit tour: a banner that walks the bench top-to-bottom in four
 * stops, highlighting one section at a time. Finishing or skipping records
 * the dismissal on the server, so it never returns by itself; the explain
 * overlay's footer can replay it on request.
 */
export function WalkthroughBanner({
  step,
  onStep,
  onFinish,
}: {
  /** Index into WALKTHROUGH_STOPS, or null when the tour is not running. */
  step: number | null;
  onStep: (step: number) => void;
  onFinish: () => void;
}) {
  const stop = step === null ? null : WALKTHROUGH_STOPS[step];

  // Scroll the highlighted section into view as the tour advances.
  useEffect(() => {
    if (!stop) return;
    const target = document.querySelector(`[data-walkthrough="${stop.anchor}"]`);
    target?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [stop]);

  if (step === null || !stop) return null;
  const last = step === WALKTHROUGH_STOPS.length - 1;

  return (
    <div
      role="region"
      aria-label="Tuning bench tour"
      className="sticky top-4 z-20 rounded-xl border bg-popover p-4 shadow-lg"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-mono text-sm text-muted-foreground">
          {step + 1} of {WALKTHROUGH_STOPS.length}
        </span>
        <h2 className="font-display text-lg font-semibold">{stop.title}</h2>
      </div>
      <p className="mt-1 max-w-prose text-base text-muted-foreground">{stop.body}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" className="min-h-10" onClick={onFinish}>
          {BENCH_COPY.walkthroughSkip}
        </Button>
        <div className="ml-auto flex gap-2">
          {step > 0 && (
            <Button variant="outline" size="sm" className="min-h-10" onClick={() => onStep(step - 1)}>
              {BENCH_COPY.walkthroughBack}
            </Button>
          )}
          <Button
            size="sm"
            className="min-h-10"
            onClick={() => (last ? onFinish() : onStep(step + 1))}
          >
            {last ? BENCH_COPY.walkthroughDone : BENCH_COPY.walkthroughNext}
          </Button>
        </div>
      </div>
    </div>
  );
}
