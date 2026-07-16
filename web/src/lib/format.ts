/** Station-local presentation: Europe/London, friendly dates, 24-hour times. */

const ZONE = "Europe/London";

const dayFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: ZONE,
  weekday: "long",
  day: "numeric",
  month: "long",
});

const weekdayFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: ZONE,
  weekday: "long",
});

const timeFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: ZONE,
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const isoDayFormat = new Intl.DateTimeFormat("en-CA", {
  timeZone: ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** "Tuesday 8 July" */
export function friendlyDate(isoDay: string): string {
  return dayFormat.format(new Date(`${isoDay}T12:00:00Z`)).replace(",", "");
}

/** "Tuesday" */
export function weekday(isoDay: string): string {
  return weekdayFormat.format(new Date(`${isoDay}T12:00:00Z`));
}

/** "14:07" from a UTC timestamp. */
export function clockTime(utc: string): string {
  return timeFormat.format(new Date(ensureUtc(utc)));
}

/** Today's date in the station's timezone, as YYYY-MM-DD. */
export function todayIso(): string {
  return isoDayFormat.format(new Date());
}

/** The UTC timestamp's local calendar day, as YYYY-MM-DD. */
export function localDay(utc: string): string {
  return isoDayFormat.format(new Date(ensureUtc(utc)));
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
function ensureUtc(value: string): string {
  return API_TIMESTAMP_HAS_ZONE.test(value) ? value : `${value}Z`;
}
