"use client";

/**
 * The Leaflet map itself — loaded only on the client (it touches `window`),
 * via a `next/dynamic(..., { ssr: false })` import in the Sky page. A real
 * OSM basemap dressed as an instrument: range rings and aircraft glyphs are
 * plain SVG/DOM layers styled from `globals.css`, not baked into tiles.
 */

import L from "leaflet";
import { useEffect, useMemo, useRef } from "react";
import { Circle, MapContainer, Marker, TileLayer, useMap } from "react-leaflet";

import type { SkyAircraftResource } from "@/lib/api/client";
import { aircraftLabel, matchesIcao } from "@/lib/sky";

const RING_RADII_M = [10_000, 20_000, 40_000];
const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors';

function stationIcon(): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<div class="sky-station-glyph" style="transform: translate(-50%, -50%);">
      <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
        <circle cx="9" cy="9" r="3" fill="currentColor" />
        <circle cx="9" cy="9" r="7" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.5" />
      </svg>
    </div>`,
    iconSize: [0, 0],
  });
}

function aircraftIcon(aircraft: SkyAircraftResource, pulsing: boolean): L.DivIcon {
  const heading = aircraft.track ?? 0;
  const label = aircraftLabel(aircraft);
  return L.divIcon({
    className: "",
    html: `
      <div class="flex flex-col items-center gap-0.5 cursor-pointer" style="transform: translate(-50%, -50%);">
        <div class="relative flex items-center justify-center${pulsing ? " sky-heard-pulse" : ""}">
          <svg class="sky-aircraft-glyph" data-heard="${aircraft.heard_recently}"
               width="14" height="14" viewBox="0 0 14 14"
               style="transform: rotate(${heading}deg);" aria-hidden="true">
            <path d="M7 0 L12 12 L7 9 L2 12 Z" fill="currentColor" />
          </svg>
        </div>
        <span class="sky-aircraft-label rounded px-1 text-[0.65rem] leading-tight">${label}</span>
      </div>
    `,
    iconSize: [0, 0],
  });
}

/** Re-centres the map on a hex when it changes — a deep link or the
 * "overhead now" chip jump, never on the recurring 10 s poll. */
function FlyTo({
  hex,
  aircraft,
  fallback,
}: {
  hex: string | null;
  aircraft: SkyAircraftResource[];
  fallback: [number, number];
}) {
  const map = useMap();
  const aircraftRef = useRef(aircraft);
  aircraftRef.current = aircraft;

  useEffect(() => {
    if (!hex) return;
    const match = aircraftRef.current.find((a) => matchesIcao(a.hex, hex));
    const target: [number, number] =
      match?.lat != null && match?.lon != null ? [match.lat, match.lon] : fallback;
    map.flyTo(target, 11, { duration: 0.6 });
    // Only re-fires when the requested hex itself changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hex]);

  return null;
}

export function SkyMap({
  aircraft,
  stationLat,
  stationLon,
  focusHex,
  pulsingHex,
  onSelectAircraft,
}: {
  aircraft: SkyAircraftResource[];
  stationLat: number;
  stationLon: number;
  /** Re-centre on this hex (deep link from a clip's "overhead now" chip). */
  focusHex: string | null;
  /** Give this hex a one-shot "heard just now" pulse. */
  pulsingHex: string | null;
  onSelectAircraft: (hex: string) => void;
}) {
  const station = useMemo<[number, number]>(() => [stationLat, stationLon], [stationLat, stationLon]);
  const stationIconRef = useRef<L.DivIcon>(undefined);
  stationIconRef.current ??= stationIcon();

  return (
    <MapContainer center={station} zoom={9} className="sky-map" scrollWheelZoom>
      <TileLayer url={TILE_URL} attribution={ATTRIBUTION} />
      {RING_RADII_M.map((radius) => (
        <Circle
          key={radius}
          center={station}
          radius={radius}
          pathOptions={{ className: "sky-ring" }}
          interactive={false}
        />
      ))}
      <Marker position={station} icon={stationIconRef.current} interactive={false} />
      {aircraft
        .filter((a): a is SkyAircraftResource & { lat: number; lon: number } => a.lat != null && a.lon != null)
        .map((a) => (
          <Marker
            key={a.hex}
            position={[a.lat, a.lon]}
            icon={aircraftIcon(a, matchesIcao(a.hex, pulsingHex))}
            eventHandlers={{ click: () => onSelectAircraft(a.hex) }}
          />
        ))}
      <FlyTo hex={focusHex} aircraft={aircraft} fallback={station} />
    </MapContainer>
  );
}
