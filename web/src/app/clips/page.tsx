"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { ClipCard } from "@/components/clip-card";
import { NewClipsPill } from "@/components/new-clips-pill";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useFrequencies, useRecordingDetail, useRecordings, type ClipFilters } from "@/lib/api/hooks";
import { freqLabel } from "@/lib/format";
import { categoryWord } from "@/lib/tiers";

const CATEGORIES = [
  "emergency",
  "urgency",
  "go_around",
  "medical",
  "fuel",
  "guard_activity",
  "unusual",
  "other",
  "routine",
];

export default function ClipsPage() {
  return (
    <Suspense>
      <ClipsView />
    </Suspense>
  );
}

function ClipsView() {
  const params = useSearchParams();
  const linkedClip = params.get("clip");
  const linkedDate = params.get("date");

  const [fromDate, setFromDate] = useState(linkedDate ?? "");
  const [toDate, setToDate] = useState(linkedDate ?? "");
  const [freqId, setFreqId] = useState<string>("all");
  const [interestingOnly, setInterestingOnly] = useState(false);
  const [category, setCategory] = useState<string>("all");
  const [hasAircraft, setHasAircraft] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(
    linkedClip ? Number(linkedClip) : null,
  );

  const filters: ClipFilters = {
    ...(fromDate && { from_date: fromDate }),
    ...(toDate && { to_date: toDate }),
    ...(freqId !== "all" && { freq_id: Number(freqId) }),
    ...(interestingOnly && { interesting: true as const }),
    ...(category !== "all" && { category }),
    ...(hasAircraft && { has_match: true as const }),
  };

  const { data: frequencies } = useFrequencies();
  const recordings = useRecordings(filters);

  const items = recordings.data?.pages.flatMap((page) => page.items) ?? [];
  const total = recordings.data?.pages[0]?.total;

  // A deep-linked clip that isn't in the visible pages still gets shown.
  const linkedId = linkedClip ? Number(linkedClip) : null;
  const linkedVisible = linkedId != null && items.some((item) => item.id === linkedId);

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="font-display text-3xl font-semibold tracking-tight">Clips</h1>
        <p className="mt-1 text-base text-muted-foreground">
          {total != null
            ? `${total} ${total === 1 ? "recording" : "recordings"} in the archive`
            : "Opening the archive…"}
        </p>
      </header>

      <section
        aria-label="Filters"
        className="flex flex-wrap items-end gap-x-5 gap-y-3 rounded-xl border bg-card px-4 py-4"
      >
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="from-date" className="text-sm">
            From
          </Label>
          <Input
            id="from-date"
            type="date"
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
            className="h-10 w-40 text-base"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="to-date" className="text-sm">
            To
          </Label>
          <Input
            id="to-date"
            type="date"
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
            className="h-10 w-40 text-base"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label className="text-sm">Frequency</Label>
          <Select value={freqId} onValueChange={setFreqId}>
            <SelectTrigger className="h-10 w-56 text-base">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All frequencies</SelectItem>
              {frequencies?.items.map((freq) => (
                <SelectItem key={freq.id} value={String(freq.id)}>
                  {freqLabel(freq.mhz, freq.label)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label className="text-sm">Category</Label>
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger className="h-10 w-44 text-base">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All categories</SelectItem>
              {CATEGORIES.map((cat) => (
                <SelectItem key={cat} value={cat}>
                  {categoryWord(cat)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <label className="flex min-h-10 items-center gap-2 text-base">
          <Switch checked={interestingOnly} onCheckedChange={setInterestingOnly} />
          Worth hearing only
        </label>
        <label className="flex min-h-10 items-center gap-2 text-base">
          <Switch checked={hasAircraft} onCheckedChange={setHasAircraft} />
          Has aircraft
        </label>
      </section>

      <NewClipsPill />

      {linkedId != null && !linkedVisible && <LinkedClip id={linkedId} />}

      {recordings.isPending && (
        <div className="flex flex-col gap-4" aria-hidden>
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-28 animate-pulse rounded-xl border bg-card" />
          ))}
        </div>
      )}

      {recordings.isError && (
        <p className="rounded-xl border bg-card px-6 py-8 text-center text-base text-health-bad">
          The archive could not be reached. Check the Station view if this keeps happening.
        </p>
      )}

      {recordings.data && items.length === 0 && (
        <div className="rounded-xl border bg-card px-6 py-10 text-center">
          <p className="text-lg">Nothing matches these filters.</p>
          <p className="mt-2 text-base text-muted-foreground">
            Widen the dates or switch off a filter to see more of the archive.
          </p>
        </div>
      )}

      <section className="flex flex-col gap-4" aria-label="Clip list">
        {items.map((clip) => (
          <ClipCard
            key={clip.id}
            clip={clip}
            expanded={expandedId === clip.id}
            onToggle={(id) => setExpandedId((cur) => (cur === id ? null : id))}
          />
        ))}
      </section>

      {recordings.hasNextPage && (
        <div className="flex justify-center">
          <Button
            variant="outline"
            size="lg"
            onClick={() => recordings.fetchNextPage()}
            disabled={recordings.isFetchingNextPage}
          >
            {recordings.isFetchingNextPage ? "Loading…" : "Load more"}
          </Button>
        </div>
      )}
    </div>
  );
}

/** Deep-linked clip rendered above the list when it's outside the loaded pages. */
function LinkedClip({ id }: { id: number }) {
  const { data, isError } = useRecordingDetail(id, true);
  const [expanded, setExpanded] = useState(true);

  useEffect(() => {
    if (data) setExpanded(true);
  }, [data]);

  if (isError) {
    return (
      <p className="rounded-xl border bg-card px-4 py-3 text-base text-muted-foreground">
        The linked clip could not be found — it may have been pruned.
      </p>
    );
  }
  if (!data) return null;

  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm text-muted-foreground">From your link:</p>
      <ClipCard
        clip={data}
        expanded={expanded}
        onToggle={() => setExpanded((cur) => !cur)}
      />
    </div>
  );
}
