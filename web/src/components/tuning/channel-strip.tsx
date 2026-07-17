"use client";

import React, { useCallback, useRef, useState } from "react";

import { RotateCcw } from "lucide-react";

import { Lcd } from "@/components/tuning/lcd";
import { SQUELCH_MAX, SQUELCH_MIN } from "@/components/tuning/squelch-default";
import type { ChannelMeter } from "@/lib/api/client";
import { clockTime, mhz as formatMhz } from "@/lib/format";
import { BENCH_COPY } from "@/lib/tuning-copy";
import { cn } from "@/lib/utils";

/** The meter face spans 0–50 dB SNR — the same scale squelch is set on. */
const METER_MAX_DB = 50;

export type MeterState = "live" | "no-data" | "paused";

export interface BeforeAfter {
  clips: number;
  minutes: number;
  wasPerHour: number | null;
}

/**
 * One frequency's slice of the desk: live S/N meter with the squelch
 * threshold drawn (and adjustable) directly on it, activity numbers, and an
 * amber jewel lamp that strikes when this frequency records a clip.
 */
export function ChannelStrip({
  meter,
  meterState,
  threshold,
  overridden,
  appliedThreshold,
  reset,
  onThreshold,
  onReset,
  lampLit,
  beforeAfter,
  disabled,
}: {
  meter: ChannelMeter;
  meterState: MeterState;
  /** The staged threshold this strip currently obeys (override or default). */
  threshold: number;
  overridden: boolean;
  /** What capture is running with for this strip, for the staged tag. */
  appliedThreshold: number;
  /** Reset chip: shown when this strip's staged state differs from its default. */
  reset: { show: boolean; label: string } | null;
  onThreshold: (snrDb: number) => void;
  onReset: () => void;
  lampLit: boolean;
  beforeAfter: BeforeAfter | null;
  disabled?: boolean;
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);

  const valueFromPointer = useCallback((clientY: number) => {
    const el = trackRef.current;
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    const fraction = Math.min(1, Math.max(0, (rect.bottom - clientY) / (rect.height || 1)));
    return Math.round(fraction * METER_MAX_DB);
  }, []);

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (disabled) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
    const value = valueFromPointer(event.clientY);
    if (value !== null) onThreshold(value);
  };
  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging || disabled) return;
    const value = valueFromPointer(event.clientY);
    if (value !== null) onThreshold(value);
  };
  const handlePointerEnd = () => setDragging(false);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return;
    const stepBy = (delta: number) => {
      event.preventDefault();
      onThreshold(Math.max(SQUELCH_MIN, Math.min(SQUELCH_MAX, Math.round(threshold + delta))));
    };
    if (event.key === "ArrowUp") stepBy(1);
    else if (event.key === "ArrowDown") stepBy(-1);
    else if (event.key === "PageUp") stepBy(5);
    else if (event.key === "PageDown") stepBy(-5);
  };

  const snr = meterState === "live" ? meter.snr_db : null;
  const fillFraction = snr === null ? 0 : Math.min(1, Math.max(0, snr / METER_MAX_DB));
  const thresholdFraction = Math.min(1, Math.max(0, threshold / METER_MAX_DB));

  return (
    <section
      aria-label={`${meter.label} channel strip`}
      className="flex flex-col gap-3 rounded-xl border bg-bench p-4"
    >
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono text-lg font-semibold text-readout">{formatMhz(meter.mhz)}</p>
          <p className="truncate text-sm text-muted-foreground" title={meter.label}>
            {meter.label}
          </p>
        </div>
        <span
          className="jewel-lamp mt-1 size-4 shrink-0 rounded-full"
          data-lit={lampLit}
          role="status"
          aria-label={lampLit ? `${meter.label} is recording a clip` : undefined}
        />
      </header>

      <div className="flex gap-4">
        {/* The meter, with the squelch threshold living ON it. */}
        <div
          ref={trackRef}
          role="slider"
          tabIndex={disabled ? -1 : 0}
          aria-label={`${meter.label} squelch threshold`}
          aria-orientation="vertical"
          aria-valuemin={SQUELCH_MIN}
          aria-valuemax={SQUELCH_MAX}
          aria-valuenow={threshold}
          aria-valuetext={`${threshold.toFixed(1)} decibels above the noise floor${overridden ? ", overriding the station default" : ", the station default"}`}
          aria-disabled={disabled || undefined}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerEnd}
          onPointerCancel={handlePointerEnd}
          onKeyDown={handleKeyDown}
          className={cn(
            "meter-glass relative h-44 w-16 shrink-0 cursor-ns-resize touch-none overflow-hidden rounded-md outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
            disabled && "cursor-default opacity-60",
          )}
        >
          {/* Live SNR, as LED rungs. Height changes only every 15 s. */}
          {snr !== null && (
            <div
              aria-hidden
              className="meter-led-fill absolute inset-x-1.5 bottom-0 origin-bottom motion-safe:transition-transform motion-safe:duration-700 motion-safe:ease-out"
              style={{ height: "100%", transform: `scaleY(${fillFraction})` }}
            />
          )}

          {meterState !== "live" && (
            <p
              className="absolute inset-x-0 top-1/2 -translate-y-1/2 px-1 text-center text-sm text-muted-foreground"
              role="status"
            >
              {meterState === "paused" ? "paused" : "no live data"}
            </p>
          )}

          {/* The squelch threshold line — dashed while inheriting the default. */}
          <div
            aria-hidden
            className="absolute inset-x-0"
            style={{ bottom: `${thresholdFraction * 100}%` }}
          >
            {/* CUSTOM_STYLE: mask dashes the hairline while it inherits the station default */}
            <div
              className={cn(
                "h-0.5 w-full bg-threshold",
                !overridden && "opacity-70 [mask-image:repeating-linear-gradient(90deg,black_0_6px,transparent_6px_10px)]",
              )}
            />
            {/* Generous grab zone around the hairline. */}
            <div className="absolute inset-x-0 -top-5 h-10" />
          </div>
        </div>

        <dl className="flex min-w-0 flex-1 flex-col gap-2 text-sm">
          <div>
            <dt className="panel-label">Squelch</dt>
            <dd className="mt-1 flex flex-wrap items-center gap-2">
              <Lcd
                value={threshold.toFixed(1)}
                unit="dB"
                label={`Squelch threshold ${threshold.toFixed(1)} decibels`}
              />
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-sm",
                  overridden
                    ? "bg-interesting-surface text-interesting-surface-foreground"
                    : "bg-muted text-muted-foreground",
                )}
              >
                {overridden ? BENCH_COPY.overrideTag : BENCH_COPY.inheritsDefault}
              </span>
            </dd>
            {threshold !== appliedThreshold && (
              <p className="mt-1 font-mono text-sm text-interesting-surface-foreground">
                {appliedThreshold.toFixed(1)} → {threshold.toFixed(1)} dB staged
              </p>
            )}
            {reset?.show && (
              <div className="mt-2">
                <button
                  type="button"
                  disabled={disabled}
                  onClick={onReset}
                  title={BENCH_COPY.resetChipTitle}
                  className="inline-flex min-h-10 items-center gap-1.5 rounded-full border px-3 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50"
                >
                  <RotateCcw className="size-3.5" aria-hidden />
                  {reset.label}
                </button>
              </div>
            )}
          </div>

          <div className="mt-auto flex flex-col gap-1 text-muted-foreground">
            <div className="flex justify-between gap-2">
              <dt>Opens</dt>
              <dd className="font-mono text-readout">
                {meterState === "live" && meter.squelch_open_count !== null
                  ? meter.squelch_open_count
                  : "—"}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt>Clips last hour</dt>
              <dd className="font-mono text-readout">{meter.clips_last_hour}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt>Last heard</dt>
              <dd className="font-mono text-readout">
                {meter.last_heard_utc ? clockTime(meter.last_heard_utc) : "—"}
              </dd>
            </div>
          </div>
        </dl>
      </div>

      {beforeAfter && (
        <p className="rounded-md bg-secondary px-3 py-2 text-sm text-secondary-foreground">
          Since your change: {beforeAfter.clips} {beforeAfter.clips === 1 ? "clip" : "clips"} in{" "}
          {beforeAfter.minutes} min
          {beforeAfter.wasPerHour !== null && <> (was {beforeAfter.wasPerHour}/hr)</>}
        </p>
      )}
    </section>
  );
}
