"use client";

import { useQueryClient } from "@tanstack/react-query";
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

import type { RecordingListResponse, RecordingSummary, StatusResponse } from "./api/client";
import { wsUrl } from "./api/client";
import { localDay, todayIso } from "./format";

interface WsState {
  connected: boolean;
  /** Clips that arrived over the stream but are not folded into lists yet. */
  pendingNewClips: number;
  /** Fold pending arrivals in: refetch the lists, clear the pill. */
  foldInNewClips: () => void;
}

const WsContext = createContext<WsState>({
  connected: true,
  pendingNewClips: 0,
  foldInNewClips: () => {},
});

export function useWs() {
  return useContext(WsContext);
}

interface StreamEvent {
  type: "recording.new" | "recording.updated" | "status.changed";
  payload: unknown;
}

/**
 * One WebSocket for the whole app. Events never re-render lists wholesale:
 * new clips only bump a counter (the pill folds them in on request), updates
 * patch cached items in place, and status replaces a single cache entry.
 */
export function WsProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(true);
  const [pendingNewClips, setPendingNewClips] = useState(0);
  const retryRef = useRef(0);

  const foldInNewClips = useCallback(() => {
    setPendingNewClips(0);
    queryClient.invalidateQueries({ queryKey: ["recordings"] });
    queryClient.invalidateQueries({ queryKey: ["recordings-any"] });
    queryClient.invalidateQueries({ queryKey: ["digest", todayIso()] });
  }, [queryClient]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let closed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const handleEvent = (event: StreamEvent) => {
      if (event.type === "recording.new") {
        setPendingNewClips((n) => n + 1);
        // Day-one → first-clip transition must not wait for the pill.
        const hadAny = queryClient.getQueryData<boolean>(["recordings-any"]);
        if (hadAny === false) {
          queryClient.invalidateQueries({ queryKey: ["recordings-any"] });
        }
        return;
      }
      if (event.type === "recording.updated") {
        const summary = event.payload as RecordingSummary;
        patchLists(summary);
        queryClient.invalidateQueries({ queryKey: ["recording", summary.id] });
        if (summary.classification && localDay(summary.started_at_utc) === todayIso()) {
          // A verdict landing today can change the Today digest.
          queryClient.invalidateQueries({ queryKey: ["digest", todayIso()] });
        }
        return;
      }
      if (event.type === "status.changed") {
        queryClient.setQueryData(["status"], event.payload as StatusResponse);
      }
    };

    const patchLists = (summary: RecordingSummary) => {
      queryClient.setQueriesData<{ pages: RecordingListResponse[]; pageParams: number[] }>(
        { queryKey: ["recordings"] },
        (data) => {
          if (!data?.pages) return data;
          let touched = false;
          const pages = data.pages.map((page) => {
            const idx = page.items.findIndex((item) => item.id === summary.id);
            if (idx === -1) return page;
            touched = true;
            const items = [...page.items];
            items[idx] = summary;
            return { ...page, items };
          });
          return touched ? { ...data, pages } : data;
        },
      );
    };

    const connect = () => {
      if (closed) return;
      try {
        socket = new WebSocket(wsUrl());
      } catch {
        scheduleReconnect();
        return;
      }
      socket.onopen = () => {
        retryRef.current = 0;
        setConnected(true);
      };
      socket.onmessage = (message) => {
        try {
          handleEvent(JSON.parse(message.data as string) as StreamEvent);
        } catch {
          // Malformed frames are dropped; the poll loop self-heals state.
        }
      };
      socket.onclose = () => {
        setConnected(false);
        scheduleReconnect();
      };
      socket.onerror = () => {
        socket?.close();
      };
    };

    const scheduleReconnect = () => {
      if (closed) return;
      const delay = Math.min(15_000, 1_000 * 2 ** retryRef.current);
      retryRef.current += 1;
      reconnectTimer = setTimeout(connect, delay);
    };

    connect();
    return () => {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [queryClient]);

  return (
    <WsContext.Provider value={{ connected, pendingNewClips, foldInNewClips }}>
      {children}
    </WsContext.Provider>
  );
}
