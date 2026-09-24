/**
 * Shared date formatting utilities.
 *
 * All API timestamps are UTC but may arrive without a trailing "Z".
 * `parseUTC` normalises this so the browser interprets them correctly.
 */

/** Parse an ISO timestamp that may be missing the trailing Z (UTC marker). */
export function parseUTC(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  // If the string has no timezone info, treat it as UTC
  const normalized =
    iso.endsWith('Z') || iso.includes('+') || iso.includes('-', 10) ? iso : iso + 'Z';
  return new Date(normalized);
}

/** Short date+time in the user's local timezone. */
export function formatDateTime(iso: string | null | undefined): string {
  const d = parseUTC(iso);
  if (!d) return '—';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** Date only in the user's local timezone. */
export function formatDate(iso: string | null | undefined): string {
  const d = parseUTC(iso);
  if (!d) return '—';
  return d.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

/** Human-readable duration between two ISO timestamps. */
export function formatDuration(
  startedAt: string | null | undefined,
  completedAt: string | null | undefined
): string {
  const start = parseUTC(startedAt);
  if (!start) return '—';
  const end = parseUTC(completedAt) ?? new Date();
  const ms = end.getTime() - start.getTime();
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ${secs % 60}s`;
  return `${Math.floor(mins / 60)}h ${mins % 60}m`;
}
