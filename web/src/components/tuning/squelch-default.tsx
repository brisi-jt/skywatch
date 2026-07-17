"use client";

import { Minus, Plus } from "lucide-react";

import { DiffChip, ResetChip } from "@/components/tuning/staging-chips";
import { Lcd } from "@/components/tuning/lcd";

export const SQUELCH_MIN = 0;
export const SQUELCH_MAX = 50;

/**
 * The station-wide squelch threshold. Channel strips inherit this unless
 * they carry their own override; their amber threshold lines move with it.
 */
export function SquelchDefault({
  value,
  applied,
  resetTarget,
  onChange,
  disabled,
}: {
  value: number;
  applied: number;
  resetTarget: number;
  onChange: (snrDb: number) => void;
  disabled?: boolean;
}) {
  const step = (delta: number) =>
    onChange(Math.max(SQUELCH_MIN, Math.min(SQUELCH_MAX, Math.round(value + delta))));

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="panel-label">Squelch — station default</span>
        <DiffChip applied={applied} staged={value} unit="dB" />
        <ResetChip
          current={value}
          target={resetTarget}
          unit="dB"
          onReset={onChange}
          disabled={disabled}
        />
      </div>
      <div
        className="flex items-center gap-2"
        role="group"
        aria-label="Squelch station default"
      >
        <button
          type="button"
          disabled={disabled || value <= SQUELCH_MIN}
          aria-label="Squelch 1 dB down"
          onClick={() => step(-1)}
          className="flex size-10 items-center justify-center rounded-md border transition-colors hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50"
        >
          <Minus className="size-4" aria-hidden />
        </button>
        <Lcd
          value={value.toFixed(1)}
          unit="dB"
          size="lg"
          className="min-w-24"
          label={`Squelch default ${value.toFixed(1)} decibels above the noise floor`}
        />
        <button
          type="button"
          disabled={disabled || value >= SQUELCH_MAX}
          aria-label="Squelch 1 dB up"
          onClick={() => step(1)}
          className="flex size-10 items-center justify-center rounded-md border transition-colors hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50"
        >
          <Plus className="size-4" aria-hidden />
        </button>
      </div>
      <p className="text-sm text-muted-foreground">
        Recording opens when a signal rises this far above the static.
      </p>
    </div>
  );
}
