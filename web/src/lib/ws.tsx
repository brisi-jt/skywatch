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

/** One channel's readout inside a deep tune spectrum frame. */
export interface SpectrumChannelReading {
  freq_id: number;
  label: string;
  mhz: number;
  /** Null when the channel sits outside the receiver's window. */
  power_db: number | null;
  snr_db: number | null;
}

/** A `spectrum.frame` payload: one sweep of the deep tune scope. */
export interface SpectrumFrame {
  start_mhz: number;
  stop_mhz: number;
  bin_hz: number;
  db: number[];
  noise_floor_db: number;
  channels: SpectrumChannelReading[];
  ts: string;
}

/** A `deep_tune.state` payload: the session announcing its lifecycle. */
export interface DeepTuneStateEvent {
  state: "started" | "warning" | "stopped";
  reason: "requested" | "idle_timeout" | "connection_lost" | "error" | null;
  started_at: string | null;
  seconds_remaining: number | null;
}

interface WsState {
  connected: boolean;
  /** Clips that arrived over the stream but are not folded into lists yet. */
  pendingNewClips: number;
  /** Fold pending arrivals in: refetch the lists, clear the pill. */
  foldInNewClips: () => void;
  /**
   * Be told about each new clip as it lands (payload: the list-item summary).
   * Returns an unsubscribe function. Used by the tuning bench's jewel lamps;
   * listeners must be cheap — they run on the socket's message path.
   */
  onNewRecording: (listener: (summary: RecordingSummary) => void) => () => void;
  /** Spectrum sweeps, flowing only while a deep tune session runs. */
  onSpectrumFrame: (listener: (frame: SpectrumFrame) => void) => () => void;
  /** Deep tune lifecycle events: started, the idle warning, stopped. */
  onDeepTuneState: (listener: (event: DeepTuneStateEvent) => void) => () => void;
}

const WsContext = createContext<WsState>({
  connected: true,
  pendingNewClips: 0,
  foldInNewClips: () => {},
  onNewRecording: () => () => {},
  onSpectrumFrame: () => () => {},
  onDeepTuneState: () => () => {},
});

export function useWs() {
  return useContext(WsContext);
}

interface StreamEvent {
  type:
    | "recording.new"
    | "recording.updated"
    | "status.changed"
    | "spectrum.frame"
    | "deep_tune.state";
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
  const newRecordingListeners = useRef(new Set<(summary: RecordingSummary) => void>());
  const spectrumListeners = useRef(new Set<(frame: SpectrumFrame) => void>());
  const deepTuneListeners = useRef(new Set<(event: DeepTuneStateEvent) => void>());

  const onNewRecording = useCallback((listener: (summary: RecordingSummary) => void) => {
    newRecordingListeners.current.add(listener);
    return () => {
      newRecordingListeners.current.delete(listener);
    };
  }, []);

  const onSpectrumFrame = useCallback((listener: (frame: SpectrumFrame) => void) => {
    spectrumListeners.current.add(listener);
    return () => {
      spectrumListeners.current.delete(listener);
    };
  }, []);

  const onDeepTuneState = useCallback((listener: (event: DeepTuneStateEvent) => void) => {
    deepTuneListeners.current.add(listener);
    return () => {
      deepTuneListeners.current.delete(listener);
    };
  }, []);

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
        const summary = event.payload as RecordingSummary;
        newRecordingListeners.current.forEach((listener) => listener(summary));
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
        return;
      }
      if (event.type === "spectrum.frame") {
        const frame = event.payload as SpectrumFrame;
        spectrumListeners.current.forEach((listener) => listener(frame));
        return;
      }
      if (event.type === "deep_tune.state") {
        const state = event.payload as DeepTuneStateEvent;
        deepTuneListeners.current.forEach((listener) => listener(state));
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
    <WsContext.Provider
      value={{
        connected,
        pendingNewClips,
        foldInNewClips,
        onNewRecording,
        onSpectrumFrame,
        onDeepTuneState,
      }}
    >
      {children}
    </WsContext.Provider>
  );
}
