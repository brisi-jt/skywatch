"use client";

import { Check, HelpCircle, Link2, Play, Search, X } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import { ClipCard, ClipCardSkeleton } from "@/components/clip-card";
import { NewClipsPill } from "@/components/new-clips-pill";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useFrequencies, useRecordingDetail, useRecordings } from "@/lib/api/hooks";
import { playableQueue } from "@/lib/clip";
import {
  buildClipFilters,
  emptyFilters,
  filtersFromSearchParams,
  filtersToSearchParams,
  hasActiveFilters,
  type FilterState,
} from "@/lib/clip-filters";
import { freqLabel } from "@/lib/format";
import { usePlayer } from "@/lib/player";
import { categoryWord } from "@/lib/tiers";
import { useStaggerGate } from "@/lib/use-stagger";
import { useWs } from "@/lib/ws";

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

const SEARCH_PLACEHOLDER = 'Search transcripts — mayday, "go around", freq:121.5…';

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

  const [filters, setFilters] = useState<FilterState>(() =>
    filtersFromSearchParams(new URLSearchParams(params.toString())),
  );
  const update = (patch: Partial<FilterState>) => setFilters((f) => ({ ...f, ...patch }));

  const [expandedId, setExpandedId] = useState<number | null>(
    linkedClip ? Number(linkedClip) : null,
  );

  const apiFilters = useMemo(() => buildClipFilters(filters), [filters]);

  // Keep the URL a faithful copy of the filter state so the view is shareable;
  // replaceState avoids piling up history entries as the search box is typed.
  useEffect(() => {
    const params = filtersToSearchParams(filters);
    if (linkedClip) params.set("clip", linkedClip);
    const query = params.toString();
    window.history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
  }, [filters, linkedClip]);

  const [linkCopied, setLinkCopied] = useState(false);
  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setLinkCopied(true);
      setTimeout(() => setLinkCopied(false), 2000);
    } catch {
      // Clipboard access can be denied (e.g. insecure origin); the link is
      // still in the address bar to copy by hand.
    }
  };

  const { data: frequencies } = useFrequencies();
  const recordings = useRecordings(apiFilters);
  const player = usePlayer();
  const { pendingNewClips, onNewRecording } = useWs();

  const items = recordings.data?.pages.flatMap((page) => page.items) ?? [];
  const total = recordings.data?.pages[0]?.total;
  const shouldStagger = useStaggerGate(recordings.data != null && items.length > 0);

  // Track clips that arrived over the stream while the pill was pending, so
  // that the moment the reader folds them in they glow warm and decay.
  const arrivedIds = useRef<Set<number>>(new Set());
  const prevPending = useRef(0);
  const [recentIds, setRecentIds] = useState<Set<number>>(new Set());
  useEffect(
    () => onNewRecording((summary) => arrivedIds.current.add(summary.id)),
    [onNewRecording],
  );
  useEffect(() => {
    if (prevPending.current > 0 && pendingNewClips === 0 && arrivedIds.current.size > 0) {
      const folded = new Set(arrivedIds.current);
      arrivedIds.current.clear();
      setRecentIds(folded);
      const timer = setTimeout(() => setRecentIds(new Set()), 4000);
      prevPending.current = pendingNewClips;
      return () => clearTimeout(timer);
    }
    prevPending.current = pendingNewClips;
  }, [pendingNewClips]);
  const listQueue = playableQueue(items);
  const worthHearingQueue = playableQueue(
    items.filter((clip) => clip.classification?.is_interesting),
  );

  const selectedFreq = frequencies?.items.find((f) => String(f.id) === filters.freqId);
  const activeFilters: { key: string; label: string; clear: () => void }[] = [];
  if (filters.q.trim())
    activeFilters.push({ key: "q", label: `“${filters.q.trim()}”`, clear: () => update({ q: "" }) });
  if (filters.fromDate)
    activeFilters.push({
      key: "from",
      label: `From ${filters.fromDate}`,
      clear: () => update({ fromDate: "" }),
    });
  if (filters.toDate)
    activeFilters.push({
      key: "to",
      label: `To ${filters.toDate}`,
      clear: () => update({ toDate: "" }),
    });
  if (filters.freqId !== "all")
    activeFilters.push({
      key: "freq",
      label: selectedFreq ? freqLabel(selectedFreq.mhz, selectedFreq.label) : "Frequency",
      clear: () => update({ freqId: "all" }),
    });
  if (filters.category !== "all")
    activeFilters.push({
      key: "cat",
      label: categoryWord(filters.category),
      clear: () => update({ category: "all" }),
    });
  if (filters.interestingOnly)
    activeFilters.push({
      key: "interesting",
      label: "Worth hearing only",
      clear: () => update({ interestingOnly: false }),
    });
  if (filters.hasAircraft)
    activeFilters.push({
      key: "aircraft",
      label: "Has aircraft",
      clear: () => update({ hasAircraft: false }),
    });
  if (filters.starredOnly)
    activeFilters.push({
      key: "starred",
      label: "Starred",
      clear: () => update({ starredOnly: false }),
    });

  const clearAllFilters = () => setFilters(emptyFilters);
  const anyActive = hasActiveFilters(filters);

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
        className="flex flex-col gap-4 rounded-xl border bg-card px-4 py-4"
      >
        <div className="flex items-end gap-2">
          <div className="flex flex-1 flex-col gap-1.5">
            <div className="flex items-center gap-1.5">
              <Label htmlFor="clip-search" className="text-sm">
                Search
              </Label>
              <Popover>
                <PopoverTrigger asChild>
                  <button
                    type="button"
                    className="text-muted-foreground transition-colors hover:text-foreground"
                    aria-label="How search works"
                  >
                    <HelpCircle className="size-4" aria-hidden />
                  </button>
                </PopoverTrigger>
                <PopoverContent align="start" className="text-sm">
                  <SearchHelp />
                </PopoverContent>
              </Popover>
            </div>
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                id="clip-search"
                type="search"
                value={filters.q}
                onChange={(e) => update({ q: e.target.value })}
                placeholder={SEARCH_PLACEHOLDER}
                className="h-10 pl-9 text-base"
              />
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="from-date" className="text-sm">
              From
            </Label>
            <Input
              id="from-date"
              type="date"
              value={filters.fromDate}
              onChange={(e) => update({ fromDate: e.target.value })}
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
              value={filters.toDate}
              onChange={(e) => update({ toDate: e.target.value })}
              className="h-10 w-40 text-base"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label className="text-sm">Frequency</Label>
            <Select value={filters.freqId} onValueChange={(v) => update({ freqId: v })}>
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
            <Select value={filters.category} onValueChange={(v) => update({ category: v })}>
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
            <Switch
              checked={filters.interestingOnly}
              onCheckedChange={(v) => update({ interestingOnly: v })}
            />
            Worth hearing only
          </label>
          <label className="flex min-h-10 items-center gap-2 text-base">
            <Switch
              checked={filters.hasAircraft}
              onCheckedChange={(v) => update({ hasAircraft: v })}
            />
            Has aircraft
          </label>
          <label className="flex min-h-10 items-center gap-2 text-base">
            <Switch
              checked={filters.starredOnly}
              onCheckedChange={(v) => update({ starredOnly: v })}
            />
            Starred
          </label>
        </div>
      </section>

      {activeFilters.length > 0 && (
        <div className="flex flex-wrap items-center gap-2" aria-label="Active filters">
          <span className="text-sm text-muted-foreground">Showing:</span>
          {activeFilters.map((filter) => (
            <button
              key={filter.key}
              type="button"
              onClick={filter.clear}
              className="inline-flex min-h-8 items-center gap-1.5 rounded-full bg-secondary px-3 text-sm text-secondary-foreground transition-colors hover:opacity-80"
              aria-label={`Remove filter: ${filter.label}`}
            >
              {filter.label}
              <X className="size-3.5" aria-hidden />
            </button>
          ))}
          <Button variant="ghost" className="min-h-8 px-2 text-sm" onClick={clearAllFilters}>
            Clear filters
          </Button>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm text-muted-foreground" aria-live="polite">
          {total != null &&
            `${total} ${total === 1 ? "clip" : "clips"}${anyActive ? " match these filters" : ""}`}
        </span>
        <div className="flex items-center gap-2">
          <Button variant="ghost" className="min-h-10" onClick={copyLink}>
            {linkCopied ? (
              <>
                <Check className="size-4" />
                Link copied
              </>
            ) : (
              <>
                <Link2 className="size-4" />
                Copy link
              </>
            )}
          </Button>
          {worthHearingQueue.length > 0 && (
            <Button
              variant="outline"
              className="min-h-10"
              onClick={() => player.playQueue(worthHearingQueue, worthHearingQueue[0].id)}
            >
              <Play className="size-4" />
              Play all worth hearing
            </Button>
          )}
        </div>
      </div>

      <NewClipsPill />

      {linkedId != null && !linkedVisible && <LinkedClip id={linkedId} />}

      {recordings.isPending && (
        <div className="flex flex-col gap-4" aria-hidden>
          {[0, 1, 2].map((i) => (
            <ClipCardSkeleton key={i} />
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
          <p className="text-lg">No clips match.</p>
          <p className="mt-2 text-base text-muted-foreground">
            {filters.q.trim()
              ? "Try fewer words, or drop a freq:/callsign: token from your search."
              : "Widen the dates or switch off a filter to see more of the archive."}
          </p>
        </div>
      )}

      <section className="flex flex-col gap-4" aria-label="Clip list">
        {items.map((clip, i) => (
          <div
            key={clip.id}
            className={shouldStagger ? "clip-enter" : undefined}
            style={shouldStagger ? { animationDelay: `${Math.min(i, 8) * 40}ms` } : undefined}
          >
            <ClipCard
              clip={clip}
              queue={listQueue}
              highlight={recentIds.has(clip.id)}
              expanded={expandedId === clip.id}
              onToggle={(id) => setExpandedId((cur) => (cur === id ? null : id))}
            />
          </div>
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

function SearchHelp() {
  return (
    <div className="flex flex-col gap-2">
      <p className="font-medium">Searching clips</p>
      <p className="text-muted-foreground">
        Type words to search the transcripts. Wrap a phrase in quotes to keep it together. Add any of
        these to narrow the results:
      </p>
      <ul className="flex flex-col gap-1 text-muted-foreground">
        <li>
          <code className="text-foreground">freq:121.5</code> or{" "}
          <code className="text-foreground">freq:tower</code> — one frequency
        </li>
        <li>
          <code className="text-foreground">callsign:BAW2761</code> — a matched aircraft
        </li>
        <li>
          <code className="text-foreground">interesting</code> — worth-hearing clips only
        </li>
        <li>
          <code className="text-foreground">after:2026-07-01</code>,{" "}
          <code className="text-foreground">before:2026-07-10</code> — a date range
        </li>
      </ul>
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
      <ClipCard clip={data} expanded={expanded} onToggle={() => setExpanded((cur) => !cur)} />
    </div>
  );
}
