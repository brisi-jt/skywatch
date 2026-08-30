/** Station-local presentation: friendly dates, 24-hour times.
 *
 * The display timezone is the station's own, reported by `/status` rather than
 * hardcoded. `setDisplayZone` updates it once status loads; until then it falls
 * back to Europe/London (the shipped default). Formatters are cached per zone. */

const DEFAULT_ZONE = "Europe/London";

let displayZone = DEFAULT_ZONE;

interface ZoneFormatters {
  day: Intl.DateTimeFormat;
  weekday: Intl.DateTimeFormat;
  time: Intl.DateTimeFormat;
  isoDay: Intl.DateTimeFormat;
}

const formatterCache = new Map<string, ZoneFormatters>();

function formatters(): ZoneFormatters {
  const zone = displayZone;
  let cached = formatterCache.get(zone);
  if (!cached) {
    cached = {
      day: new Intl.DateTimeFormat("en-GB", {
        timeZone: zone,
        weekday: "long",
        day: "numeric",
        month: "long",
      }),
      weekday: new Intl.DateTimeFormat("en-GB", { timeZone: zone, weekday: "long" }),
      time: new Intl.DateTimeFormat("en-GB", {
        timeZone: zone,
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }),
      isoDay: new Intl.DateTimeFormat("en-CA", {
        timeZone: zone,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }),
    };
    formatterCache.set(zone, cached);
  }
  return cached;
}

/** Set the timezone used for every clock and calendar-day format (from /status). */
export function setDisplayZone(zone: string | null | undefined): void {
  if (zone) displayZone = zone;
}

/** "Tuesday 8 July" */
export function friendlyDate(isoDay: string): string {
  return formatters()
    .day.format(new Date(`${isoDay}T12:00:00Z`))
    .replace(",", "");
}

/** "Tuesday" */
export function weekday(isoDay: string): string {
  return formatters().weekday.format(new Date(`${isoDay}T12:00:00Z`));
}

/** "14:07" from a UTC timestamp. */
export function clockTime(utc: string): string {
  return formatters().time.format(new Date(ensureUtc(utc)));
}

/** Today's date in the station's timezone, as YYYY-MM-DD. */
export function todayIso(): string {
  return formatters().isoDay.format(new Date());
}

/** The UTC timestamp's local calendar day, as YYYY-MM-DD. */
export function localDay(utc: string): string {
  return formatters().isoDay.format(new Date(ensureUtc(utc)));
}

export function shiftDay(isoDay: string, delta: number): string {
  const d = new Date(`${isoDay}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + delta);
  return d.toISOString().slice(0, 10);
}

/** "118.190" — frequencies always to three decimal places. */
export function mhz(value: number): string {
  return value.toFixed(3);
}

/** "118.190 · Stansted Tower" */
export function freqLabel(value: number, label: string): string {
  return `${mhz(value)} · ${label}`;
}

/** "0:07" clip length. */
export function durationLabel(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function gb(value: number): string {
  return `${value.toFixed(1)} GB`;
}

const API_TIMESTAMP_HAS_ZONE = /(Z|[+-]\d{2}:?\d{2})$/;

/** API timestamps are UTC; some arrive without an explicit zone suffix. */
export function ensureUtc(value: string): string {
  return API_TIMESTAMP_HAS_ZONE.test(value) ? value : `${value}Z`;
}
