/**
 * The browser owns the timezone.
 *
 * `datetime-local` gives a wall-clock string with no zone, which the Date
 * constructor reads in the viewer's local time. Converting to an ISO instant
 * here means the server never has to guess what "09:00" meant — it stores and
 * compares UTC only.
 */

/** Format a Date for a `datetime-local` input (local wall clock, no zone). */
export function toLocalInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

/** A `datetime-local` value -> UTC ISO instant. Empty stays empty. */
export function localInputToUtcIso(value: string): string {
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "" : parsed.toISOString();
}

/** The soonest time the picker should allow: a minute from now. */
export function earliestSelectable(): string {
  return toLocalInputValue(new Date(Date.now() + 60_000));
}

export function formatAbsolute(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "in 3 hours" / "2 minutes ago", using the viewer's locale. */
export function formatRelative(iso: string, from: Date = new Date()): string {
  const deltaMs = new Date(iso).getTime() - from.getTime();
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["day", 86_400_000],
    ["hour", 3_600_000],
    ["minute", 60_000],
  ];

  for (const [unit, ms] of units) {
    if (Math.abs(deltaMs) >= ms) {
      return formatter.format(Math.round(deltaMs / ms), unit);
    }
  }
  return formatter.format(Math.round(deltaMs / 1000), "second");
}
