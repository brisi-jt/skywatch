"use client";

import { useEffect, useState } from "react";

/**
 * Tracks the Page Visibility API so a poller can pause while the tab is
 * backgrounded — used by the Sky view's 10 s live-position poll, which has
 * no reason to keep hitting the aggregators while nobody is looking at the
 * map.
 */
export function useIsVisible(): boolean {
  const [visible, setVisible] = useState(
    () => typeof document === "undefined" || document.visibilityState === "visible",
  );

  useEffect(() => {
    const onChange = () => setVisible(document.visibilityState === "visible");
    onChange();
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);

  return visible;
}
