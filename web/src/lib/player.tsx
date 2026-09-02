"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useReducer,
  useRef,
  useState,
} from "react";

import { audioUrl } from "./api/client";
import { currentItem, emptyQueue, hasNext as queueHasNext, queueReducer } from "./queue";
import { isTypingTarget, shortcutFor } from "./shortcuts";

export interface PlayerClip {
  id: number;
  title: string;
  subtitle: string;
  /** Whether the clip is worth hearing — drives the opt-in earcon. */
  interesting?: boolean;
}

export type PlaybackRate = 1 | 0.75 | 0.5;

interface PlayerState {
  /** The clip shown in the bar. Persists after the queue finishes until dismissed. */
  clip: PlayerClip | null;
  playing: boolean;
  position: number;
  duration: number;
  rate: PlaybackRate;
  error: string | null;
  queueLength: number;
  hasNext: boolean;
  hasPrev: boolean;
  /** Play a single clip (no queue), e.g. a greatest-hit. */
  play: (clip: PlayerClip) => void;
  /** Seed the queue from an ordered list and start at one clip. */
  playQueue: (clips: PlayerClip[], startId: number) => void;
  toggle: () => void;
  next: () => void;
  prev: () => void;
  seekBy: (seconds: number) => void;
  seekTo: (seconds: number) => void;
  setRate: (rate: PlaybackRate) => void;
  /** Close the player bar and stop playback. */
  dismiss: () => void;
  /** Scroll the currently-playing clip's card into view, if it is on the page. */
  jumpToPlaying: () => void;
}

const PlayerContext = createContext<PlayerState | null>(null);

export function usePlayer(): PlayerState {
  const state = useContext(PlayerContext);
  if (!state) throw new Error("usePlayer requires PlayerProvider");
  return state;
}

/** DOM id for a clip card, so the player can scroll to what is playing. */
export function clipAnchorId(id: number): string {
  return `clip-${id}`;
}

export function PlayerProvider({
  children,
  onReachInteresting,
}: {
  children: React.ReactNode;
  /** Called when playback lands on an interesting clip (queue advance). */
  onReachInteresting?: (clip: PlayerClip) => void;
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [queue, dispatch] = useReducer(queueReducer, emptyQueue);
  const [clip, setClip] = useState<PlayerClip | null>(null);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [rate, setRateState] = useState<PlaybackRate>(1);
  const [error, setError] = useState<string | null>(null);
  const [playToken, setPlayToken] = useState(0);

  const current = currentItem(queue);
  const currentId = current?.id ?? null;
  const currentRef = useRef(current);
  currentRef.current = current;
  const loadedIdRef = useRef<number | null>(null);
  const rateRef = useRef<PlaybackRate>(rate);
  rateRef.current = rate;

  const ensureAudio = useCallback(() => {
    if (!audioRef.current) {
      const audio = new Audio();
      audio.preload = "metadata";
      audio.addEventListener("timeupdate", () => setPosition(audio.currentTime));
      audio.addEventListener("durationchange", () => {
        setDuration(Number.isFinite(audio.duration) ? audio.duration : 0);
      });
      audio.addEventListener("play", () => setPlaying(true));
      audio.addEventListener("pause", () => setPlaying(false));
      audio.addEventListener("ended", () => {
        setPlaying(false);
        // Hands-free: fall through to the next clip in the queue, if any.
        dispatch({ type: "advance" });
      });
      audio.addEventListener("error", () => {
        setPlaying(false);
        setError("This clip's audio could not be loaded.");
      });
      audioRef.current = audio;
    }
    return audioRef.current;
  }, []);

  // Single source of playback: whenever the current queue item or a play
  // request changes, load (if needed) and play. Toggling pause never touches
  // these deps, so it does not restart the clip.
  useEffect(() => {
    const item = currentRef.current;
    if (!item) return;
    const audio = ensureAudio();
    setClip(item);
    if (item.id !== loadedIdRef.current) {
      audio.src = audioUrl(item.id);
      audio.playbackRate = rateRef.current;
      loadedIdRef.current = item.id;
      setPosition(0);
      setDuration(0);
      setError(null);
    } else if (audio.ended) {
      audio.currentTime = 0;
    }
    void audio.play();
  }, [currentId, playToken, ensureAudio]);

  const bump = useCallback(() => setPlayToken((t) => t + 1), []);

  const play = useCallback(
    (next: PlayerClip) => {
      setError(null);
      dispatch({ type: "seed", items: [next], startId: next.id });
      bump();
    },
    [bump],
  );

  const playQueue = useCallback(
    (clips: PlayerClip[], startId: number) => {
      if (clips.length === 0) return;
      setError(null);
      dispatch({ type: "seed", items: clips, startId });
      bump();
    },
    [bump],
  );

  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || !clip) return;
    if (audio.paused) void audio.play();
    else audio.pause();
  }, [clip]);

  const next = useCallback(() => {
    if (!queueHasNext(queue)) return;
    dispatch({ type: "advance" });
    bump();
  }, [queue, bump]);

  const prev = useCallback(() => {
    if (queue.index <= 0) return;
    dispatch({ type: "back" });
    bump();
  }, [queue.index, bump]);

  const seekBy = useCallback((seconds: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = Math.max(0, Math.min(audio.duration || 0, audio.currentTime + seconds));
  }, []);

  const seekTo = useCallback((seconds: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = seconds;
  }, []);

  const setRate = useCallback((next: PlaybackRate) => {
    setRateState(next);
    if (audioRef.current) audioRef.current.playbackRate = next;
  }, []);

  const dismiss = useCallback(() => {
    audioRef.current?.pause();
    loadedIdRef.current = null;
    dispatch({ type: "clear" });
    setClip(null);
    setPlaying(false);
    setPosition(0);
    setDuration(0);
  }, []);

  const jumpToPlaying = useCallback(() => {
    if (!clip) return;
    const el = document.getElementById(clipAnchorId(clip.id));
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [clip]);

  // Earcon on hands-free arrival at an interesting clip (never on the very
  // first, user-initiated play — only on queue advance).
  const prevIdRef = useRef<number | null>(null);
  useEffect(() => {
    const item = currentRef.current;
    const landedOnNew = item?.id != null && item.id !== prevIdRef.current;
    if (landedOnNew && prevIdRef.current != null && item?.interesting) {
      onReachInteresting?.(item);
    }
    if (item?.id != null) prevIdRef.current = item.id;
  }, [currentId, onReachInteresting]);

  // Global keyboard shortcuts, guarded against form fields.
  const actionsRef = useRef({ toggle, seekBy, next, prev });
  actionsRef.current = { toggle, seekBy, next, prev };
  const hasClipRef = useRef(false);
  hasClipRef.current = clip != null;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target as HTMLElement)) return;
      const action = shortcutFor(event.key);
      if (!action || !hasClipRef.current) return;
      event.preventDefault();
      const a = actionsRef.current;
      if (action === "toggle") a.toggle();
      else if (action === "back5") a.seekBy(-5);
      else if (action === "forward5") a.seekBy(5);
      else if (action === "next") a.next();
      else if (action === "prev") a.prev();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(
    () => () => {
      audioRef.current?.pause();
    },
    [],
  );

  return (
    <PlayerContext.Provider
      value={{
        clip,
        playing,
        position,
        duration,
        rate,
        error,
        queueLength: queue.items.length,
        hasNext: queueHasNext(queue),
        hasPrev: queue.index > 0,
        play,
        playQueue,
        toggle,
        next,
        prev,
        seekBy,
        seekTo,
        setRate,
        dismiss,
        jumpToPlaying,
      }}
    >
      {children}
    </PlayerContext.Provider>
  );
}
