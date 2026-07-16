import { BadgeCheck } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { AircraftMatchResource } from "@/lib/api/client";
import { categoryWord, matchTier, TIER_WORD } from "@/lib/tiers";
import { cn } from "@/lib/utils";

/** "Probably BA2761 · British Airways · 3 km away" */
export function TierChip({ match, className }: { match: AircraftMatchResource; className?: string }) {
  const tier = matchTier(match.match_confidence);
  const who = match.callsign?.trim() || match.icao24.toUpperCase();
  const parts = [
    match.flight_number_guess ? `${who} (maybe ${match.flight_number_guess})` : who,
    match.airline_name,
    `${Math.round(match.distance_km)} km away`,
  ].filter(Boolean);

  return (
    <span
      className={cn(
        "inline-flex min-h-8 items-center gap-1.5 rounded-full border px-3 text-sm",
        tier === "probably" && "border-transparent bg-secondary text-secondary-foreground",
        tier === "possibly" && "bg-transparent text-foreground",
        tier === "unsure" && "border-dashed bg-transparent text-muted-foreground",
        className,
      )}
    >
      <span className="font-medium">{TIER_WORD[tier]}</span>
      <span>{parts.join(" · ")}</span>
    </span>
  );
}

export function InterestingBadge({ category }: { category: string }) {
  return (
    <Badge className="bg-interesting-surface text-sm text-interesting-surface-foreground">
      {category === "routine" ? "Worth hearing" : categoryWord(category)}
    </Badge>
  );
}

export function RoutineBadge({ category }: { category: string }) {
  return (
    <Badge variant="secondary" className="text-sm font-normal text-muted-foreground">
      {categoryWord(category)}
    </Badge>
  );
}

export function RoughTranscriptBadge() {
  return (
    <Badge variant="outline" className="text-sm font-normal text-muted-foreground">
      rough transcript
    </Badge>
  );
}

export function VerifyBadge() {
  return (
    <Badge variant="outline" className="gap-1 text-sm font-normal text-health-warn">
      <BadgeCheck className="size-3.5" aria-hidden />
      verify
    </Badge>
  );
}

export type Health = "good" | "warn" | "bad";

export function HealthChip({ health, label }: { health: Health; label: string }) {
  return (
    <span
      className={cn(
        "inline-flex min-h-8 items-center gap-2 rounded-full px-3 text-sm font-medium",
        health === "good" && "bg-health-good-surface text-health-good",
        health === "warn" && "bg-health-warn-surface text-health-warn",
        health === "bad" && "bg-health-bad-surface text-health-bad",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "size-2 rounded-full",
          health === "good" && "bg-health-good",
          health === "warn" && "bg-health-warn",
          health === "bad" && "bg-health-bad",
        )}
      />
      {label}
    </span>
  );
}
