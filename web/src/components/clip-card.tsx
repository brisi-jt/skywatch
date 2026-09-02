"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ChevronDown, Play, RefreshCcw, ThumbsDown, ThumbsUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  InterestingBadge,
  RoughTranscriptBadge,
  RoutineBadge,
  TierChip,
} from "@/components/chips";
import { Button } from "@/components/ui/button";
import type { RecordingSummary } from "@/lib/api/client";
import { useFeedback, useReclassify, useRecordingDetail } from "@/lib/api/hooks";
import { toPlayerClip } from "@/lib/clip";
import { clockTime, durationLabel, freqLabel } from "@/lib/format";
import { clipAnchorId, usePlayer, type PlayerClip } from "@/lib/player";
import { isRoughTranscript, stageWord } from "@/lib/tiers";
import { cn } from "@/lib/utils";

export type ClipCardVariant = "default" | "featured" | "small";

type Vote = "up" | "down";

/** Feedback votes persist per clip so a vote can't be cast twice across a
 * collapse/expand or a page reload — the server has no per-listener identity. */
function readVote(id: number): Vote | null {
  if (typeof window === "undefined") return null;
  const stored = window.localStorage.getItem(`skywatch.voted.${id}`);
  return stored === "up" || stored === "down" ? stored : null;
}

function writeVote(id: number, verdict: Vote): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(`skywatch.voted.${id}`, verdict);
}

export function ClipCard({
  clip,
  variant = "default",
  expanded = false,
  onToggle,
  queue,
}: {
  clip: RecordingSummary;
  variant?: ClipCardVariant;
  expanded?: boolean;
  onToggle?: (id: number) => void;
  /** The ordered list this card belongs to; playing seeds the queue from it. */
  queue?: PlayerClip[];
}) {
  const player = usePlayer();
  const reducedMotion = useReducedMotion();
  const ref = useRef<HTMLElement>(null);
  const detail = useRecordingDetail(clip.id, expanded);

  useEffect(() => {
    if (expanded && ref.current) {
      ref.current.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "nearest" });
    }
  }, [expanded, reducedMotion]);

  const interesting = clip.classification?.is_interesting ?? false;
  const title = `${clockTime(clip.started_at_utc)} · ${clip.frequency.label}`;
  const isCurrent = player.clip?.id === clip.id;

  const startPlay = () => {
    if (isCurrent) {
      player.toggle();
    } else if (queue && queue.length > 0) {
      player.playQueue(queue, clip.id);
    } else {
      player.play(toPlayerClip(clip));
    }
  };

  if (variant === "small") {
    return (
      <div
        id={clipAnchorId(clip.id)}
        className={cn(
          "flex items-center gap-3 rounded-lg border bg-card px-3 py-2",
          isCurrent && "ring-2 ring-interesting/60",
        )}
      >
        <PlayButton
          available={clip.audio_available}
          playing={isCurrent && player.playing}
          onClick={startPlay}
          size="sm"
        />
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{title}</p>
          {clip.transcript_snippet && (
            <p className="truncate text-sm text-muted-foreground">“{clip.transcript_snippet}”</p>
          )}
        </div>
        <span className="ml-auto shrink-0 font-mono text-sm text-muted-foreground">
          👍 {clip.feedback.up}
        </span>
      </div>
    );
  }

  return (
    <article
      ref={ref}
      id={clipAnchorId(clip.id)}
      className={cn(
        "rounded-xl border bg-card transition-colors",
        interesting && "border-interesting/40",
        expanded && "border-ring/50",
        isCurrent && "ring-2 ring-interesting/60",
      )}
    >
      <div className={cn("flex items-start gap-4 p-4", variant === "featured" && "p-5")}>
        <PlayButton
          available={clip.audio_available}
          playing={isCurrent && player.playing}
          onClick={startPlay}
        />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className={cn("font-medium", variant === "featured" && "text-lg")}>
              {clockTime(clip.started_at_utc)}
            </span>
            {isCurrent && <NowPlaying playing={player.playing} />}
            <span className="font-mono text-sm text-readout">
              {freqLabel(clip.frequency.mhz, clip.frequency.label)}
            </span>
            <span className="text-sm text-muted-foreground">{durationLabel(clip.duration_s)}</span>
            {clip.classification ? (
              interesting ? (
                <InterestingBadge category={clip.classification.category} />
              ) : (
                <RoutineBadge category={clip.classification.category} />
              )
            ) : (
              <span className="text-sm text-muted-foreground">{stageWord(clip.stage)}…</span>
            )}
          </div>

          {clip.transcript_snippet ? (
            <p
              className={cn(
                "mt-2 text-foreground/90",
                variant === "featured" ? "text-lg leading-relaxed" : "text-base",
                !expanded && "line-clamp-2",
              )}
            >
              “{clip.transcript_snippet}
              {!expanded && clip.transcript_snippet.length >= 140 ? "…" : "”"}
            </p>
          ) : (
            !clip.classification && (
              <p className="mt-2 text-base text-muted-foreground">Transcript on its way…</p>
            )
          )}

          {clip.top_match && !expanded && (
            <div className="mt-3">
              <TierChip match={clip.top_match} />
            </div>
          )}
        </div>

        {onToggle && (
          <button
            type="button"
            onClick={() => onToggle(clip.id)}
            aria-expanded={expanded}
            aria-label={expanded ? "Collapse clip details" : "Expand clip details"}
            className="flex size-10 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground"
          >
            <ChevronDown className={cn("size-5 transition-transform", expanded && "rotate-180")} />
          </button>
        )}
      </div>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={reducedMotion ? false : { height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={reducedMotion ? undefined : { height: 0, opacity: 0 }}
            transition={{ type: "tween", ease: [0.16, 1, 0.3, 1], duration: 0.3 }}
            className="overflow-hidden"
          >
            <ExpandedBody clip={clip} detailQuery={detail} />
          </motion.div>
        )}
      </AnimatePresence>
    </article>
  );
}

/** A card-shaped placeholder while a page of clips is loading. */
export function ClipCardSkeleton() {
  return (
    <div className="flex items-start gap-4 rounded-xl border bg-card p-4" aria-hidden>
      <div className="size-12 shrink-0 animate-pulse rounded-full bg-muted" />
      <div className="min-w-0 flex-1 space-y-2">
        <div className="h-4 w-40 animate-pulse rounded bg-muted" />
        <div className="h-4 w-full animate-pulse rounded bg-muted" />
        <div className="h-4 w-3/4 animate-pulse rounded bg-muted" />
      </div>
    </div>
  );
}

/** The now-playing marker: an equalizer glyph that animates only while playing. */
function NowPlaying({ playing }: { playing: boolean }) {
  return (
    <span
      className="inline-flex items-end gap-0.5"
      role="img"
      aria-label={playing ? "Now playing" : "Loaded in the player"}
      title={playing ? "Now playing" : "Loaded in the player"}
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          data-playing={playing}
          className="eq-bar w-0.5 rounded-full bg-interesting"
          style={{ animationDelay: `${i * 0.16}s` }}
        />
      ))}
    </span>
  );
}

function PlayButton({
  available,
  playing,
  onClick,
  size = "lg",
}: {
  available: boolean;
  playing: boolean;
  onClick: () => void;
  size?: "sm" | "lg";
}) {
  if (!available) {
    return (
      <span
        className={cn(
          "flex shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground",
          size === "lg" ? "size-12" : "size-10",
        )}
        title="Audio no longer kept for this clip"
      >
        <Play className={cn(size === "lg" ? "size-5" : "size-4", "translate-x-0.5 opacity-40")} />
      </span>
    );
  }
  return (
    <Button
      size="icon"
      onClick={onClick}
      aria-label={playing ? "Pause clip" : "Play clip"}
      className={cn("shrink-0 rounded-full", size === "lg" ? "size-12" : "size-10")}
    >
      {playing ? (
        <span className="flex gap-0.5" aria-hidden>
          <span className="h-4 w-1 bg-current" />
          <span className="h-4 w-1 bg-current" />
        </span>
      ) : (
        <Play className={cn(size === "lg" ? "size-5" : "size-4", "translate-x-0.5")} />
      )}
    </Button>
  );
}

function ExpandedBody({
  clip,
  detailQuery,
}: {
  clip: RecordingSummary;
  detailQuery: ReturnType<typeof useRecordingDetail>;
}) {
  const { data: detail, isPending, isError } = detailQuery;
  const feedback = useFeedback();
  const reclassify = useReclassify();
  const [voted, setVoted] = useState<Vote | null>(() => readVote(clip.id));

  const latest = detail?.classifications[detail.classifications.length - 1] ?? clip.classification;

  return (
    <div className="flex flex-col gap-5 border-t px-4 py-5 sm:px-5">
      {isPending && <p className="text-base text-muted-foreground">Fetching the full story…</p>}
      {isError && (
        <p className="text-base text-health-bad">
          The clip’s details could not be loaded. It may have just been pruned — try refreshing.
        </p>
      )}

      {detail?.transcript && (
        <section>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold tracking-wide text-muted-foreground uppercase">
              Transcript
            </h3>
            {isRoughTranscript(detail.transcript.avg_logprob) && <RoughTranscriptBadge />}
          </div>
          <p className="mt-2 text-lg leading-relaxed">“{detail.transcript.text}”</p>
        </section>
      )}

      {detail && detail.matches.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold tracking-wide text-muted-foreground uppercase">
            Who was flying
          </h3>
          <ul className="mt-2 flex flex-col gap-2">
            {detail.matches.map((match) => (
              <li key={match.id} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <TierChip match={match} />
                <span className="font-mono text-sm text-muted-foreground">
                  {match.alt_ft != null && `${Math.round(match.alt_ft).toLocaleString()} ft`}
                  {match.alt_ft != null && match.gs_kt != null && " · "}
                  {match.gs_kt != null && `${Math.round(match.gs_kt)} kt`}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {latest && (
        <section>
          <h3 className="text-sm font-semibold tracking-wide text-muted-foreground uppercase">
            Why it was {latest.is_interesting ? "flagged" : "filed as routine"}
          </h3>
          <p className="mt-2 text-base">{latest.reason}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {latest.source === "llm"
              ? "Judged by the station's language model."
              : "Caught by the station's own listening rules."}
            {latest.status === "deferred" && " A fuller verdict is queued for later."}
          </p>
        </section>
      )}

      <div className="flex flex-wrap items-center gap-4">
        <div className="flex items-center gap-2">
          <span className="text-base">Worth hearing?</span>
          <Button
            variant={voted === "up" ? "secondary" : "ghost"}
            size="icon"
            className="size-10"
            aria-label="Worth hearing"
            disabled={feedback.isPending || voted !== null}
            onClick={() =>
              feedback.mutate(
                { recordingId: clip.id, verdict: "up" },
                {
                  onSuccess: () => {
                    setVoted("up");
                    writeVote(clip.id, "up");
                  },
                },
              )
            }
          >
            <ThumbsUp className="size-5" />
          </Button>
          <Button
            variant={voted === "down" ? "secondary" : "ghost"}
            size="icon"
            className="size-10"
            aria-label="Not worth hearing"
            disabled={feedback.isPending || voted !== null}
            onClick={() =>
              feedback.mutate(
                { recordingId: clip.id, verdict: "down" },
                {
                  onSuccess: () => {
                    setVoted("down");
                    writeVote(clip.id, "down");
                  },
                },
              )
            }
          >
            <ThumbsDown className="size-5" />
          </Button>
          <span className="font-mono text-sm text-muted-foreground">
            {clip.feedback.up + (voted === "up" ? 1 : 0)} up ·{" "}
            {clip.feedback.down + (voted === "down" ? 1 : 0)} down
          </span>
        </div>

        <div className="ml-auto flex items-center gap-2">
          {reclassify.isSuccess ? (
            <span className="text-sm text-muted-foreground">
              Sent back for another look — a fresh verdict will appear shortly.
            </span>
          ) : (
            <Button
              variant="outline"
              className="min-h-10"
              disabled={reclassify.isPending || !latest}
              onClick={() => reclassify.mutate(clip.id)}
            >
              <RefreshCcw className="size-4" />
              Take another look
            </Button>
          )}
        </div>
      </div>

      {detail && (
        <details className="rounded-lg bg-muted/60 px-4 py-3">
          <summary className="min-h-8 cursor-pointer text-sm font-medium text-muted-foreground">
            Technical detail
          </summary>
          <dl className="mt-3 grid grid-cols-1 gap-x-8 gap-y-2 font-mono text-sm sm:grid-cols-2">
            {detail.transcript && (
              <>
                <TechRow
                  label="ASR engine"
                  value={`${detail.transcript.engine} · ${detail.transcript.model}`}
                />
                <TechRow
                  label="avg_logprob"
                  value={detail.transcript.avg_logprob?.toFixed(3) ?? "n/a"}
                />
              </>
            )}
            {latest && (
              <>
                <TechRow label="verdict confidence" value={latest.confidence.toFixed(2)} />
                <TechRow
                  label="verdict model"
                  value={latest.model ?? latest.source}
                />
                {latest.prefilter_flags.length > 0 && (
                  <TechRow label="prefilter flags" value={latest.prefilter_flags.join(", ")} />
                )}
              </>
            )}
            {detail.matches[0] && (
              <TechRow
                label="top match confidence"
                value={detail.matches[0].match_confidence.toFixed(2)}
              />
            )}
            <TechRow label="stage" value={detail.stage} />
            <TechRow label="file" value={detail.file_path} />
          </dl>
        </details>
      )}
    </div>
  );
}

function TechRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 overflow-hidden">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className="truncate">{value}</dd>
    </div>
  );
}
