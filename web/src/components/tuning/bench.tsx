"use client";

import { CircleHelp } from "lucide-react";
import React, { useCallback, useEffect, useRef, useState } from "react";

import { ApplyBar, type ApplyBarState } from "@/components/tuning/apply-bar";
import { ChannelStrip, type MeterState } from "@/components/tuning/channel-strip";
import { ExplainBadge, ExplainOverlay } from "@/components/tuning/explain-overlay";
import { GainFader } from "@/components/tuning/gain-fader";
import { Lcd } from "@/components/tuning/lcd";
import { PpmKnob } from "@/components/tuning/ppm-knob";
import { SquelchDefault } from "@/components/tuning/squelch-default";
import { WalkthroughBanner } from "@/components/tuning/walkthrough";
import { Button } from "@/components/ui/button";
import type { AppliedTuning, MetersResponse } from "@/lib/api/client";
import {
  ApiError,
  useApplyTuning,
  useSaveBaseline,
  useSaveSettings,
  useSettings,
  useStatus,
  useTuning,
  useTuningMeters,
} from "@/lib/api/hooks";
import { useWs } from "@/lib/ws";
import { ensureUtc, mhz as formatMhz } from "@/lib/format";
import { BENCH_COPY, CONTEXT_CARDS, WALKTHROUGH_STOPS } from "@/lib/tuning-copy";
import { cn } from "@/lib/utils";

interface Staged {
  gain: number;
  squelch: number;
  ppm: number;
  overrides: Record<number, number>;
}

function stagedFromApplied(applied: AppliedTuning): Staged {
  const overrides: Record<number, number> = {};
  for (const override of applied.squelch_overrides) {
    overrides[override.freq_id] = override.squelch_snr_db;
  }
  return {
    gain: applied.gain_db,
    squelch: applied.squelch_default_snr_db,
    ppm: applied.ppm,
    overrides,
  };
}

function countStagedChanges(staged: Staged, applied: AppliedTuning): number {
  let count = 0;
  if (staged.gain !== applied.gain_db) count += 1;
  if (staged.squelch !== applied.squelch_default_snr_db) count += 1;
  if (staged.ppm !== applied.ppm) count += 1;
  const appliedOverrides = stagedFromApplied(applied).overrides;
  const ids = new Set([
    ...Object.keys(staged.overrides),
    ...Object.keys(appliedOverrides),
  ]);
  for (const id of ids) {
    if (staged.overrides[Number(id)] !== appliedOverrides[Number(id)]) count += 1;
  }
  return count;
}

function nearestStep(steps: number[], db: number): number {
  return steps.reduce(
    (best, step) => (Math.abs(step - db) < Math.abs(best - db) ? step : best),
    steps[0] ?? db,
  );
}

/** How long the jewel lamp holds after a clip lands on its frequency. */
const LAMP_HOLD_MS = 3_000;

export function TuningBench() {
  const status = useStatus();
  const tuning = useTuning();
  const meters = useTuningMeters();
  const settings = useSettings();
  const applyTuning = useApplyTuning();
  const saveBaseline = useSaveBaseline();
  const saveSettings = useSaveSettings();
  const { onNewRecording } = useWs();

  // -- staged lever state ------------------------------------------------------
  const [staged, setStaged] = useState<Staged | null>(null);
  const syncedFrom = useRef<string | null>(null);

  useEffect(() => {
    const applied = tuning.data?.applied;
    if (!applied) return;
    const key = JSON.stringify(applied);
    if (syncedFrom.current === key) return;
    // First load, or the applied values changed underneath us (another tab,
    // an apply): resync unless the reader has levers mid-move.
    if (staged === null || countStagedChanges(staged, applied) === 0 || syncedFrom.current === null) {
      setStaged(stagedFromApplied(applied));
    }
    syncedFrom.current = key;
  }, [tuning.data?.applied, staged]);

  // -- lamps, apply bookkeeping, modes ----------------------------------------
  const [lamps, setLamps] = useState<Record<number, true>>({});
  const lampTimers = useRef<Record<number, ReturnType<typeof setTimeout>>>({});
  useEffect(() => {
    const unsubscribe = onNewRecording((summary) => {
      const freqId = summary.frequency.id;
      setLamps((current) => ({ ...current, [freqId]: true }));
      if (lampTimers.current[freqId]) clearTimeout(lampTimers.current[freqId]);
      lampTimers.current[freqId] = setTimeout(() => {
        setLamps((current) => {
          const next = { ...current };
          delete next[freqId];
          return next;
        });
      }, LAMP_HOLD_MS);
    });
    const timers = lampTimers.current;
    return () => {
      unsubscribe();
      Object.values(timers).forEach(clearTimeout);
    };
  }, [onNewRecording]);

  const [applyError, setApplyError] = useState<string | null>(null);
  const [applyWarnings, setApplyWarnings] = useState<string[]>([]);
  const [justApplied, setJustApplied] = useState(false);
  const [baselineSaved, setBaselineSaved] = useState(false);
  const [showSince, setShowSince] = useState(false);
  const preApplyClipsRate = useRef<Record<number, number>>({});

  const [explainOpen, setExplainOpen] = useState(false);
  const [tourStep, setTourStep] = useState<number | null>(null);
  const tourOffered = useRef(false);

  // Offer the tour once, on the first visit only.
  useEffect(() => {
    if (tourOffered.current) return;
    if (settings.data && !settings.data.tuning_walkthrough_done) {
      tourOffered.current = true;
      setTourStep(0);
    }
  }, [settings.data]);

  const finishTour = useCallback(() => {
    setTourStep(null);
    if (settings.data && !settings.data.tuning_walkthrough_done) {
      saveSettings.mutate({ "tuning.walkthrough_done": "true" });
    }
  }, [settings.data, saveSettings]);

  // -- derived -----------------------------------------------------------------
  const data = tuning.data;
  const applied = data?.applied;
  const dirty = staged !== null && applied ? countStagedChanges(staged, applied) > 0 : false;
  const replayMode = status.data?.capture.source === "replay";

  // Warn before losing staged changes — tab close and in-app navigation alike.
  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    const onClickCapture = (event: MouseEvent) => {
      const anchor = (event.target as HTMLElement).closest?.("a[href]");
      if (!anchor || anchor.getAttribute("target") === "_blank") return;
      const href = anchor.getAttribute("href") ?? "";
      if (!href.startsWith("/")) return;
      if (!window.confirm(BENCH_COPY.unsavedWarning)) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClickCapture, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClickCapture, true);
    };
  }, [dirty]);

  // -- page-level states ---------------------------------------------------------
  if (tuning.isPending || status.isPending) {
    return (
      <div className="flex flex-col gap-4" aria-hidden>
        <div className="h-10 w-64 animate-pulse rounded-md bg-muted" />
        <div className="h-48 animate-pulse rounded-xl border bg-card" />
        <div className="h-72 animate-pulse rounded-xl border bg-card" />
      </div>
    );
  }
  if (tuning.isError || !data || !applied || !staged) {
    return (
      <p className="text-base text-health-bad">
        The tuning bench could not load its settings from the station. Try refreshing; if this
        persists, see “Failure modes” in the Runbook.
      </p>
    );
  }

  const factory = data.factory;
  const baseline = data.baseline;
  const gainResetTarget = nearestStep(
    data.gain_steps_db,
    baseline?.gain_db ?? factory.gain_db,
  );
  const squelchResetTarget = baseline?.squelch_default_snr_db ?? factory.squelch_default_snr_db;
  const ppmResetTarget = baseline?.ppm ?? factory.ppm;
  const baselineOverrides: Record<number, number> = {};
  for (const override of baseline?.squelch_overrides ?? []) {
    baselineOverrides[override.freq_id] = override.squelch_snr_db;
  }
  const appliedOverrides = stagedFromApplied(applied).overrides;

  const applyBlocked = replayMode
    ? BENCH_COPY.replayNote
    : data.deep_tune.active
      ? BENCH_COPY.applyDeepTuneConflict
      : null;

  const handleApply = () => {
    setApplyError(null);
    // Remember each strip's pace before the change, for the "was X/hr" note.
    preApplyClipsRate.current = {};
    for (const channel of meters.data?.channels ?? []) {
      preApplyClipsRate.current[channel.freq_id] = channel.clips_last_hour;
    }
    applyTuning.mutate(
      {
        gain_db: staged.gain,
        squelch_default_snr_db: staged.squelch,
        ppm: staged.ppm,
        squelch_overrides: Object.entries(staged.overrides).map(([freqId, snr]) => ({
          freq_id: Number(freqId),
          squelch_snr_db: snr,
        })),
      },
      {
        onSuccess: (response) => {
          setStaged(stagedFromApplied(response.applied));
          syncedFrom.current = JSON.stringify(response.applied);
          setApplyWarnings(response.warnings);
          setJustApplied(true);
          setBaselineSaved(false);
          setShowSince(true);
        },
        onError: (error) => {
          if (error instanceof ApiError && error.problem?.code === "deep_tune_active") {
            setApplyError(BENCH_COPY.applyDeepTuneConflict);
          } else if (error instanceof ApiError && error.problem?.detail) {
            setApplyError(`${BENCH_COPY.applyFailed} ${error.problem.detail}`);
          } else {
            setApplyError(BENCH_COPY.applyFailed);
          }
        },
      },
    );
  };

  const applyBarState: ApplyBarState = {
    dirty,
    stagedCount: countStagedChanges(staged, applied),
    applying: applyTuning.isPending,
    error: applyError,
    justApplied: justApplied && !dirty,
    savingBaseline: saveBaseline.isPending,
    baselineSaved,
    applyBlocked,
    warnings: applyWarnings,
  };

  const statsState = meters.data?.stats;
  const meterState: MeterState = !statsState?.present
    ? "no-data"
    : statsState.stale
      ? "paused"
      : "live";

  const centerfreq = status.data?.capture.centerfreq_mhz ?? null;
  const captureMode = status.data?.capture.mode ?? null;

  const dim = explainOpen;

  return (
    <div className="flex flex-col gap-8">
      <WalkthroughBanner step={tourStep} onStep={setTourStep} onFinish={finishTour} />

      {/* Header — never dimmed, so the explain toggle stays reachable. */}
      <header className="flex flex-wrap items-start gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight">
            {BENCH_COPY.pageTitle}
          </h1>
          <p className="mt-1 max-w-prose text-base text-muted-foreground">{BENCH_COPY.pageLead}</p>
        </div>
        <Button
          variant="outline"
          size="lg"
          className="ml-auto"
          aria-pressed={explainOpen}
          onClick={() => setExplainOpen((open) => !open)}
        >
          <CircleHelp aria-hidden />
          {BENCH_COPY.explainToggle}
        </Button>
      </header>

      {replayMode && (
        <p className="rounded-xl border bg-secondary px-4 py-3 text-base text-secondary-foreground">
          {BENCH_COPY.replayNote}
        </p>
      )}

      {/* Device row: the dongle's own levers. */}
      <section
        aria-label="Receiver levers"
        className="rounded-xl border bg-bench p-5"
        data-walkthrough="gain"
      >
        <div className={cn("relative", tourStep !== null && WALKTHROUGH_STOPS[tourStep]?.anchor === "gain" && "rounded-lg ring-2 ring-interesting")}>
          <ExplainBadge number={1} active={dim} />
          <div className={cn(dim && "pointer-events-none opacity-40")}>
            <GainFader
              steps={data.gain_steps_db}
              value={staged.gain}
              applied={applied.gain_db}
              resetTarget={gainResetTarget}
              onChange={(db) => setStaged({ ...staged, gain: db })}
            />
          </div>
        </div>

        <div className="mt-8 grid gap-8 sm:grid-cols-2" data-walkthrough="squelch">
          <div className={cn("relative", tourStep !== null && WALKTHROUGH_STOPS[tourStep]?.anchor === "squelch" && "rounded-lg ring-2 ring-interesting")}>
            <ExplainBadge number={2} active={dim} />
            <div className={cn(dim && "pointer-events-none opacity-40")}>
              <SquelchDefault
                value={staged.squelch}
                applied={applied.squelch_default_snr_db}
                resetTarget={squelchResetTarget}
                onChange={(snr) => setStaged({ ...staged, squelch: snr })}
              />
            </div>
          </div>
          <div className="relative">
            <ExplainBadge number={4} active={dim} />
            <div className={cn(dim && "pointer-events-none opacity-40")}>
              <PpmKnob
                value={staged.ppm}
                applied={applied.ppm}
                resetTarget={ppmResetTarget}
                onChange={(ppm) => setStaged({ ...staged, ppm })}
              />
            </div>
          </div>
        </div>
      </section>

      {/* Channel strips. */}
      <section aria-label="Channel strips" data-walkthrough="strips">
        <div className={cn("relative", tourStep !== null && WALKTHROUGH_STOPS[tourStep]?.anchor === "strips" && "rounded-lg ring-2 ring-interesting")}>
          <ExplainBadge number={3} active={dim} />
          <div className={cn(dim && "pointer-events-none opacity-40")}>
            <div className="flex flex-wrap items-baseline gap-3">
              <h2 className="font-display text-xl font-semibold">Channels</h2>
              <div className="relative ml-auto">
                <ExplainBadge number={5} active={dim} />
                <MetersWhisper meters={meters.data} isError={meters.isError} />
              </div>
            </div>

            {meters.isError && (
              <p className="mt-4 text-base text-health-bad">
                The live meters could not be loaded. The levers still work; readings return when
                the station answers again.
              </p>
            )}

            {meters.data && meters.data.channels.length === 0 && (
              <p className="mt-4 max-w-prose text-base text-muted-foreground">
                {BENCH_COPY.noActiveFrequencies}
              </p>
            )}

            {meterState === "no-data" && meters.data && meters.data.channels.length > 0 && (
              <p className="mt-2 text-sm text-muted-foreground">{BENCH_COPY.noStatsYet}</p>
            )}
            {meterState === "paused" && (
              <p className="mt-2 text-sm text-health-warn">{BENCH_COPY.metersPaused}</p>
            )}

            {/* CUSTOM_STYLE: auto-fill minmax keeps strips desk-width without breakpoints */}
            <div className="mt-4 grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(280px,1fr))]">
              {(meters.data?.channels ?? []).map((channel) => {
                const overridden = channel.freq_id in staged.overrides;
                const threshold = staged.overrides[channel.freq_id] ?? staged.squelch;
                const appliedThreshold =
                  appliedOverrides[channel.freq_id] ?? applied.squelch_default_snr_db;
                const baselineOverride = baselineOverrides[channel.freq_id];
                const showReset =
                  baselineOverride !== undefined
                    ? !overridden || threshold !== baselineOverride
                    : overridden;
                const sinceApply = meters.data?.since_last_apply ?? null;
                const beforeAfter =
                  showSince && sinceApply && channel.clips_since_apply !== null
                    ? {
                        clips: channel.clips_since_apply,
                        minutes: Math.max(
                          1,
                          Math.round(
                            (Date.now() - new Date(ensureUtc(sinceApply.applied_at)).getTime()) /
                              60_000,
                          ),
                        ),
                        wasPerHour: preApplyClipsRate.current[channel.freq_id] ?? null,
                      }
                    : null;
                return (
                  <ChannelStrip
                    key={channel.freq_id}
                    meter={channel}
                    meterState={meterState}
                    threshold={threshold}
                    overridden={overridden}
                    appliedThreshold={appliedThreshold}
                    reset={
                      showReset
                        ? {
                            show: true,
                            label:
                              baselineOverride !== undefined
                                ? `default ${baselineOverride.toFixed(1)} dB`
                                : `use ${BENCH_COPY.inheritsDefault}`,
                          }
                        : null
                    }
                    onThreshold={(snr) =>
                      setStaged({
                        ...staged,
                        overrides: { ...staged.overrides, [channel.freq_id]: snr },
                      })
                    }
                    onReset={() => {
                      const overrides = { ...staged.overrides };
                      if (baselineOverride !== undefined) {
                        overrides[channel.freq_id] = baselineOverride;
                      } else {
                        delete overrides[channel.freq_id];
                      }
                      setStaged({ ...staged, overrides });
                    }}
                    lampLit={Boolean(lamps[channel.freq_id])}
                    beforeAfter={beforeAfter}
                  />
                );
              })}
            </div>
          </div>
        </div>
      </section>

      {/* Computed, not tuned. */}
      <section aria-label="Computed settings" className="relative">
        <div className={cn(dim && "pointer-events-none opacity-40")}>
          <h2 className="font-display text-xl font-semibold">Computed, not tuned</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            {CONTEXT_CARDS.map((card) => (
              <div key={card.title} className="rounded-xl border bg-card p-4">
                <div className="flex items-baseline justify-between gap-2">
                  <h3 className="text-base font-semibold">{card.title}</h3>
                  {card.title === "Centre frequency" && (
                    <Lcd
                      value={centerfreq !== null ? formatMhz(centerfreq) : "—"}
                      unit={centerfreq !== null ? "MHz" : undefined}
                    />
                  )}
                  {card.title === "Mode" && captureMode && <Lcd value={captureMode} />}
                </div>
                <p className="mt-2 text-sm text-muted-foreground">{card.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How changes land — the apply model, plus baseline saving at rest. */}
      <section
        aria-label="How changes land"
        className="relative rounded-xl border bg-card p-5"
        data-walkthrough="apply"
      >
        <div className={cn(tourStep !== null && WALKTHROUGH_STOPS[tourStep]?.anchor === "apply" && "rounded-lg ring-2 ring-interesting", "relative")}>
          <ExplainBadge number={6} active={dim} />
          <div className={cn(dim && "pointer-events-none opacity-40")}>
            <h2 className="font-display text-xl font-semibold">How changes land</h2>
            <p className="mt-2 max-w-prose text-base text-muted-foreground">
              Levers only stage changes; Apply rewrites the radio&rsquo;s instructions and
              restarts it, taking the station off the air for about five seconds. Reset chips
              return levers to the saved station defaults
              {baseline ? "." : " — factory values, until you save your own."}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <Button
                variant="outline"
                size="sm"
                className="min-h-10"
                disabled={saveBaseline.isPending || dirty}
                title={dirty ? "Apply or discard the staged changes first." : undefined}
                onClick={() =>
                  saveBaseline.mutate(undefined, { onSuccess: () => setBaselineSaved(true) })
                }
              >
                {saveBaseline.isPending ? "Saving…" : BENCH_COPY.saveBaselineButton}
              </Button>
              <span className="text-sm text-muted-foreground">
                {baseline
                  ? "Station defaults are saved."
                  : "No station defaults saved yet — reset chips use the factory values."}
              </span>
            </div>
          </div>
        </div>
      </section>

      <ApplyBar
        state={applyBarState}
        onApply={handleApply}
        onDiscard={() => {
          setStaged(stagedFromApplied(applied));
          setApplyError(null);
        }}
        onSaveBaseline={() =>
          saveBaseline.mutate(undefined, {
            onSuccess: () => {
              setBaselineSaved(true);
              setApplyWarnings([]);
            },
          })
        }
        onDismiss={() => {
          setJustApplied(false);
          setApplyWarnings([]);
        }}
      />

      <ExplainOverlay
        open={explainOpen}
        onClose={() => setExplainOpen(false)}
        onReplayWalkthrough={() => {
          setExplainOpen(false);
          setTourStep(0);
        }}
      />
    </div>
  );
}

/** "updated 7 s ago" — a whisper that keeps the 15 s meter cadence honest. */
function MetersWhisper({
  meters,
  isError,
}: {
  meters: MetersResponse | undefined;
  isError: boolean;
}) {
  const [, tick] = useState(0);
  useEffect(() => {
    const interval = setInterval(() => tick((n) => n + 1), 1_000);
    return () => clearInterval(interval);
  }, []);

  if (isError || !meters?.stats.present || !meters.stats.updated_at) return null;
  const seconds = Math.max(
    0,
    Math.round((Date.now() - new Date(ensureUtc(meters.stats.updated_at)).getTime()) / 1_000),
  );
  return (
    <span className="text-sm text-muted-foreground" role="status">
      updated {seconds} s ago
    </span>
  );
}
