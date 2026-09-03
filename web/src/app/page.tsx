"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ChevronLeft, ChevronRight, Play } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ClipCard } from "@/components/clip-card";
import { EmptyHero } from "@/components/empty-hero";
import { HealthStrip } from "@/components/health-strip";
import { Button } from "@/components/ui/button";
import {
  useDigest,
  useFrequencies,
  useHasAnyRecording,
  useStatus,
} from "@/lib/api/hooks";
import { playableQueue } from "@/lib/clip";
import { clockTime, friendlyDate, shiftDay, todayIso, weekday } from "@/lib/format";
import { usePlayer } from "@/lib/player";

export default function TodayPage() {
  const [date, setDate] = useState(todayIso);
  const [direction, setDirection] = useState(0);
  const reducedMotion = useReducedMotion();
  const { data: status } = useStatus();
  const { data: hasAny, isPending: anyPending } = useHasAnyRecording();
  const digest = useDigest(date);
  const { data: frequencies } = useFrequencies();
  const player = usePlayer();
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const featuredQueue = digest.data ? playableQueue(digest.data.interesting) : [];
  const hitsQueue = digest.data ? playableQueue(digest.data.greatest_hits) : [];

  const isToday = date === todayIso();
  const activeCount = frequencies?.items.filter((f) => f.is_active).length;

  // Day one: nothing has ever been recorded — the live hero owns the page.
  if (!anyPending && hasAny === false) {
    return <EmptyHero status={status} activeCount={activeCount} />;
  }

  const goToDay = (delta: number) => {
    setDirection(delta);
    setDate((d) => shiftDay(d, delta));
  };
  const goToToday = () => {
    setDirection(1);
    setDate(todayIso());
  };

  const dayVariants = {
    enter: (d: number) => (reducedMotion ? { opacity: 1 } : { x: d >= 0 ? 28 : -28, opacity: 0 }),
    center: { x: 0, opacity: 1 },
    exit: (d: number) => (reducedMotion ? { opacity: 1 } : { x: d >= 0 ? -28 : 28, opacity: 0 }),
  };

  return (
    <div className="flex flex-col gap-8">
      {status && <HealthStrip status={status} />}

      <nav className="flex items-center justify-end gap-1" aria-label="Change day">
        <Button
          variant="outline"
          size="icon"
          className="size-10"
          aria-label="Previous day"
          onClick={() => goToDay(-1)}
        >
          <ChevronLeft className="size-5" />
        </Button>
        <Button variant="outline" className="min-h-10" disabled={isToday} onClick={goToToday}>
          Today
        </Button>
        <Button
          variant="outline"
          size="icon"
          className="size-10"
          aria-label="Next day"
          disabled={isToday}
          onClick={() => goToDay(1)}
        >
          <ChevronRight className="size-5" />
        </Button>
      </nav>

      <AnimatePresence mode="wait" custom={direction} initial={false}>
        <motion.div
          key={date}
          className="flex flex-col gap-8"
          custom={direction}
          variants={dayVariants}
          initial="enter"
          animate="center"
          exit="exit"
          transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
        >
          <header>
            <p className="text-base text-muted-foreground">{friendlyDate(date)}</p>
            <h1 className="mt-1 font-display text-3xl font-semibold tracking-tight">
              {digest.data ? (
                <>
                  {weekday(date)}: {digest.data.total_count}{" "}
                  {digest.data.total_count === 1 ? "transmission" : "transmissions"},{" "}
                  {digest.data.interesting_count} worth hearing
                </>
              ) : digest.isError ? (
                "The day's digest could not be loaded"
              ) : (
                "Reading the day's log…"
              )}
            </h1>
          </header>

          {digest.data?.narrative && (
            <section aria-label="The day in a few words" className="max-w-prose">
              <p className="text-lg leading-relaxed text-foreground/90">
                {digest.data.narrative.text}
              </p>
              {digest.data.narrative.rolling && (
                <p className="mt-1 text-sm text-muted-foreground">
                  as of {clockTime(digest.data.narrative.generated_at)}
                </p>
              )}
            </section>
          )}

          {digest.isError && (
            <p className="text-base text-health-bad">
              Something went wrong fetching the digest. The station itself is unaffected — try again
              in a moment.
            </p>
          )}

          {digest.data &&
            (digest.data.interesting.length > 0 ? (
              <section className="flex flex-col gap-4" aria-label="Worth hearing">
                {featuredQueue.length > 0 && (
                  <div className="flex justify-end">
                    <Button
                      variant="outline"
                      className="min-h-10"
                      onClick={() => player.playQueue(featuredQueue, featuredQueue[0].id)}
                    >
                      <Play className="size-4" />
                      Play all worth hearing
                    </Button>
                  </div>
                )}
                {digest.data.interesting.map((clip) => (
                  <ClipCard
                    key={clip.id}
                    clip={clip}
                    variant="featured"
                    queue={featuredQueue}
                    expanded={expandedId === clip.id}
                    onToggle={(id) => setExpandedId((cur) => (cur === id ? null : id))}
                  />
                ))}
              </section>
            ) : (
              <section className="rounded-xl border bg-card px-6 py-10 text-center">
                <p className="text-lg">A quiet day on the airwaves — nothing flagged.</p>
                {digest.data.total_count > 0 && (
                  <p className="mt-2 text-base text-muted-foreground">
                    <Link href={`/clips/?date=${date}`} className="underline underline-offset-4">
                      Listen through all {digest.data.total_count} clips from this day
                    </Link>
                  </p>
                )}
              </section>
            ))}
        </motion.div>
      </AnimatePresence>

      {digest.data && digest.data.greatest_hits.length > 0 && (
        <section aria-label="Greatest hits">
          <h2 className="font-display text-xl font-semibold">All-time greatest hits</h2>
          <p className="text-sm text-muted-foreground">The clips you keep coming back to.</p>
          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {digest.data.greatest_hits.map((clip) => (
              <ClipCard key={clip.id} clip={clip} variant="small" queue={hitsQueue} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
