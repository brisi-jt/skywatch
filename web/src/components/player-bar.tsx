"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Pause, Play, RotateCcw, RotateCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { durationLabel } from "@/lib/format";
import { usePlayer, type PlaybackRate } from "@/lib/player";
import { cn } from "@/lib/utils";

const RATES: PlaybackRate[] = [1, 0.75, 0.5];

/** Persistent bottom player. Slides in on first play and stays for the session. */
export function PlayerBar() {
  const player = usePlayer();
  const reducedMotion = useReducedMotion();

  return (
    <AnimatePresence>
      {player.clip && (
        <motion.div
          initial={reducedMotion ? false : { y: 96, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={reducedMotion ? undefined : { y: 96, opacity: 0 }}
          transition={{ type: "tween", ease: [0.16, 1, 0.3, 1], duration: 0.35 }}
          className="fixed inset-x-0 bottom-0 z-40 border-t bg-card/95 backdrop-blur-sm"
          role="region"
          aria-label="Audio player"
        >
          <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6">
            <Button
              size="icon"
              className="size-12 rounded-full"
              onClick={player.toggle}
              aria-label={player.playing ? "Pause" : "Play"}
            >
              {player.playing ? <Pause className="size-6" /> : <Play className="size-6 translate-x-0.5" />}
            </Button>

            <Button
              variant="ghost"
              size="icon"
              className="size-10"
              onClick={() => player.seekBy(-5)}
              aria-label="Back 5 seconds"
            >
              <RotateCcw className="size-5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="size-10"
              onClick={() => player.seekBy(5)}
              aria-label="Forward 5 seconds"
            >
              <RotateCw className="size-5" />
            </Button>

            <div className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-base font-medium">{player.clip.title}</span>
              <span className="truncate font-mono text-sm text-readout">{player.clip.subtitle}</span>
            </div>

            <div className="flex w-full items-center gap-3 sm:w-auto sm:min-w-72 sm:flex-1">
              <span className="font-mono text-sm text-muted-foreground tabular-nums">
                {durationLabel(player.position)}
              </span>
              <input
                type="range"
                min={0}
                max={Math.max(player.duration, 0.1)}
                step={0.1}
                value={Math.min(player.position, player.duration || 0)}
                onChange={(event) => player.seekTo(Number(event.target.value))}
                aria-label="Seek"
                className="h-10 flex-1 accent-(--interesting)"
              />
              <span className="font-mono text-sm text-muted-foreground tabular-nums">
                {durationLabel(player.duration)}
              </span>
            </div>

            <div className="flex gap-1" role="group" aria-label="Playback speed">
              {RATES.map((rate) => (
                <button
                  key={rate}
                  type="button"
                  onClick={() => player.setRate(rate)}
                  className={cn(
                    "min-h-10 rounded-md px-2.5 font-mono text-sm transition-colors",
                    player.rate === rate
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-accent/60",
                  )}
                >
                  {rate}×
                </button>
              ))}
            </div>
          </div>
          {player.error && (
            <p className="mx-auto w-full max-w-5xl px-4 pb-2 text-sm text-health-bad sm:px-6">
              {player.error}
            </p>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
