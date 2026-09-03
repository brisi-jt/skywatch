"use client";

import { ArrowLeft, Play, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { ClipCard } from "@/components/clip-card";
import { Button } from "@/components/ui/button";
import {
  useDeleteIncident,
  useIncident,
  useIncidents,
  useRemoveClipFromIncident,
} from "@/lib/api/hooks";
import { playableQueue } from "@/lib/clip";
import { clockTime, friendlyDate, localDay } from "@/lib/format";
import { usePlayer } from "@/lib/player";

export default function IncidentsPage() {
  return (
    <Suspense>
      <IncidentsView />
    </Suspense>
  );
}

function IncidentsView() {
  const params = useSearchParams();
  const selectedId = params.get("incident") ? Number(params.get("incident")) : null;

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="font-display text-3xl font-semibold tracking-tight">Incidents</h1>
        <p className="mt-1 text-base text-muted-foreground">
          Clips grouped together because they belong to the same story.
        </p>
      </header>

      {selectedId != null ? <IncidentDetail id={selectedId} /> : <IncidentList />}
    </div>
  );
}

function IncidentList() {
  const incidents = useIncidents();

  if (incidents.isPending) {
    return <p className="text-base text-muted-foreground">Opening the incident log…</p>;
  }
  if (incidents.isError) {
    return (
      <p className="rounded-xl border bg-card px-6 py-8 text-center text-base text-health-bad">
        The incident log could not be reached.
      </p>
    );
  }
  if (incidents.data.items.length === 0) {
    return (
      <div className="rounded-xl border bg-card px-6 py-10 text-center">
        <p className="text-lg">No incidents yet.</p>
        <p className="mt-2 text-base text-muted-foreground">
          Select clips on the Clips page and group them into a bundle to start one.
        </p>
      </div>
    );
  }

  return (
    <section className="flex flex-col gap-3" aria-label="Incident list">
      {incidents.data.items.map((incident) => (
        <Link
          key={incident.id}
          href={`/incidents/?incident=${incident.id}`}
          className="flex items-center justify-between gap-4 rounded-xl border bg-card px-4 py-4 transition-colors hover:bg-accent/40"
        >
          <div className="min-w-0">
            <p className="truncate text-lg font-medium">{incident.title}</p>
            <p className="text-sm text-muted-foreground">
              {friendlyDate(localDay(incident.created_at))} ·{" "}
              {incident.clip_count} {incident.clip_count === 1 ? "clip" : "clips"}
            </p>
          </div>
        </Link>
      ))}
    </section>
  );
}

function IncidentDetail({ id }: { id: number }) {
  const router = useRouter();
  const incident = useIncident(id);
  const removeClip = useRemoveClipFromIncident();
  const deleteIncident = useDeleteIncident();
  const player = usePlayer();
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  if (incident.isPending) {
    return <p className="text-base text-muted-foreground">Opening the incident…</p>;
  }
  if (incident.isError) {
    return (
      <div className="flex flex-col gap-4">
        <BackLink />
        <p className="rounded-xl border bg-card px-6 py-8 text-center text-base text-health-bad">
          This incident could not be found — it may have been deleted.
        </p>
      </div>
    );
  }

  const detail = incident.data;
  const recordings = detail.clips.map((c) => c.recording);
  const queue = playableQueue(recordings);

  return (
    <div className="flex flex-col gap-4">
      <BackLink />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-2xl font-semibold">{detail.title}</h2>
          <p className="text-sm text-muted-foreground">
            {friendlyDate(localDay(detail.created_at))} · {detail.clips.length}{" "}
            {detail.clips.length === 1 ? "clip" : "clips"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {queue.length > 0 && (
            <Button
              variant="outline"
              className="min-h-10"
              onClick={() => player.playQueue(queue, queue[0].id)}
            >
              <Play className="size-4" />
              Play in order
            </Button>
          )}
          <Button
            variant={confirmingDelete ? "destructive" : "ghost"}
            className="min-h-10"
            disabled={deleteIncident.isPending}
            onClick={() => {
              if (!confirmingDelete) {
                setConfirmingDelete(true);
                return;
              }
              deleteIncident.mutate(id, { onSuccess: () => router.push("/incidents/") });
            }}
          >
            <Trash2 className="size-4" />
            {confirmingDelete ? "Confirm delete" : "Delete incident"}
          </Button>
        </div>
      </div>

      {detail.clips.length === 0 ? (
        <p className="rounded-xl border bg-card px-6 py-8 text-center text-base text-muted-foreground">
          No clips in this incident yet.
        </p>
      ) : (
        <section className="flex flex-col gap-3" aria-label="Incident clips, in order">
          {detail.clips.map((entry, i) => (
            <div key={entry.recording.id} className="flex items-start gap-2">
              <span className="mt-3 w-6 shrink-0 text-right font-mono text-sm text-muted-foreground">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <ClipCard clip={entry.recording} queue={queue} />
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="mt-1 size-10 shrink-0"
                aria-label={`Remove the ${clockTime(entry.recording.started_at_utc)} clip from this incident`}
                disabled={removeClip.isPending}
                onClick={() => removeClip.mutate({ incidentId: id, recordingId: entry.recording.id })}
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

function BackLink() {
  return (
    <Link
      href="/incidents/"
      className="flex min-h-10 w-fit items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
    >
      <ArrowLeft className="size-4" aria-hidden />
      All incidents
    </Link>
  );
}
