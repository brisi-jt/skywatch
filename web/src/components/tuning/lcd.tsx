import { cn } from "@/lib/utils";

/**
 * An LCD readout window: the bench's way of showing a value. Purely
 * presentational — interaction lives on the control beside it.
 */
export function Lcd({
  value,
  unit,
  size = "md",
  className,
  label,
}: {
  value: string;
  unit?: string;
  size?: "md" | "lg";
  className?: string;
  /** Accessible name when the LCD stands alone (not describing a slider). */
  label?: string;
}) {
  return (
    <span
      aria-label={label}
      className={cn(
        "lcd-window inline-flex items-baseline justify-end gap-1 whitespace-nowrap",
        size === "md" && "px-3 py-1 text-base",
        size === "lg" && "px-4 py-1.5 text-2xl",
        className,
      )}
    >
      <span>{value}</span>
      {unit && <span className="text-sm text-lcd-dim">{unit}</span>}
    </span>
  );
}
