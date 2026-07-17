"use client";

import { RotateCcw } from "lucide-react";

import { BENCH_COPY } from "@/lib/tuning-copy";

function show(value: number, unit: string): string {
  const text = unit === "dB" ? value.toFixed(1) : `${value > 0 ? "+" : ""}${value}`;
  return `${text} ${unit}`;
}

/** "32.8 → 38.6 dB" — visible only while a lever is staged off its applied value. */
export function DiffChip({
  applied,
  staged,
  unit,
}: {
  applied: number;
  staged: number;
  unit: string;
}) {
  if (applied === staged) return null;
  return (
    <span className="rounded-full bg-interesting-surface px-2.5 py-0.5 font-mono text-sm text-interesting-surface-foreground">
      {show(applied, unit)} → {show(staged, unit)}
    </span>
  );
}

/** A small chip that stages the lever back to its default. */
export function ResetChip({
  current,
  target,
  unit,
  onReset,
  disabled,
  label,
}: {
  current: number;
  target: number;
  unit: string;
  onReset: (value: number) => void;
  disabled?: boolean;
  label?: string;
}) {
  if (current === target) return null;
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onReset(target)}
      title={BENCH_COPY.resetChipTitle}
      className="inline-flex min-h-10 items-center gap-1.5 rounded-full border px-3 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50"
    >
      <RotateCcw className="size-3.5" aria-hidden />
      {label ?? `default ${show(target, unit)}`}
    </button>
  );
}
