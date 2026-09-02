"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const reducedMotion = useReducedMotion();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  const dark = mounted && resolvedTheme === "dark";

  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-10 overflow-hidden"
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      onClick={() => setTheme(dark ? "light" : "dark")}
    >
      <AnimatePresence initial={false} mode="wait">
        <motion.span
          key={dark ? "sun" : "moon"}
          initial={reducedMotion ? false : { rotate: -90, scale: 0.4, opacity: 0 }}
          animate={{ rotate: 0, scale: 1, opacity: 1 }}
          exit={reducedMotion ? undefined : { rotate: 90, scale: 0.4, opacity: 0 }}
          transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
          className="flex items-center justify-center"
        >
          {dark ? <Sun className="size-5" /> : <Moon className="size-5" />}
        </motion.span>
      </AnimatePresence>
    </Button>
  );
}

/** A brief full-bleed cross-fade on theme change — not the View Transitions API. */
export function ThemeWash() {
  const { resolvedTheme } = useTheme();
  const prev = useRef<string | undefined>(undefined);
  const [washKey, setWashKey] = useState<number | null>(null);

  useEffect(() => {
    if (prev.current !== undefined && prev.current !== resolvedTheme) {
      setWashKey((k) => (k ?? 0) + 1);
    }
    prev.current = resolvedTheme;
  }, [resolvedTheme]);

  if (washKey === null) return null;
  return (
    <div
      key={washKey}
      aria-hidden
      className="theme-wash pointer-events-none fixed inset-0 z-[60] bg-background"
      onAnimationEnd={() => setWashKey(null)}
    />
  );
}
