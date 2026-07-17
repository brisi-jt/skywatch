"use client";

import { X } from "lucide-react";
import React, { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { BENCH_COPY, EXPLAIN_ITEMS } from "@/lib/tuning-copy";

/**
 * The "What do these do?" mode: the bench dims, numbered badges appear on
 * each section, and this panel walks through them in plain English.
 *
 * Rendering the badges is the bench's job (they must sit beside the dimmed
 * content); this component is the copy panel plus the mode's keyboard exit.
 */
export function ExplainOverlay({
  open,
  onClose,
  onReplayWalkthrough,
}: {
  open: boolean;
  onClose: () => void;
  onReplayWalkthrough: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <aside
      role="dialog"
      aria-label="What the tuning levers do"
      className="fixed inset-y-0 right-0 z-30 flex w-full max-w-md flex-col border-l bg-popover shadow-xl"
    >
      <header className="flex items-center justify-between gap-2 border-b px-5 py-4">
        <h2 className="font-display text-xl font-semibold">{BENCH_COPY.explainToggle}</h2>
        <Button variant="ghost" size="icon-lg" onClick={onClose} aria-label={BENCH_COPY.explainClose}>
          <X aria-hidden />
        </Button>
      </header>

      <ol className="flex-1 overflow-y-auto px-5 py-4">
        {EXPLAIN_ITEMS.map((item) => (
          <li key={item.number} className="flex gap-3 py-3">
            <span
              aria-hidden
              className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-interesting font-mono text-sm font-semibold text-interesting-foreground"
            >
              {item.number}
            </span>
            <div>
              <h3 className="text-base font-semibold">{item.title}</h3>
              <p className="mt-1 text-base text-muted-foreground">{item.body}</p>
            </div>
          </li>
        ))}
      </ol>

      <footer className="flex flex-wrap items-center justify-between gap-2 border-t px-5 py-4">
        <span className="text-sm text-muted-foreground">{BENCH_COPY.explainFooterNote}</span>
        <Button variant="outline" size="sm" className="min-h-10" onClick={onReplayWalkthrough}>
          {BENCH_COPY.explainFooterAction}
        </Button>
      </footer>
    </aside>
  );
}

/** The numbered badge a bench section wears while the overlay is open. */
export function ExplainBadge({ number, active }: { number: number; active: boolean }) {
  if (!active) return null;
  return (
    <span
      aria-hidden
      className="absolute -left-2 -top-2 z-20 flex size-8 items-center justify-center rounded-full bg-interesting font-mono text-base font-semibold text-interesting-foreground shadow-md"
    >
      {number}
    </span>
  );
}
