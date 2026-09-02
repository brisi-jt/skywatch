"use client";

import { useEffect, useRef } from "react";

/**
 * Latches a one-time mount stagger. Returns true only on the first render in
 * which content is ready; every later render (including a WS fold-in that adds
 * clips) returns false, so the list never re-staggers under the reader.
 */
export function useStaggerGate(ready: boolean): boolean {
  const done = useRef(false);
  const should = ready && !done.current;
  useEffect(() => {
    if (ready) done.current = true;
  }, [ready]);
  return should;
}
