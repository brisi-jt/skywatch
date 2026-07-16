"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import React, { useState } from "react";

import { PlayerProvider } from "@/lib/player";
import { WsProvider } from "@/lib/ws";

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
        <WsProvider>
          <PlayerProvider>{children}</PlayerProvider>
        </WsProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
