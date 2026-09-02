"use client";

import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

/**
 * A static waveform drawn behind the scrubber. Bars up to the playhead take the
 * signal accent; the rest are the same colour dimmed. Purely decorative — the
 * range input on top stays the interactive control — so it carries no ARIA.
 */
export function Waveform({
  peaks,
  progress,
  className,
}: {
  peaks: number[];
  progress: number;
  className?: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;

    const draw = () => {
      const rect = canvas.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.round(rect.width * dpr);
      canvas.height = Math.round(rect.height * dpr);
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, rect.width, rect.height);
      // Resolve the accent through the element so the browser hands back a
      // colour its own canvas can parse, in either theme.
      const color = getComputedStyle(canvas).color || "#888";
      const n = peaks.length;
      if (n === 0) return;
      const barW = rect.width / n;
      const mid = rect.height / 2;
      for (let i = 0; i < n; i++) {
        const h = Math.max(2, peaks[i] * (rect.height - 2));
        ctx.globalAlpha = i / n <= progress ? 1 : 0.32;
        ctx.fillStyle = color;
        ctx.fillRect(i * barW, mid - h / 2, Math.max(1, barW - 0.5), h);
      }
      ctx.globalAlpha = 1;
    };

    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [peaks, progress]);

  return <canvas ref={ref} aria-hidden className={cn("text-interesting", className)} />;
}
