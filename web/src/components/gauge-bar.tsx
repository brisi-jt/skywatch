import { cn } from "@/lib/utils";

/** A plain horizontal gauge — no dials on this flight deck. */
export function GaugeBar({
  label,
  detail,
  fraction,
  tone = "good",
}: {
  label: string;
  detail: string;
  /** 0..1 fill. */
  fraction: number;
  tone?: "good" | "warn" | "bad";
}) {
  const clamped = Math.max(0, Math.min(1, fraction));
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-4">
        <span className="text-base font-medium">{label}</span>
        <span className="font-mono text-sm text-readout">{detail}</span>
      </div>
      <div
        className="h-2.5 overflow-hidden rounded-full bg-muted"
        role="meter"
        aria-label={label}
        aria-valuenow={Math.round(clamped * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={cn(
            "h-full rounded-full",
            tone === "good" && "bg-health-good",
            tone === "warn" && "bg-health-warn",
            tone === "bad" && "bg-health-bad",
          )}
          style={{ width: `${clamped * 100}%` }}
        />
      </div>
    </div>
  );
}
