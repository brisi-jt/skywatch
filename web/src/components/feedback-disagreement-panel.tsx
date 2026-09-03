import Link from "next/link";

import type { EvalFeedbackResponse } from "@/lib/api/client";
import { categoryWord } from "@/lib/tiers";

/** The classifier measured against listener votes, and where the two disagreed. */
export function FeedbackDisagreementPanel({
  data,
  isPending,
  isError,
}: {
  data: EvalFeedbackResponse | undefined;
  isPending: boolean;
  isError: boolean;
}) {
  if (isPending) {
    return (
      <p className="mt-3 text-base text-muted-foreground">
        Comparing verdicts…
      </p>
    );
  }
  if (isError) {
    return (
      <p className="mt-3 text-base text-health-bad">
        Could not load the feedback comparison right now.
      </p>
    );
  }
  if (!data || data.sample_size === 0) {
    return (
      <p className="mt-3 text-base text-muted-foreground">
        No clips have both a listener vote and a verdict yet — thumbs-up or down
        a few clips to start comparing.
      </p>
    );
  }

  return (
    <div className="mt-3 flex flex-col gap-4">
      <dl className="flex flex-wrap gap-6">
        <div>
          <dt className="text-sm text-muted-foreground">Precision</dt>
          <dd className="font-mono text-2xl text-readout">
            {data.precision != null
              ? `${Math.round(data.precision * 100)}%`
              : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-sm text-muted-foreground">Recall</dt>
          <dd className="font-mono text-2xl text-readout">
            {data.recall != null ? `${Math.round(data.recall * 100)}%` : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-sm text-muted-foreground">Clips compared</dt>
          <dd className="font-mono text-2xl text-readout">
            {data.sample_size}
          </dd>
        </div>
      </dl>

      {data.disagreements.length === 0 ? (
        <p className="text-base text-muted-foreground">
          The classifier and listeners agree on every clip so far.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {data.disagreements.map((d) => (
            <li
              key={d.recording_id}
              className="rounded-lg border bg-card px-4 py-3"
            >
              <Link
                href={`/clips/?clip=${d.recording_id}`}
                className="text-base underline underline-offset-4 hover:text-foreground"
              >
                {d.transcript_snippet ?? `Clip #${d.recording_id}`}
              </Link>
              <p className="mt-1 text-sm text-muted-foreground">
                Classifier said{" "}
                {d.classified_interesting ? "worth hearing" : "routine"} (
                {categoryWord(d.category)}); listeners voted{" "}
                {d.human_interesting ? "worth hearing" : "routine"} (
                {d.feedback_up}↑ {d.feedback_down}↓)
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
