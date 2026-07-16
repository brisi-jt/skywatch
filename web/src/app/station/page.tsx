"use client";

import { ArrowRight, CircleCheck, CircleAlert, CircleX } from "lucide-react";

import { HealthChip } from "@/components/chips";
import { deriveHealth } from "@/components/health-strip";
import { FrequencyTable } from "@/components/frequency-table";
import { GaugeBar } from "@/components/gauge-bar";
import type { BudgetInfo, StatusResponse } from "@/lib/api/client";
import { useFrequencies, useStatus } from "@/lib/api/hooks";
import { gb, mhz } from "@/lib/format";
import { cn } from "@/lib/utils";

export default function StationPage() {
  const status = useStatus();
  const frequencies = useFrequencies();

  if (status.isPending) {
    return <p className="text-base text-muted-foreground">Checking on the station…</p>;
  }
  if (status.isError || !status.data) {
    return (
      <p className="text-base text-health-bad">
        The station API is not answering. If the dashboard is open, the API is usually running —
        try refreshing; if this persists, see “Failure modes” in the Runbook.
      </p>
    );
  }

  const s = status.data;
  const health = deriveHealth(s);
  const activeCount = frequencies.data?.items.filter((f) => f.is_active).length;

  return (
    <div className="flex flex-col gap-10">
      {/* Layer 1 — plain English */}
      <section>
        <h1 className="font-display text-3xl font-semibold tracking-tight">
          {plainStatusSentence(s, activeCount)}
        </h1>
        <div className="mt-4 flex flex-wrap gap-2">
          <HealthChip
            health={health.capture}
            label={
              s.capture.running
                ? "Capture running"
                : s.capture.paused_for_disk
                  ? "Capture paused — disk space"
                  : "Capture stopped"
            }
          />
          <HealthChip
            health={health.pipeline}
            label={health.failed > 0 ? `${health.failed} clips need attention` : "Pipeline clear"}
          />
          <HealthChip
            health={health.disk}
            label={s.disk.low ? "Disk critically low" : `${gb(s.disk.free_gb)} free`}
          />
          <HealthChip
            health={health.budgets}
            label={health.budgets === "good" ? "Budgets healthy" : "A daily budget has run out"}
          />
        </div>
        {s.capture.detail && (
          <p className="mt-3 text-base text-muted-foreground">{s.capture.detail}</p>
        )}
      </section>

      {/* Layer 2 — the instrument panel */}
      <section aria-labelledby="frequencies-heading">
        <h2 id="frequencies-heading" className="font-display text-xl font-semibold">
          Frequencies
        </h2>
        <p className="mt-1 text-base text-muted-foreground">
          Flick a switch to change what the station listens to — it retunes itself in a few
          seconds. Rows marked “verify” still need their published frequency double-checked.
        </p>
        <div className="mt-4">
          {frequencies.isPending && (
            <div className="h-48 animate-pulse rounded-xl border bg-card" aria-hidden />
          )}
          {frequencies.isError && (
            <p className="text-base text-health-bad">The frequency list could not be loaded.</p>
          )}
          {frequencies.data && <FrequencyTable frequencies={frequencies.data.items} />}
        </div>
      </section>

      <section aria-labelledby="gauges-heading" className="max-w-2xl">
        <h2 id="gauges-heading" className="font-display text-xl font-semibold">
          Room to breathe
        </h2>
        <div className="mt-4 flex flex-col gap-5">
          <GaugeBar
            label="Disk"
            detail={`${gb(s.disk.free_gb)} free of ${gb(s.disk.total_gb)}`}
            fraction={s.disk.total_gb > 0 ? (s.disk.total_gb - s.disk.free_gb) / s.disk.total_gb : 0}
            tone={s.disk.low ? "bad" : health.disk === "warn" ? "warn" : "good"}
          />
          {s.budgets.llm && <BudgetGauge label="Daily verdicts" budget={s.budgets.llm} />}
          {s.budgets.opensky && (
            <BudgetGauge label="Daily aircraft lookups" budget={s.budgets.opensky} />
          )}
        </div>
      </section>

      <section aria-labelledby="trace-heading">
        <h2 id="trace-heading" className="font-display text-xl font-semibold">
          Capture chain
        </h2>
        <p className="mt-1 text-base text-muted-foreground">
          What the station intends, what the radio was told, and what is actually running.
        </p>
        <CaptureTrace s={s} />
      </section>
    </div>
  );
}

function plainStatusSentence(s: StatusResponse, activeCount: number | undefined): string {
  if (s.capture.running) {
    const freqs =
      activeCount != null
        ? `${activeCount} ${activeCount === 1 ? "frequency" : "frequencies"}`
        : "the airband";
    const mode = s.capture.mode === "scan" ? ", scanning" : "";
    return `Listening on ${freqs}${mode}.`;
  }
  if (s.capture.paused_for_disk) return "Paused until some disk space is freed.";
  return "The station is not listening right now.";
}

function BudgetGauge({ label, budget }: { label: string; budget: BudgetInfo }) {
  const used = budget.daily_cap > 0 ? budget.calls_today / budget.daily_cap : 0;
  return (
    <GaugeBar
      label={`${label} (${budget.provider})`}
      detail={`${budget.calls_today} of ${budget.daily_cap} used`}
      fraction={used}
      tone={budget.remaining <= 0 ? "bad" : used > 0.85 ? "warn" : "good"}
    />
  );
}

function CaptureTrace({ s }: { s: StatusResponse }) {
  const confState = s.trace.rendered_conf.state;
  const confOk = confState === "match" || confState === "not_applicable";
  const processOk = s.trace.process.running;

  const steps = [
    {
      title: "The plan",
      ok: true,
      warn: false,
      body:
        s.trace.db_intent.channels.length > 0
          ? `${s.trace.db_intent.mode === "scan" ? "Scan" : "Listen to"} ${s.trace.db_intent.channels
              .map((c) => `${c.label} (${mhz(c.mhz)})`)
              .join(", ")}.`
          : "No frequencies are switched on.",
    },
    {
      title: "The radio's instructions",
      ok: confOk,
      warn: confState === "stale",
      body:
        confState === "match"
          ? "Up to date with the plan."
          : confState === "stale"
            ? "Out of date — the radio is still following older instructions. Toggling any frequency rewrites them."
            : confState === "missing"
              ? "Not written yet — they are generated the first time capture starts."
              : "Not needed while the station replays recordings instead of using the radio.",
    },
    {
      title: "The radio process",
      ok: processOk,
      warn: false,
      body: s.trace.process.detail,
    },
  ];

  return (
    <ol className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-stretch sm:gap-0">
      {steps.map((step, index) => (
        <li key={step.title} className="flex flex-1 items-stretch">
          <div
            className={cn(
              "flex-1 rounded-xl border bg-card p-4",
              !step.ok && !step.warn && "border-health-bad/40",
              step.warn && "border-health-warn/40",
            )}
          >
            <div className="flex items-center gap-2">
              {step.ok ? (
                <CircleCheck className="size-5 text-health-good" aria-hidden />
              ) : step.warn ? (
                <CircleAlert className="size-5 text-health-warn" aria-hidden />
              ) : (
                <CircleX className="size-5 text-health-bad" aria-hidden />
              )}
              <h3 className="text-base font-semibold">{step.title}</h3>
            </div>
            <p className="mt-2 text-base text-muted-foreground">{step.body}</p>
          </div>
          {index < steps.length - 1 && (
            <ArrowRight
              className="mx-2 hidden size-5 self-center text-muted-foreground sm:block"
              aria-hidden
            />
          )}
        </li>
      ))}
    </ol>
  );
}
