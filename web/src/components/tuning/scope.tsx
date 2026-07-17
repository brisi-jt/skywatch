"use client";

import { useReducedMotion } from "framer-motion";
import React, { useCallback, useEffect, useRef, useState } from "react";

import { useWs, type SpectrumFrame } from "@/lib/ws";
import { mhz as formatMhz } from "@/lib/format";
import { DEEP_TUNE_COPY } from "@/lib/tuning-copy";

/** The scope's fixed vertical window, in dB relative to a full-scale carrier. */
const DB_TOP = 0;
const DB_BOTTOM = -100;
/** Graticule spacing: a horizontal line every 10 dB. */
const DB_GRID_STEP = 10;
/** Graticule spacing: a vertical line every quarter MHz. */
const MHZ_GRID_STEP = 0.25;
/** How often the spoken/text summary refreshes — slow enough not to chatter. */
const SUMMARY_INTERVAL_MS = 5_000;

interface ScopeColors {
  screen: string;
  grid: string;
  gridLabel: string;
  trace: string;
  traceFill: string;
  noiseFloor: string;
  marker: string;
}

function readColors(el: HTMLElement): ScopeColors {
  const styles = getComputedStyle(el);
  const v = (name: string) => styles.getPropertyValue(name).trim();
  return {
    screen: v("--scope-screen"),
    grid: v("--scope-grid"),
    gridLabel: v("--scope-grid-label"),
    trace: v("--scope-trace"),
    traceFill: v("--scope-trace-fill"),
    noiseFloor: v("--threshold"),
    marker: v("--threshold"),
  };
}

/**
 * The deep tune scope: an oscilloscope-style spectrum display drawn straight
 * to a canvas, so two frames a second never touch the DOM. The graticule is
 * real — dB lines on the fixed vertical scale, MHz lines placed from the
 * frame's own axis metadata — and every active frequency gets a marker.
 */
export function SpectrumScope() {
  const { onSpectrumFrame } = useWs();
  const reduceMotion = useReducedMotion();

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const shellRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<SpectrumFrame | null>(null);
  const [latest, setLatest] = useState<SpectrumFrame | null>(null);
  const lastRenderedRef = useRef<SpectrumFrame | null>(null);

  // Readouts under the scope re-render per frame (cheap: a handful of rows);
  // the trace itself is canvas-only.
  useEffect(
    () =>
      onSpectrumFrame((frame) => {
        frameRef.current = frame;
        setLatest(frame);
      }),
    [onSpectrumFrame],
  );

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const shell = shellRef.current;
    const frame = frameRef.current;
    if (!canvas || !shell) return;

    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (width === 0 || height === 0) return;
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const colors = readColors(shell);
    const sameFrame = lastRenderedRef.current === frame;

    // Trace persistence: instead of clearing, wash the screen with a
    // translucent coat so the previous sweep glows through — an afterglow.
    // Reduced motion (and resizes, which blank the canvas) get plain redraws.
    if (reduceMotion || sameFrame) {
      ctx.globalAlpha = 1;
      ctx.fillStyle = colors.screen;
      ctx.fillRect(0, 0, width, height);
    } else {
      ctx.globalAlpha = 0.4;
      ctx.fillStyle = colors.screen;
      ctx.fillRect(0, 0, width, height);
      ctx.globalAlpha = 1;
    }
    lastRenderedRef.current = frame;

    const yFor = (db: number) =>
      ((DB_TOP - Math.max(DB_BOTTOM, Math.min(DB_TOP, db))) / (DB_TOP - DB_BOTTOM)) * height;

    // -- graticule ------------------------------------------------------------------
    ctx.lineWidth = 1;
    ctx.strokeStyle = colors.grid;
    ctx.fillStyle = colors.gridLabel;
    ctx.font = "11px ui-monospace, monospace";
    ctx.textBaseline = "top";

    for (let db = DB_TOP - DB_GRID_STEP; db > DB_BOTTOM; db -= DB_GRID_STEP) {
      const y = Math.round(yFor(db)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
      ctx.fillText(`${db}`, 4, y + 2);
    }

    if (frame) {
      const span = frame.stop_mhz - frame.start_mhz;
      const xFor = (mhzValue: number) => ((mhzValue - frame.start_mhz) / span) * width;

      ctx.textBaseline = "bottom";
      const firstTick = Math.ceil(frame.start_mhz / MHZ_GRID_STEP) * MHZ_GRID_STEP;
      for (let tick = firstTick; tick < frame.stop_mhz; tick += MHZ_GRID_STEP) {
        const x = Math.round(xFor(tick)) + 0.5;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
        ctx.fillText(tick.toFixed(2), x + 3, height - 3);
      }

      // -- noise floor ---------------------------------------------------------------
      const floorY = yFor(frame.noise_floor_db);
      ctx.save();
      ctx.strokeStyle = colors.noiseFloor;
      ctx.globalAlpha = 0.6;
      ctx.setLineDash([5, 5]);
      ctx.beginPath();
      ctx.moveTo(0, floorY);
      ctx.lineTo(width, floorY);
      ctx.stroke();
      ctx.restore();
      ctx.fillStyle = colors.gridLabel;
      ctx.textBaseline = "bottom";
      ctx.fillText(DEEP_TUNE_COPY.noiseFloorLabel, width - 78, floorY - 2);

      // -- channel markers -------------------------------------------------------------
      ctx.save();
      ctx.strokeStyle = colors.marker;
      ctx.globalAlpha = 0.5;
      for (const channel of frame.channels) {
        if (channel.mhz < frame.start_mhz || channel.mhz > frame.stop_mhz) continue;
        const x = Math.round(xFor(channel.mhz)) + 0.5;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.fillStyle = colors.marker;
        ctx.beginPath();
        ctx.moveTo(x - 5, 0);
        ctx.lineTo(x + 5, 0);
        ctx.lineTo(x, 7);
        ctx.closePath();
        ctx.fill();
        ctx.globalAlpha = 0.5;
      }
      ctx.restore();

      // -- the trace ---------------------------------------------------------------------
      const bins = frame.db.length;
      if (bins > 1) {
        ctx.beginPath();
        for (let i = 0; i < bins; i += 1) {
          const x = ((i + 0.5) / bins) * width;
          const y = yFor(frame.db[i]);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = colors.trace;
        ctx.lineWidth = 1.5;
        ctx.lineJoin = "round";
        ctx.stroke();

        // A soft skirt under the trace, so peaks read as light, not wire.
        ctx.lineTo(width, height);
        ctx.lineTo(0, height);
        ctx.closePath();
        ctx.fillStyle = colors.traceFill;
        ctx.fill();
      }
    }
  }, [reduceMotion]);

  // One draw per received frame (they arrive ~2.5×/s), plus redraw on resize.
  useEffect(() => {
    draw();
  }, [latest, draw]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const observer = new ResizeObserver(() => draw());
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [draw]);

  // Theme flips swap every CSS variable the canvas paints with.
  useEffect(() => {
    const observer = new MutationObserver(() => draw());
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, [draw]);

  return (
    <div ref={shellRef} className="flex flex-col gap-3">
      <div className="scope-bezel">
        <div className="scope-screen relative">
          <canvas ref={canvasRef} className="block h-64 w-full sm:h-80" aria-hidden />
          {!latest && (
            <p
              role="status"
              className="absolute inset-x-0 top-1/2 -translate-y-1/2 text-center font-mono text-sm text-muted-foreground"
            >
              waiting for the first sweep…
            </p>
          )}
        </div>
      </div>

      {latest && (
        <>
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 font-mono text-sm text-muted-foreground">
            <span>
              {formatMhz(latest.start_mhz)} – {formatMhz(latest.stop_mhz)} MHz
            </span>
            <span>
              {DEEP_TUNE_COPY.noiseFloorLabel} {latest.noise_floor_db.toFixed(1)} dB
            </span>
          </div>

          {/* CUSTOM_STYLE: auto-fill minmax keeps channel readouts desk-width without breakpoints */}
          <ul
            aria-label="Channel readings"
            className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(220px,1fr))]"
          >
            {latest.channels.map((channel) => (
              <li
                key={channel.freq_id}
                className="flex items-baseline justify-between gap-2 rounded-md border bg-card px-3 py-2"
              >
                <span className="min-w-0">
                  <span className="font-mono text-base text-readout">
                    {formatMhz(channel.mhz)}
                  </span>{" "}
                  <span className="block truncate text-sm text-muted-foreground sm:inline">
                    {channel.label}
                  </span>
                </span>
                <span className="shrink-0 font-mono text-sm text-readout">
                  {channel.snr_db !== null ? (
                    <>+{channel.snr_db.toFixed(1)} dB</>
                  ) : (
                    <span className="text-muted-foreground">
                      {DEEP_TUNE_COPY.outsideWindow}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>

          <ScopeSummary frame={latest} />
        </>
      )}
    </div>
  );
}

/**
 * A screen-reader alternative to the trace: one plain sentence per channel,
 * refreshed a few times a minute rather than per sweep.
 */
function ScopeSummary({ frame }: { frame: SpectrumFrame }) {
  const [summary, setSummary] = useState("");
  const frameRef = useRef(frame);
  frameRef.current = frame;

  useEffect(() => {
    const compose = () => {
      const current = frameRef.current;
      const parts = current.channels.map((channel) =>
        channel.snr_db !== null
          ? `${channel.label} at ${formatMhz(channel.mhz)} megahertz reads ${channel.snr_db.toFixed(0)} decibels above the static floor`
          : `${channel.label} at ${formatMhz(channel.mhz)} megahertz sits outside the receiver's window`,
      );
      setSummary(`${DEEP_TUNE_COPY.scopeSummaryLead} ${parts.join("; ")}.`);
    };
    compose();
    const interval = setInterval(compose, SUMMARY_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  return (
    <p aria-live="polite" className="sr-only">
      {summary}
    </p>
  );
}
