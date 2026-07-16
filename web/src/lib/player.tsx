"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

import { audioUrl } from "./api/client";

export interface PlayerClip {
  id: number;
  title: string;
  subtitle: string;
}

export type PlaybackRate = 1 | 0.75 | 0.5;

interface PlayerState {
  clip: PlayerClip | null;
  playing: boolean;
  position: number;
  duration: number;
  rate: PlaybackRate;
  error: string | null;
  play: (clip: PlayerClip) => void;
  toggle: () => void;
  seekBy: (seconds: number) => void;
  seekTo: (seconds: number) => void;
  setRate: (rate: PlaybackRate) => void;
}

const PlayerContext = createContext<PlayerState | null>(null);

export function usePlayer(): PlayerState {
  const state = useContext(PlayerContext);
  if (!state) throw new Error("usePlayer requires PlayerProvider");
  return state;
}

export function PlayerProvider({ children }: { children: React.ReactNode }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [clip, setClip] = useState<PlayerClip | null>(null);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [rate, setRateState] = useState<PlaybackRate>(1);
  const [error, setError] = useState<string | null>(null);

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
      audio.addEventListener("ended", () => setPlaying(false));
      audio.addEventListener("error", () => {
        setPlaying(false);
        setError("This clip's audio could not be loaded.");
      });
      audioRef.current = audio;
    }
    return audioRef.current;
  }, []);

  const play = useCallback(
    (next: PlayerClip) => {
      const audio = ensureAudio();
      setError(null);
      if (clip?.id === next.id) {
        void audio.play();
        return;
      }
      setClip(next);
      setPosition(0);
      setDuration(0);
      audio.src = audioUrl(next.id);
      audio.playbackRate = rate;
      void audio.play();
    },
    [clip?.id, ensureAudio, rate],
  );

  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || !clip) return;
    if (audio.paused) void audio.play();
    else audio.pause();
  }, [clip]);

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

  useEffect(
    () => () => {
      audioRef.current?.pause();
    },
    [],
  );

  return (
    <PlayerContext.Provider
      value={{ clip, playing, position, duration, rate, error, play, toggle, seekBy, seekTo, setRate }}
    >
      {children}
    </PlayerContext.Provider>
  );
}
