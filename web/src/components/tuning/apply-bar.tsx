"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Check, TriangleAlert, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { BENCH_COPY } from "@/lib/tuning-copy";

export interface ApplyBarState {
  dirty: boolean;
  stagedCount: number;
  applying: boolean;
  /** Plain-language problem from the last failed apply, if any. */
  error: string | null;
  /** True right after a successful apply, until dismissed or re-staged. */
  justApplied: boolean;
  savingBaseline: boolean;
  baselineSaved: boolean;
  /** Set when applying is impossible (replay mode); explains why. */
  applyBlocked: string | null;
  /** Non-fatal notes from the last apply, e.g. a restart that failed. */
  warnings: string[];
}

/**
 * The staging desk's master section: slides up whenever there is something
 * to commit, and lingers after an apply to offer "save as defaults".
 */
export function ApplyBar({
  state,
  onApply,
  onDiscard,
  onSaveBaseline,
  onDismiss,
}: {
  state: ApplyBarState;
  onApply: () => void;
  onDiscard: () => void;
  onSaveBaseline: () => void;
  onDismiss: () => void;
}) {
  const reduceMotion = useReducedMotion();
  const visible = state.dirty || state.applying || state.justApplied;

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={reduceMotion ? false : { y: 24, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={reduceMotion ? undefined : { y: 24, opacity: 0 }}
          transition={{ duration: 0.18, ease: "easeOut" }}
          className="sticky bottom-4 z-20 mt-8"
        >
          <div className="rounded-xl border bg-card p-4 shadow-lg">
            {state.justApplied && !state.dirty ? (
              <div className="flex flex-wrap items-center gap-3">
                <p className="flex items-center gap-2 text-base">
                  {state.warnings.length > 0 ? (
                    <TriangleAlert className="size-5 text-health-warn" aria-hidden />
                  ) : (
                    <Check className="size-5 text-health-good" aria-hidden />
                  )}
                  {state.baselineSaved
                    ? BENCH_COPY.baselineSaved
                    : state.warnings.length > 0
                      ? BENCH_COPY.appliedNoRestart
                      : BENCH_COPY.applied}
                </p>
                {state.warnings.map((warning) => (
                  <p key={warning} className="w-full text-sm text-health-warn" role="status">
                    {warning}
                  </p>
                ))}
                <div className="ml-auto flex items-center gap-2">
                  {!state.baselineSaved && (
                    <Button
                      variant="outline"
                      size="lg"
                      onClick={onSaveBaseline}
                      disabled={state.savingBaseline}
                    >
                      {state.savingBaseline ? "Saving…" : BENCH_COPY.saveBaselineButton}
                    </Button>
                  )}
                  <Button variant="ghost" size="icon-lg" onClick={onDismiss} aria-label="Dismiss">
                    <X aria-hidden />
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <p className="text-base">
                  {state.applying ? (
                    <span role="status">{BENCH_COPY.applying}</span>
                  ) : (
                    <>
                      {state.stagedCount} staged{" "}
                      {state.stagedCount === 1 ? "change" : "changes"}
                    </>
                  )}
                </p>
                <div className="ml-auto flex flex-wrap items-center gap-2">
                  <Button variant="ghost" size="lg" onClick={onDiscard} disabled={state.applying}>
                    {BENCH_COPY.discardButton}
                  </Button>
                  <Button
                    size="lg"
                    onClick={onApply}
                    disabled={state.applying || state.applyBlocked !== null}
                  >
                    {BENCH_COPY.applyButton}
                  </Button>
                </div>
                {state.applyBlocked && (
                  <p className="w-full text-sm text-muted-foreground">{state.applyBlocked}</p>
                )}
                {state.error && (
                  <p role="alert" className="w-full text-sm text-health-bad">
                    {state.error}
                  </p>
                )}
              </div>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
