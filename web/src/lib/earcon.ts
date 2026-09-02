"use client";

/**
 * A soft, WebAudio-generated chime for interesting clips — no audio asset.
 * Opt-in and off by default; the enabled flag mirrors the station setting.
 * Playing before the listener has interacted with the page may be blocked by
 * the browser's autoplay policy; that is acceptable for a best-effort cue.
 */

let enabled = false;
let ctx: AudioContext | null = null;

export function setEarconEnabled(value: boolean): void {
  enabled = value;
}

export function isEarconEnabled(): boolean {
  return enabled;
}

export function playEarcon(): void {
  if (!enabled || typeof window === "undefined") return;
  try {
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return;
    ctx = ctx ?? new Ctor();
    if (ctx.state === "suspended") void ctx.resume();
    const now = ctx.currentTime;
    // A gentle two-note open interval (E5 → B5), quiet and short.
    [659.25, 987.77].forEach((freq, i) => {
      const osc = ctx!.createOscillator();
      const gain = ctx!.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      const start = now + i * 0.12;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.linearRampToValueAtTime(0.12, start + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.35);
      osc.connect(gain).connect(ctx!.destination);
      osc.start(start);
      osc.stop(start + 0.4);
    });
  } catch {
    // Audio unavailable — the cue is best-effort and silent on failure.
  }
}
