"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Radio, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { useHasAnyRecording, useSaveSettings, useSettings } from "@/lib/api/hooks";

/**
 * A once-ever welcome the moment the station's first clip lands. It fires only
 * on the no-clips → first-clip transition within a session; if clips already
 * exist on load (an upgrade) the flag is set silently so it never fires
 * retroactively. The `first_clip_celebrated` setting makes it permanent.
 */
export function FirstClipCelebration() {
  const { data: hasAny } = useHasAnyRecording();
  const { data: settings } = useSettings();
  const save = useSaveSettings();
  const reducedMotion = useReducedMotion();
  const [show, setShow] = useState(false);

  const prev = useRef<boolean | undefined>(undefined);
  const saveRef = useRef(save.mutate);
  saveRef.current = save.mutate;

  useEffect(() => {
    if (hasAny === undefined || settings === undefined || settings.first_clip_celebrated) return;
    const previous = prev.current;
    prev.current = hasAny;
    if (previous === undefined) {
      // First observation this session — backfill the flag if clips already
      // exist so an upgrade never triggers a retroactive celebration.
      if (hasAny) saveRef.current({ first_clip_celebrated: "true" });
      return;
    }
    if (!previous && hasAny) {
      setShow(true);
      saveRef.current({ first_clip_celebrated: "true" });
    }
  }, [hasAny, settings]);

  useEffect(() => {
    if (!show) return;
    const timer = setTimeout(() => setShow(false), 6000);
    return () => clearTimeout(timer);
  }, [show]);

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          className="fixed inset-x-0 bottom-6 z-50 flex justify-center px-4"
          initial={reducedMotion ? { opacity: 0 } : { opacity: 0, y: 24, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={reducedMotion ? { opacity: 0 } : { opacity: 0, y: 24, scale: 0.96 }}
          transition={{ type: "spring", stiffness: 320, damping: 24 }}
          role="status"
        >
          <div className="flex max-w-md items-center gap-4 rounded-xl border border-interesting/40 bg-card px-5 py-4 shadow-lg">
            <span className="relative flex size-10 shrink-0 items-center justify-center">
              <span className="listening-pulse absolute inset-0" aria-hidden />
              <Radio className="size-6 text-interesting" aria-hidden />
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-display text-lg font-semibold">Your first clip just landed</p>
              <p className="text-sm text-muted-foreground">
                The station is alive and listening. Everything it hears will appear here.
              </p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="size-9 shrink-0"
              aria-label="Dismiss"
              onClick={() => setShow(false)}
            >
              <X className="size-5" />
            </Button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
