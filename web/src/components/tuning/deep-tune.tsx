"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Radar, TriangleAlert } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";

import { ExplainBadge } from "@/components/tuning/explain-overlay";
import { SpectrumScope } from "@/components/tuning/scope";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { DeepTuneState, TuningResponse } from "@/lib/api/client";
import {
  ApiError,
  usePingDeepTune,
  useStartDeepTune,
  useStopDeepTune,
} from "@/lib/api/hooks";
import { durationLabel, ensureUtc } from "@/lib/format";
import { DEEP_TUNE_COPY } from "@/lib/tuning-copy";
import { useWs, type DeepTuneStateEvent } from "@/lib/ws";
import { cn } from "@/lib/utils";

/** Floor between interaction pings — well inside the server's ten-minute countdown. */
const PING_THROTTLE_MS = 20_000;

function stoppedNotice(reason: DeepTuneStateEvent["reason"]): string {
  switch (reason) {
    case "idle_timeout":
      return DEEP_TUNE_COPY.resumedIdle;
    case "connection_lost":
      return DEEP_TUNE_COPY.resumedConnectionLost;
    case "error":
      return DEEP_TUNE_COPY.resumedError;
    default:
      return DEEP_TUNE_COPY.resumedRequested;
  }
}

/**
 * The bench's doorway into Deep Tune, and the whole session's UX: the
 * confirm-the-cost dialog, the off-air banner with its elapsed clock, the
 * scope, the idle warning, and the capture-restart note on every exit path.
 *
 * The server owns the session; this component follows `deep_tune.state`
 * events and keeps the shared /tuning cache in step so the rest of the bench
 * (Apply, most visibly) reacts in the same breath.
 */
export function DeepTuneSection({
  deepTune,
  replayMode,
  dim,
}: {
  deepTune: DeepTuneState;
  replayMode: boolean;
  dim: boolean;
}) {
  const queryClient = useQueryClient();
  const { onDeepTuneState } = useWs();
  const start = useStartDeepTune();
  const stop = useStopDeepTune();
  const ping = usePingDeepTune();

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [warning, setWarning] = useState<DeepTuneStateEvent | null>(null);
  const [stopNotice, setStopNotice] = useState<string | null>(null);

  const active = deepTune.active;

  // Follow the session's own announcements; the cache is the bench's truth.
  useEffect(
    () =>
      onDeepTuneState((event) => {
        if (event.state === "warning") {
          setWarning(event);
          return;
        }
        setWarning(null);
        queryClient.setQueryData<TuningResponse>(["tuning"], (old) =>
          old
            ? {
                ...old,
                deep_tune: {
                  active: event.state === "started",
                  started_at: event.state === "started" ? event.started_at : null,
                  seconds_remaining_before_timeout: null,
                },
              }
            : old,
        );
        if (event.state === "stopped") {
          setStopNotice(stoppedNotice(event.reason));
          queryClient.invalidateQueries({ queryKey: ["status"] });
          queryClient.invalidateQueries({ queryKey: ["tuning-meters"] });
        } else {
          setStopNotice(null);
        }
      }),
    [onDeepTuneState, queryClient],
  );

  // Interaction keep-alive: any lever or mouse activity on the bench counts,
  // throttled so a busy hand does not become a stream of requests.
  const lastPing = useRef(0);
  useEffect(() => {
    if (!active) return;
    const maybePing = () => {
      const now = Date.now();
      if (now - lastPing.current < PING_THROTTLE_MS) return;
      lastPing.current = now;
      ping.mutate();
    };
    document.addEventListener("pointerdown", maybePing);
    document.addEventListener("pointermove", maybePing);
    document.addEventListener("keydown", maybePing);
    return () => {
      document.removeEventListener("pointerdown", maybePing);
      document.removeEventListener("pointermove", maybePing);
      document.removeEventListener("keydown", maybePing);
    };
  }, [active, ping]);

  const handleStart = () => {
    setConfirmOpen(false);
    setUnavailable(null);
    setStopNotice(null);
    start.mutate(undefined, {
      onError: (error) => {
        if (error instanceof ApiError && error.problem?.code === "deep_tune_active") {
          // another tab got there first; the invalidation shows its session
          return;
        }
        setUnavailable(
          error instanceof ApiError && error.problem?.detail
            ? `${DEEP_TUNE_COPY.unavailableLead} ${error.problem.detail}.`
            : DEEP_TUNE_COPY.unavailableLead,
        );
      },
    });
  };

  const handleStop = () => {
    setWarning(null);
    stop.mutate(undefined, {
      // the response returns after capture is already back on air
      onSuccess: () => setStopNotice(DEEP_TUNE_COPY.resumedRequested),
      onError: () => setStopNotice(null),
    });
  };

  const handleKeepGoing = () => {
    lastPing.current = Date.now();
    ping.mutate();
    setWarning(null);
  };

  return (
    <>
      {active && (
        <OffAirBanner
          startedAt={deepTune.started_at ?? null}
          stopping={stop.isPending}
          onExit={handleStop}
        />
      )}

      {warning && active && (
        <div
          role="alert"
          className="fixed bottom-6 right-6 z-40 max-w-sm rounded-xl border border-health-warn/50 bg-health-warn-surface p-4 shadow-xl"
        >
          <p className="flex items-start gap-2 text-base">
            <TriangleAlert className="mt-0.5 size-5 shrink-0 text-health-warn" aria-hidden />
            {DEEP_TUNE_COPY.idleWarning}
          </p>
          <div className="mt-3 flex justify-end">
            <Button size="sm" className="min-h-10" onClick={handleKeepGoing}>
              {DEEP_TUNE_COPY.keepGoing}
            </Button>
          </div>
        </div>
      )}

      <section
        aria-label="Deep tune"
        className="relative rounded-xl border bg-bench p-5"
        data-walkthrough="deep-tune"
      >
        <ExplainBadge number={7} active={dim} />
        <div className={cn(dim && "pointer-events-none opacity-40")}>
          <div className="flex flex-wrap items-start gap-3">
            <div className="min-w-0 flex-1">
              <h2 className="flex items-center gap-2 font-display text-xl font-semibold">
                <Radar className="size-5 text-interesting" aria-hidden />
                {DEEP_TUNE_COPY.sectionTitle}
              </h2>
              <p className="mt-1 max-w-prose text-base text-muted-foreground">
                {DEEP_TUNE_COPY.sectionLead}
              </p>
            </div>
            {!active && (
              <Button
                variant="outline"
                size="lg"
                onClick={() => setConfirmOpen(true)}
                disabled={replayMode || start.isPending}
              >
                {DEEP_TUNE_COPY.openButton}
              </Button>
            )}
          </div>

          {replayMode && !active && (
            <p className="mt-2 text-sm text-muted-foreground">
              {DEEP_TUNE_COPY.unavailableLead} This station is replaying old recordings rather
              than listening with a radio, so there is no live spectrum to show.
            </p>
          )}

          {start.isPending && (
            <p role="status" className="mt-3 text-base text-muted-foreground">
              {DEEP_TUNE_COPY.starting}
            </p>
          )}

          {unavailable && !active && (
            <p role="status" className="mt-3 text-base text-health-warn">
              {unavailable}
            </p>
          )}

          {stopNotice && !active && (
            <p role="status" className="mt-3 text-base text-health-good">
              {stopNotice}
            </p>
          )}

          {stop.isPending && (
            <p role="status" className="mt-3 text-base text-muted-foreground">
              {DEEP_TUNE_COPY.exiting}
            </p>
          )}

          {active && (
            <div className="mt-4">
              <SpectrumScope />
            </div>
          )}
        </div>
      </section>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="font-display text-2xl">
              {DEEP_TUNE_COPY.confirmTitle}
            </DialogTitle>
            <DialogDescription className="text-base">
              {DEEP_TUNE_COPY.confirmBody}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" size="lg" onClick={() => setConfirmOpen(false)}>
              {DEEP_TUNE_COPY.confirmCancel}
            </Button>
            <Button size="lg" onClick={handleStart}>
              {DEEP_TUNE_COPY.confirmAction}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/** The persistent amber banner: the station is off the air, and for how long. */
function OffAirBanner({
  startedAt,
  stopping,
  onExit,
}: {
  startedAt: string | null;
  stopping: boolean;
  onExit: () => void;
}) {
  const [, tick] = useState(0);
  useEffect(() => {
    const interval = setInterval(() => tick((n) => n + 1), 1_000);
    return () => clearInterval(interval);
  }, []);

  const elapsedSeconds = startedAt
    ? Math.max(0, (Date.now() - new Date(ensureUtc(startedAt)).getTime()) / 1_000)
    : 0;

  return (
    <div
      role="status"
      className="sticky top-4 z-30 flex flex-wrap items-center gap-3 rounded-xl border border-health-warn/50 bg-health-warn-surface px-4 py-3 shadow-lg"
    >
      <TriangleAlert className="size-5 shrink-0 text-health-warn" aria-hidden />
      <p className="text-base font-medium">{DEEP_TUNE_COPY.offAirBanner}</p>
      <p className="font-mono text-base text-health-warn">
        {DEEP_TUNE_COPY.offAirElapsed} {durationLabel(elapsedSeconds)}
      </p>
      <Button
        variant="outline"
        size="sm"
        className="ml-auto min-h-10"
        onClick={onExit}
        disabled={stopping}
      >
        {stopping ? "Exiting…" : DEEP_TUNE_COPY.exitButton}
      </Button>
    </div>
  );
}
