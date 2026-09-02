"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import React, { useEffect, useState } from "react";

import { useSettings, useStatus } from "@/lib/api/hooks";
import { playEarcon, setEarconEnabled } from "@/lib/earcon";
import { setDisplayZone } from "@/lib/format";
import { PlayerProvider } from "@/lib/player";
import { useWs, WsProvider } from "@/lib/ws";

/** Keeps the date/time formatters on the station's own timezone (from /status). */
function ZoneSync() {
  const { data } = useStatus();
  useEffect(() => {
    setDisplayZone(data?.timezone);
  }, [data?.timezone]);
  return null;
}

/** Mirrors the earcon setting into the audio module. */
function EarconSettingsSync() {
  const { data } = useSettings();
  useEffect(() => {
    setEarconEnabled(data?.earcon_enabled ?? false);
  }, [data?.earcon_enabled]);
  return null;
}

/** Chimes when an interesting clip arrives live (respecting the opt-in flag). */
function LiveArrivalEarcon() {
  const { onNewRecording } = useWs();
  useEffect(
    () =>
      onNewRecording((summary) => {
        if (summary.classification?.is_interesting) playEarcon();
      }),
    [onNewRecording],
  );
  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 10_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false}>
      <QueryClientProvider client={queryClient}>
        <ZoneSync />
        <EarconSettingsSync />
        <WsProvider>
          <LiveArrivalEarcon />
          <PlayerProvider onReachInteresting={() => playEarcon()}>{children}</PlayerProvider>
        </WsProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
