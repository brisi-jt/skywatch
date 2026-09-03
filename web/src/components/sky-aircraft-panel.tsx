"use client";

import { ClipCard, ClipCardSkeleton } from "@/components/clip-card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { SkyAircraftResource } from "@/lib/api/client";
import { useRecordingDetail } from "@/lib/api/hooks";
import { playableQueue } from "@/lib/clip";
import { aircraftLabel } from "@/lib/sky";

/**
 * The fusion side panel: click a live aircraft, see the clips the station
 * has actually heard from it. Opens as a dialog rather than a docked pane so
 * it works the same on a phone-width viewport as it does on desktop.
 */
export function SkyAircraftPanel({
  aircraft,
  onOpenChange,
}: {
  aircraft: SkyAircraftResource | null;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={aircraft != null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        {aircraft && <PanelBody aircraft={aircraft} />}
      </DialogContent>
    </Dialog>
  );
}

function PanelBody({ aircraft }: { aircraft: SkyAircraftResource }) {
  const recordingIds = aircraft.heard_recording_ids ?? [];
  return (
    <>
      <DialogHeader>
        <DialogTitle className="font-mono text-xl">{aircraftLabel(aircraft)}</DialogTitle>
        <DialogDescription>
          {recordingIds.length > 0
            ? "📻 Heard on this station recently:"
            : "Not matched to any recent clip — this one hasn't been on the airwaves yet."}
        </DialogDescription>
      </DialogHeader>
      {recordingIds.length > 0 && (
        <div className="flex flex-col gap-3">
          {recordingIds.map((id) => (
            <HeardClip key={id} id={id} />
          ))}
        </div>
      )}
    </>
  );
}

/** One clip in the panel, fetched on demand and played through the same
 * queue/player machinery as every other clip card in the dashboard. */
function HeardClip({ id }: { id: number }) {
  const { data, isPending, isError } = useRecordingDetail(id, true);

  if (isPending) return <ClipCardSkeleton />;
  if (isError || !data) {
    return <p className="text-base text-muted-foreground">This clip could not be loaded.</p>;
  }
  return <ClipCard clip={data} variant="small" queue={playableQueue([data])} />;
}
