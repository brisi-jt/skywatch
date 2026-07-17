"use client";

import { ArrowRight, SlidersHorizontal } from "lucide-react";
import Link from "next/link";

import { useTuningMeters } from "@/lib/api/hooks";
import { mhz as formatMhz } from "@/lib/format";
import { BENCH_COPY } from "@/lib/tuning-copy";

const PREVIEW_MAX_DB = 50;

/**
 * The Station page's doorway to the bench: a card with a miniature of the
 * live meters, so the levers feel one glance away.
 */
export function TuningEntryCard() {
  const meters = useTuningMeters();
  const channels = meters.data?.channels ?? [];
  const live =
    Boolean(meters.data?.stats.present) && !meters.data?.stats.stale && channels.length > 0;

  return (
    <Link
      href="/station/tuning/"
      className="group flex flex-wrap items-center gap-4 rounded-xl border bg-bench p-4 transition-colors hover:bg-accent/40 focus-visible:ring-[3px] focus-visible:ring-ring/50"
    >
      <SlidersHorizontal className="size-6 shrink-0 text-interesting" aria-hidden />
      <div className="min-w-0 flex-1">
        <h3 className="text-base font-semibold">{BENCH_COPY.entryCardTitle}</h3>
        <p className="text-sm text-muted-foreground">{BENCH_COPY.entryCardBody}</p>
      </div>

      {/* Miniature meter preview — a glance at the real S/N bars. */}
      {live && (
        <div className="meter-glass relative flex h-12 items-end gap-1.5 rounded-md px-2 pb-1 pt-1" aria-hidden>
          {channels.slice(0, 8).map((channel) => {
            const fraction =
              channel.snr_db === null
                ? 0
                : Math.min(1, Math.max(0.04, channel.snr_db / PREVIEW_MAX_DB));
            return (
              <span
                key={channel.freq_id}
                title={formatMhz(channel.mhz)}
                className="meter-led-fill w-2 origin-bottom rounded-sm"
                style={{ height: `${Math.max(6, fraction * 100)}%` }}
              />
            );
          })}
        </div>
      )}
      {!live && (
        <span className="text-sm text-muted-foreground" aria-hidden>
          no live meters
        </span>
      )}

      <span className="flex min-h-10 items-center gap-1 text-base font-medium text-primary">
        {BENCH_COPY.entryCardAction}
        <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
      </span>
    </Link>
  );
}
