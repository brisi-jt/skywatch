"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import React, { useEffect, useState } from "react";

import { useStatus } from "@/lib/api/hooks";
import { setDisplayZone } from "@/lib/format";
import { PlayerProvider } from "@/lib/player";
import { WsProvider } from "@/lib/ws";

/** Keeps the date/time formatters on the station's own timezone (from /status). */
function ZoneSync() {
  const { data } = useStatus();
  useEffect(() => {
    setDisplayZone(data?.timezone);
  }, [data?.timezone]);
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
        <WsProvider>
          <PlayerProvider>{children}</PlayerProvider>
        </WsProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
