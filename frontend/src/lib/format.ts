/** Small formatting helpers shared across the knowledge UI. */

export function formatCount(value?: number): string {
  if (value === undefined) return "—";
  return value.toLocaleString("en-US");
}

/** Format a 0–1 fraction as a whole percentage. */
export function formatPercent(fraction?: number): string {
  if (fraction === undefined) return "—";
  const clamped = Math.max(0, Math.min(1, fraction));
  return `${Math.round(clamped * 100)}%`;
}

export function formatBytes(bytes?: number): string {
  if (bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

export function formatMs(ms?: number): string {
  if (ms === undefined) return "—";
  return `${ms < 10 ? ms.toFixed(1) : Math.round(ms)} ms`;
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * "8 minutes ago" / "in 2 days" phrasing for timestamps.
 */
export function formatRelative(value?: number): string {
  if (!value) return "—";
  const diff = Date.now() - value;
  const abs = Math.abs(diff);
  const prefix = (text: string) => (diff >= 0 ? `${text} ago` : `in ${text}`);
  const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? "" : "s"}`;

  if (abs < 45_000) return diff >= 0 ? "just now" : "in a moment";
  if (abs < HOUR) return prefix(plural(Math.round(abs / MINUTE), "minute"));
  if (abs < DAY) return prefix(plural(Math.round(abs / HOUR), "hour"));
  if (abs < 30 * DAY) return prefix(plural(Math.round(abs / DAY), "day"));
  return new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** "Today, 12:42 PM" style timestamp, local time. */
export function formatDateTime(value?: number): string {
  if (!value) return "—";
  const date = new Date(value);
  const today = new Date();
  const isToday = date.toDateString() === today.toDateString();
  const yesterday = new Date(today.getTime() - DAY);
  const isYesterday = date.toDateString() === yesterday.toDateString();
  const clock = date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
  if (isToday) return `Today, ${clock}`;
  if (isYesterday) return `Yesterday, ${clock}`;
  return `${date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  })}, ${clock}`;
}

/** "12:42 PM" style clock, local time. */
export function formatClock(date: Date): string {
  return date.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Line range label such as "Lines 118–156". */
export function formatLines(start?: number, end?: number): string | null {
  if (start === undefined && end === undefined) return null;
  if (start !== undefined && end !== undefined) {
    return start === end ? `Line ${start}` : `Lines ${start}–${end}`;
  }
  return `Line ${start ?? end}`;
}
