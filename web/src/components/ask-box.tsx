"use client";

import { Send } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAsk } from "@/lib/api/hooks";
import { MAX_QUESTION_LENGTH, askErrorMessage, sanitizeQuestion } from "@/lib/ask";
import { clockTime } from "@/lib/format";

/** A plain-English question box over the station's own recorded clips. */
export function AskBox() {
  const [value, setValue] = useState("");
  const ask = useAsk();

  const submit = () => {
    const question = sanitizeQuestion(value);
    if (!question) return;
    ask.mutate(question);
  };

  return (
    <section aria-label="Ask the station" className="rounded-xl border bg-card p-6">
      <h2 className="font-display text-xl font-semibold">Ask the station</h2>
      <p className="mt-1 text-base text-muted-foreground">
        Ask a plain-English question about what&apos;s been heard — &ldquo;was
        there a mayday this week?&rdquo;, &ldquo;what has Speedbird been up
        to?&rdquo;
      </p>

      <form
        className="mt-3 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Ask a question…"
          maxLength={MAX_QUESTION_LENGTH}
          disabled={ask.isPending}
          aria-label="Question"
          className="min-h-10"
        />
        <Button type="submit" disabled={ask.isPending || !value.trim()}>
          <Send className="size-4" />
          {ask.isPending ? "Asking…" : "Ask"}
        </Button>
      </form>

      {ask.isError && (
        <p className="mt-3 text-base text-health-warn">{askErrorMessage(ask.error)}</p>
      )}

      {ask.isSuccess && (
        <div className="mt-4 flex flex-col gap-3">
          <p className="text-lg leading-relaxed text-foreground/90">{ask.data.answer}</p>
          {ask.data.sources.length > 0 && (
            <ul className="flex flex-col gap-1">
              {ask.data.sources.map((source) => (
                <li key={source.recording_id} className="text-sm">
                  <Link
                    href={`/clips/?clip=${source.recording_id}`}
                    className="underline underline-offset-4 hover:text-foreground"
                  >
                    {source.transcript_snippet || `Clip #${source.recording_id}`}
                  </Link>
                  <span className="text-muted-foreground">
                    {" "}
                    — {clockTime(source.started_at_utc)} on {source.frequency_label}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <p className="mt-4 text-sm text-muted-foreground">
        Answers come from the same model that classifies clips (Gemini&apos;s
        free tier by default), whose terms allow Google to use submitted
        text — here, transcript snippets — to improve their products. See
        the project&apos;s README for details or to switch providers.
      </p>
    </section>
  );
}
