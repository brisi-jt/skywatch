"use client";

import Link from "next/link";

import { HealthChip, type Health } from "@/components/chips";
import type { StatusResponse } from "@/lib/api/client";

export function deriveHealth(status: StatusResponse) {
  // Deep tune is a deliberate, self-ending pause — cautionary, not a fault.
  const capture: Health = status.capture.running
    ? "good"
    : status.capture.deep_tune_active || status.capture.paused_for_disk
      ? "warn"
      : "bad";

  const failed = Object.entries(status.queues)
    .filter(([stage]) => stage.startsWith("failed_"))
    .reduce((sum, [, count]) => sum + count, 0);
  const pipeline: Health = failed > 0 ? "warn" : "good";

  const disk: Health = status.disk.low ? "bad" : status.disk.free_gb < status.disk.min_free_gb * 2 ? "warn" : "good";

  const exhausted = [status.budgets.llm, status.budgets.opensky].some(
    (budget) => budget && budget.remaining <= 0,
  );
  const budgets: Health = exhausted ? "warn" : "good";

  return { capture, pipeline, disk, budgets, failed };
}

/** Compact station health, always one click from the full Station view. */
export function HealthStrip({ status }: { status: StatusResponse }) {
  const health = deriveHealth(status);

  return (
    <Link
      href="/station/"
      className="flex flex-wrap items-center gap-2 rounded-xl border bg-card px-4 py-3 transition-colors hover:border-ring/50"
      aria-label="Station health — open the Station view"
    >
      <HealthChip
        health={health.capture}
        pulse={status.capture.running}
        label={
          status.capture.running
            ? "Listening"
            : status.capture.deep_tune_active
              ? "Off-air — deep tune"
              : status.capture.paused_for_disk
                ? "Paused — disk"
                : "Not listening"
        }
      />
      <HealthChip
        health={health.pipeline}
        label={health.failed > 0 ? `${health.failed} clips stuck` : "Pipeline clear"}
      />
      <HealthChip
        health={health.disk}
        label={`${status.disk.free_gb.toFixed(0)} GB free`}
      />
      <HealthChip health={health.budgets} label="Daily budgets" />
      <span className="ml-auto hidden text-sm text-muted-foreground sm:inline">Station →</span>
    </Link>
  );
}
