"use client";

import { RadioTower, WifiOff } from "lucide-react";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import { SkyAircraftPanel } from "@/components/sky-aircraft-panel";
import { useSky } from "@/lib/api/hooks";
import { deriveSkyState, findOverheadAircraft } from "@/lib/sky";
import { useWs } from "@/lib/ws";

const SkyMap = dynamic(() => import("@/components/sky-map").then((mod) => mod.SkyMap), {
  ssr: false,
  loading: () => <SkyMapPlaceholder />,
});

/** How long the "heard just now" ring stays lit on a matched aircraft. */
const PULSE_DURATION_MS = 1500;

export default function SkyPage() {
  return (
    <Suspense>
      <SkyView />
    </Suspense>
  );
}

function SkyView() {
  const params = useSearchParams();
  const linkedHex = params.get("hex");

  const sky = useSky();
  const { onNewRecording } = useWs();
  const [selectedHex, setSelectedHex] = useState<string | null>(null);
  const [pulsingHex, setPulsingHex] = useState<string | null>(null);
  const pulseTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // A clip's "overhead now" chip lands here with ?hex=; open that aircraft's
  // panel as soon as the live picture confirms it. Only fires once per hex —
  // if the reader closes the panel again, it stays closed.
  const openedLinkedHex = useRef<string | null>(null);
  useEffect(() => {
    if (!linkedHex || openedLinkedHex.current === linkedHex) return;
    const match = findOverheadAircraft(linkedHex, sky.data?.aircraft);
    if (match) {
      setSelectedHex(match.hex);
      openedLinkedHex.current = linkedHex;
    }
  }, [linkedHex, sky.data]);

  useEffect(
    () =>
      onNewRecording((summary) => {
        const hex = summary.top_match?.icao24;
        if (!hex) return;
        setPulsingHex(hex);
        if (pulseTimer.current) clearTimeout(pulseTimer.current);
        pulseTimer.current = setTimeout(() => setPulsingHex(null), PULSE_DURATION_MS);
      }),
    [onNewRecording],
  );
  useEffect(
    () => () => {
      if (pulseTimer.current) clearTimeout(pulseTimer.current);
    },
    [],
  );

  const data = sky.data;
  const state = deriveSkyState({ isPending: sky.isPending, isError: sky.isError, data });
  const selectedAircraft = useMemo(
    () => (selectedHex ? (data?.aircraft.find((a) => a.hex === selectedHex) ?? null) : null),
    [selectedHex, data],
  );
  const hasStation = data?.station_lat != null && data?.station_lon != null;

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="font-display text-3xl font-semibold tracking-tight">Sky</h1>
        <p className="mt-1 text-base text-muted-foreground">
          {data?.source && data.attribution
            ? `Live positions within ${Math.round(data.radius_nm)} nm — ${data.attribution}`
            : "What's overhead right now, fused with what the station has heard."}
        </p>
      </header>

      {state === "loading" && <SkyMapPlaceholder />}

      {state === "offline" && (
        <div className="rounded-xl border bg-card px-6 py-10 text-center">
          <WifiOff className="mx-auto size-8 text-muted-foreground" aria-hidden />
          <p className="mt-3 text-lg">The station could not be reached.</p>
          <p className="mt-1 text-base text-muted-foreground">
            Retrying automatically — no need to refresh this page.
          </p>
        </div>
      )}

      {state === "sources-down" && (
        <div className="rounded-xl border bg-card px-6 py-10 text-center">
          <RadioTower className="mx-auto size-8 text-muted-foreground" aria-hidden />
          <p className="mt-3 text-lg">The live aircraft sources are unreachable right now.</p>
          <p className="mt-1 text-base text-muted-foreground">
            Trying again automatically — the radio itself keeps listening regardless.
          </p>
        </div>
      )}

      {(state === "quiet" || state === "ready") && data && hasStation && (
        <div className="flex flex-col gap-3">
          <div className="h-[60vh] min-h-[420px] overflow-hidden rounded-xl border">
            <SkyMap
              aircraft={data.aircraft}
              stationLat={data.station_lat as number}
              stationLon={data.station_lon as number}
              focusHex={selectedHex}
              pulsingHex={pulsingHex}
              onSelectAircraft={setSelectedHex}
            />
          </div>
          {state === "quiet" && (
            <p className="text-center text-base text-muted-foreground">
              Nothing overhead within {Math.round(data.radius_nm)} nm — the station is still
              listening.
            </p>
          )}
        </div>
      )}

      <SkyAircraftPanel
        aircraft={selectedAircraft}
        onOpenChange={(open) => {
          if (!open) setSelectedHex(null);
        }}
      />
    </div>
  );
}

function SkyMapPlaceholder() {
  return (
    <div
      className="flex h-[60vh] min-h-[420px] items-center justify-center rounded-xl border bg-card"
      aria-live="polite"
    >
      <p className="text-base text-muted-foreground">Loading the map…</p>
    </div>
  );
}
