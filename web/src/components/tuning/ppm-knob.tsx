"use client";

import { motion, useReducedMotion } from "framer-motion";

import { DiffChip, ResetChip } from "@/components/tuning/staging-chips";
import { Lcd } from "@/components/tuning/lcd";
import { cn } from "@/lib/utils";

const PPM_MIN = -200;
const PPM_MAX = 200;
/** Visual degrees per ppm; the pointer clamps near full deflection while the LCD carries the truth. */
const DEG_PER_PPM = 6;
const MAX_DEG = 132;

/**
 * The bench's one rotary control: frequency trim in whole ppm. Stepped by
 * design — click the knob's left or right half, or use the arrow keys.
 * Deliberately NOT drag-to-rotate; circular dragging is misery on a trackpad.
 */
export function PpmKnob({
  value,
  applied,
  resetTarget,
  onChange,
  disabled,
}: {
  value: number;
  applied: number;
  resetTarget: number;
  onChange: (ppm: number) => void;
  disabled?: boolean;
}) {
  const reduceMotion = useReducedMotion();
  const step = (delta: number) =>
    onChange(Math.max(PPM_MIN, Math.min(PPM_MAX, value + delta)));

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return;
    if (event.key === "ArrowUp" || event.key === "ArrowRight") {
      event.preventDefault();
      step(1);
    } else if (event.key === "ArrowDown" || event.key === "ArrowLeft") {
      event.preventDefault();
      step(-1);
    } else if (event.key === "PageUp") {
      event.preventDefault();
      step(5);
    } else if (event.key === "PageDown") {
      event.preventDefault();
      step(-5);
    }
  };

  const angle = Math.max(-MAX_DEG, Math.min(MAX_DEG, value * DEG_PER_PPM));

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="panel-label">Frequency trim</span>
        <DiffChip applied={applied} staged={value} unit="ppm" />
        <ResetChip
          current={value}
          target={resetTarget}
          unit="ppm"
          onReset={onChange}
          disabled={disabled}
        />
      </div>

      <div className="flex items-center gap-4">
        <div
          role="spinbutton"
          tabIndex={disabled ? -1 : 0}
          aria-label="Frequency trim"
          aria-valuemin={PPM_MIN}
          aria-valuemax={PPM_MAX}
          aria-valuenow={value}
          aria-valuetext={`${value > 0 ? "+" : ""}${value} parts per million`}
          aria-disabled={disabled || undefined}
          onKeyDown={handleKeyDown}
          className={cn(
            "relative size-20 shrink-0 rounded-full outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
            disabled && "opacity-60",
          )}
        >
          {/* Knurled skirt + dome. */}
          <div className="fader-cap absolute inset-0 rounded-full" aria-hidden />
          {/* CUSTOM_STYLE: layered inset+drop shadow gives the knob dome its turned-metal depth */}
          <motion.div
            aria-hidden
            className="absolute inset-2 rounded-full bg-card shadow-[inset_0_1px_2px_oklch(1_0_0_/_0.4),0_1px_3px_oklch(0_0_0_/_0.3)]"
            animate={{ rotate: angle }}
            transition={reduceMotion ? { duration: 0 } : { type: "spring", stiffness: 700, damping: 35 }}
          >
            <span className="absolute left-1/2 top-1 h-4 w-0.5 -translate-x-1/2 rounded-full bg-threshold" />
          </motion.div>

          {/* Stepped click zones: left = down, right = up. */}
          <button
            type="button"
            disabled={disabled}
            aria-label="Trim 1 ppm down"
            onClick={() => step(-1)}
            className="absolute inset-y-0 left-0 w-1/2 cursor-w-resize rounded-l-full focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
          <button
            type="button"
            disabled={disabled}
            aria-label="Trim 1 ppm up"
            onClick={() => step(1)}
            className="absolute inset-y-0 right-0 w-1/2 cursor-e-resize rounded-r-full focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
        </div>

        <Lcd
          value={`${value > 0 ? "+" : ""}${value}`}
          unit="ppm"
          size="lg"
          className="min-w-24"
          label={`Frequency trim ${value} parts per million`}
        />
      </div>
    </div>
  );
}
