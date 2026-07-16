"use client";

import { useState } from "react";

import { VerifyBadge } from "@/components/chips";
import { Switch } from "@/components/ui/switch";
import type { FrequencyResource } from "@/lib/api/client";
import { ApiError, useFrequencyAction } from "@/lib/api/hooks";
import { mhz } from "@/lib/format";
import { facilityWord } from "@/lib/tiers";

interface Conflict {
  detail: string;
  offenders: string[];
  suggestedCenterfreq: number | null;
}

export function FrequencyTable({ frequencies }: { frequencies: FrequencyResource[] }) {
  const action = useFrequencyAction();
  const [conflict, setConflict] = useState<Conflict | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [busyId, setBusyId] = useState<number | null>(null);

  const toggle = (freq: FrequencyResource, active: boolean) => {
    setConflict(null);
    setWarnings([]);
    setBusyId(freq.id);
    action.mutate(
      { freqId: freq.id, action: active ? "activate" : "deactivate" },
      {
        onSuccess: (response) => setWarnings(response.warnings),
        onError: (error) => {
          if (error instanceof ApiError && error.problem?.code === "window_conflict") {
            const problem = error.problem as unknown as Record<string, unknown>;
            setConflict({
              detail: error.problem.detail ?? "These frequencies do not fit together.",
              offenders: Array.isArray(problem.offenders) ? (problem.offenders as string[]) : [],
              suggestedCenterfreq:
                typeof problem.suggested_centerfreq_mhz === "number"
                  ? problem.suggested_centerfreq_mhz
                  : null,
            });
          } else {
            setWarnings([
              error instanceof ApiError
                ? error.message
                : "The change could not be applied — try again.",
            ]);
          }
        },
        onSettled: () => setBusyId(null),
      },
    );
  };

  return (
    <div className="flex flex-col gap-3">
      {conflict && (
        <div className="rounded-xl border border-health-warn/40 bg-health-warn-surface px-4 py-3">
          <p className="text-base font-medium text-health-warn">
            These frequencies don’t fit in one radio window
          </p>
          <p className="mt-1 text-base">{conflict.detail}</p>
          {conflict.offenders.length > 0 && (
            <p className="mt-1 text-sm text-muted-foreground">
              In the way: {conflict.offenders.join(", ")}. Deactivate one of them, or switch the
              station to scan mode.
            </p>
          )}
          {conflict.suggestedCenterfreq != null && (
            <p className="mt-1 font-mono text-sm text-readout">
              Suggested centre: {mhz(conflict.suggestedCenterfreq)} MHz
            </p>
          )}
        </div>
      )}

      {warnings.map((warning) => (
        <p
          key={warning}
          className="rounded-xl border bg-card px-4 py-3 text-base text-muted-foreground"
        >
          {warning}
        </p>
      ))}

      <div className="overflow-x-auto rounded-xl border bg-card">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b text-sm text-muted-foreground">
              <th scope="col" className="px-4 py-3 font-medium">
                Frequency
              </th>
              <th scope="col" className="px-4 py-3 font-medium">
                MHz
              </th>
              <th scope="col" className="hidden px-4 py-3 font-medium sm:table-cell">
                Facility
              </th>
              <th scope="col" className="hidden px-4 py-3 font-medium md:table-cell">
                Type
              </th>
              <th scope="col" className="px-4 py-3 text-right font-medium">
                Listening
              </th>
            </tr>
          </thead>
          <tbody>
            {frequencies.map((freq) => (
              <tr key={freq.id} className="border-b last:border-b-0">
                <td className="px-4 py-3">
                  <span className="flex flex-wrap items-center gap-2 text-base font-medium">
                    {freq.label}
                    {!freq.verified && <VerifyBadge />}
                  </span>
                  <span className="text-sm text-muted-foreground sm:hidden">
                    {freq.facility}
                  </span>
                </td>
                <td className="px-4 py-3 font-mono text-base text-readout">{mhz(freq.mhz)}</td>
                <td className="hidden px-4 py-3 text-base sm:table-cell">{freq.facility}</td>
                <td className="hidden px-4 py-3 text-base text-muted-foreground md:table-cell">
                  {facilityWord(freq.category)}
                </td>
                <td className="px-4 py-3 text-right">
                  <Switch
                    checked={freq.is_active}
                    disabled={busyId !== null}
                    onCheckedChange={(next) => toggle(freq, next)}
                    aria-label={`${freq.is_active ? "Stop" : "Start"} listening on ${freq.label}`}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
