"use client";

import { motion, useReducedMotion } from "framer-motion";
import React, { useCallback, useEffect, useRef, useState } from "react";

import { DiffChip, ResetChip } from "@/components/tuning/staging-chips";
import { Lcd } from "@/components/tuning/lcd";

/** Pixel gutter so the cap's centre can reach both ends of the scale. */
const CAP_W = 48;
const GUTTER = CAP_W / 2;

/**
 * The gain fader: a full-width slider whose detents are the tuner's real
 * gain steps. The cap moves freely under the pointer and settles onto the
 * nearest detent on release; keyboard moves one detent at a time.
 */
export function GainFader({
  steps,
  value,
  applied,
  resetTarget,
  onChange,
  disabled,
}: {
  /** The tuner's real gain ladder, ascending dB. */
  steps: number[];
  /** Staged value — always one of the steps. */
  value: number;
  /** The value capture is currently running with. */
  applied: number;
  /** Where the reset chip goes: baseline if saved, factory otherwise. */
  resetTarget: number;
  onChange: (db: number) => void;
  disabled?: boolean;
}) {
  const min = steps[0] ?? 0;
  const max = steps[steps.length - 1] ?? 49.6;
  const span = max - min || 1;
  const reduceMotion = useReducedMotion();

  const trackRef = useRef<HTMLDivElement>(null);
  const [trackWidth, setTrackWidth] = useState(0);
  const [dragDb, setDragDb] = useState<number | null>(null);
  const dragging = dragDb !== null;

  useEffect(() => {
    const el = trackRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setTrackWidth(el.clientWidth));
    observer.observe(el);
    setTrackWidth(el.clientWidth);
    return () => observer.disconnect();
  }, []);

  const toFraction = useCallback((db: number) => (db - min) / span, [min, span]);
  const nearestStep = useCallback(
    (db: number) =>
      steps.reduce(
        (best, step) => (Math.abs(step - db) < Math.abs(best - db) ? step : best),
        steps[0] ?? db,
      ),
    [steps],
  );

  const dbFromPointer = useCallback(
    (clientX: number) => {
      const el = trackRef.current;
      if (!el) return value;
      const rect = el.getBoundingClientRect();
      const usable = rect.width - CAP_W;
      const fraction = Math.min(1, Math.max(0, (clientX - rect.left - GUTTER) / (usable || 1)));
      return min + fraction * span;
    },
    [min, span, value],
  );

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (disabled) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragDb(dbFromPointer(event.clientX));
  };
  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging || disabled) return;
    setDragDb(dbFromPointer(event.clientX));
  };
  const handlePointerEnd = () => {
    if (!dragging) return;
    onChange(nearestStep(dragDb ?? value));
    setDragDb(null);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return;
    const index = steps.indexOf(nearestStep(value));
    let next: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowUp") {
      next = steps[Math.min(steps.length - 1, index + 1)] ?? null;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowDown") {
      next = steps[Math.max(0, index - 1)] ?? null;
    } else if (event.key === "Home") {
      next = steps[0] ?? null;
    } else if (event.key === "End") {
      next = steps[steps.length - 1] ?? null;
    }
    if (next !== null) {
      event.preventDefault();
      onChange(next);
    }
  };

  const shownDb = dragging ? (dragDb ?? value) : value;
  const usable = Math.max(0, trackWidth - CAP_W);
  const capX = toFraction(shownDb) * usable;

  const scaleMarks = [0, 10, 20, 30, 40, max];

  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="panel-label">Gain</span>
        <DiffChip applied={applied} staged={value} unit="dB" />
        {/* Compare on the nearest detent: a seeded value between steps is not "moved". */}
        <ResetChip
          current={nearestStep(value)}
          target={resetTarget}
          unit="dB"
          onReset={onChange}
          disabled={disabled}
        />
        <Lcd
          value={shownDb.toFixed(1)}
          unit="dB"
          size="lg"
          className="ml-auto min-w-28"
          label={`Gain ${shownDb.toFixed(1)} decibels`}
        />
      </div>

      <div
        ref={trackRef}
        role="slider"
        tabIndex={disabled ? -1 : 0}
        aria-label="Gain"
        aria-orientation="horizontal"
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={value}
        aria-valuetext={`${value.toFixed(1)} decibels`}
        aria-disabled={disabled || undefined}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerEnd}
        onPointerCancel={handlePointerEnd}
        onKeyDown={handleKeyDown}
        className="relative mt-3 h-14 cursor-pointer touch-none rounded-lg outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-disabled:cursor-default aria-disabled:opacity-60"
      >
        {/* Slot the cap rides in. */}
        <div className="meter-glass absolute inset-x-0 top-1/2 h-2.5 -translate-y-1/2 rounded-full" />

        {/* Detent ticks — one per real tuner step. */}
        {steps.map((step) => (
          <span
            key={step}
            aria-hidden
            className="absolute top-1/2 h-4 w-px -translate-y-1/2 bg-muted-foreground/45"
            style={{ left: `calc(${GUTTER}px + (100% - ${CAP_W}px) * ${toFraction(step)})` }}
          />
        ))}

        {/* The ribbed cap. Snaps to the released detent; silent by design. */}
        <motion.div
          aria-hidden
          className="fader-cap absolute top-1/2 h-11 rounded-md"
          style={{ width: CAP_W, y: "-50%" }}
          animate={{ x: capX }}
          transition={
            dragging || reduceMotion
              ? { duration: 0 }
              : { type: "spring", stiffness: 900, damping: 40, mass: 0.6 }
          }
        >
          <span className="absolute inset-y-1.5 left-1/2 w-0.5 -translate-x-1/2 rounded-full bg-threshold" />
        </motion.div>
      </div>

      {/* dB scale under the slot. */}
      <div aria-hidden className="relative mt-1 h-5 font-mono text-sm text-muted-foreground">
        {scaleMarks.map((mark) => (
          <span
            key={mark}
            className="absolute -translate-x-1/2"
            style={{ left: `calc(${GUTTER}px + (100% - ${CAP_W}px) * ${toFraction(mark)})` }}
          >
            {mark === max ? max.toFixed(1) : mark}
          </span>
        ))}
      </div>
    </div>
  );
}
