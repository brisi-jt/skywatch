"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Plane } from "lucide-react";

import { useWs } from "@/lib/ws";

/**
 * New arrivals never reshuffle the list under the reader — they wait behind
 * this pill until asked for.
 */
export function NewClipsPill() {
  const { pendingNewClips, foldInNewClips } = useWs();
  const reducedMotion = useReducedMotion();

  return (
    <AnimatePresence>
      {pendingNewClips > 0 && (
        <motion.div
          initial={reducedMotion ? false : { opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reducedMotion ? undefined : { opacity: 0, y: -8 }}
          transition={{ type: "tween", ease: [0.16, 1, 0.3, 1], duration: 0.25 }}
          className="flex justify-center"
        >
          <button
            type="button"
            onClick={foldInNewClips}
            className="flex min-h-10 items-center gap-2 rounded-full bg-interesting-surface px-4 text-base font-medium text-interesting-surface-foreground transition-colors hover:opacity-90"
          >
            <Plane className="size-4" aria-hidden />
            {pendingNewClips === 1 ? "1 new clip" : `${pendingNewClips} new clips`} — show
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
