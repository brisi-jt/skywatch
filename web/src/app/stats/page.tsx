"use client";

import Link from "next/link";

import { FeedbackDisagreementPanel } from "@/components/feedback-disagreement-panel";
import { NotableDaysRail } from "@/components/notable-days-rail";
import { StatsHeatGrid } from "@/components/stats-heat-grid";
import { StatsTopAirlines } from "@/components/stats-top-airlines";
import { StatsTrend } from "@/components/stats-trend";
import { useFeedbackEval, useNotableDays, useStats } from "@/lib/api/hooks";

/** Below this many days of history, a trend or heat grid reads as noise. */
const MIN_DAYS_FOR_STATS = 3;

export default function StatsPage() {
  const stats = useStats();
  const notable = useNotableDays();
  const feedback = useFeedbackEval();

  return (
    <div className="flex flex-col gap-8">
      <header>
        <Link
          href="/"
          className="text-base text-muted-foreground underline underline-offset-4 hover:text-foreground"
        >
          ← Today
        </Link>
        <h1 className="mt-1 font-display text-3xl font-semibold tracking-tight">
          The station&apos;s story
        </h1>
      </header>

      {stats.isPending && (
        <p className="text-lg text-muted-foreground">
          Counting up the last month…
        </p>
      )}
      {stats.isError && (
        <p className="text-base text-health-bad">
          Something went wrong fetching the stats. The station itself is
          unaffected — try again in a moment.
        </p>
      )}

      {stats.data && stats.data.days_covered < MIN_DAYS_FOR_STATS && (
        <section className="rounded-xl border bg-card px-6 py-10 text-center">
          <p className="text-lg">Not enough days yet.</p>
          <p className="mt-2 text-base text-muted-foreground">
            The story fills in once the station has a week or two of listening
            behind it.
          </p>
        </section>
      )}

      {stats.data && stats.data.days_covered >= MIN_DAYS_FOR_STATS && (
        <>
          <section aria-label="Transmissions per day">
            <h2 className="font-display text-xl font-semibold">
              Transmissions, day by day
            </h2>
            <StatsTrend daily={stats.data.daily_counts} />
          </section>

          <section aria-label="Busiest hours">
            <h2 className="font-display text-xl font-semibold">
              Busiest hours
            </h2>
            <StatsHeatGrid
              frequencies={stats.data.heat_frequencies}
              cells={stats.data.hourly_heat}
            />
          </section>

          <div className="grid grid-cols-1 gap-8 sm:grid-cols-2">
            <section aria-label="Airlines heard most often">
              <h2 className="font-display text-xl font-semibold">
                Airlines heard most
              </h2>
              <StatsTopAirlines airlines={stats.data.top_airlines} />
            </section>

            <section aria-label="At a glance">
              <h2 className="font-display text-xl font-semibold">
                At a glance
              </h2>
              <dl className="mt-3 grid grid-cols-2 gap-4">
                <div>
                  <dt className="text-sm text-muted-foreground">
                    Interesting rate
                  </dt>
                  <dd className="font-mono text-2xl text-readout">
                    {stats.data.interesting_rate != null
                      ? `${Math.round(stats.data.interesting_rate * 100)}%`
                      : "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-sm text-muted-foreground">Go-arounds</dt>
                  <dd className="font-mono text-2xl text-readout">
                    {stats.data.go_around_count}
                  </dd>
                </div>
              </dl>
            </section>
          </div>
        </>
      )}

      {notable.data && notable.data.items.length > 0 && (
        <section aria-label="Notable days">
          <h2 className="font-display text-xl font-semibold">Notable days</h2>
          <NotableDaysRail days={notable.data.items} />
        </section>
      )}

      <section aria-label="Classifier versus listeners">
        <h2 className="font-display text-xl font-semibold">
          Classifier vs. listeners
        </h2>
        <FeedbackDisagreementPanel
          data={feedback.data}
          isPending={feedback.isPending}
          isError={feedback.isError}
        />
      </section>
    </div>
  );
}
