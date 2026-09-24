/**
 * Shorter text for in-plot centroid labels. Full strings stay in legend / metadata.
 * Prefers the last segment of hierarchy-like strings (pipes, arrows, slashes).
 */
export function shortenPlotLabel(raw: string): string {
  const s = raw.trim();
  if (!s) return '';
  const split = s
    .split(/\s*[|›>]\s*|\s*\/\s+/)
    .map((x) => x.trim())
    .filter(Boolean);
  const last = split.length > 0 ? split[split.length - 1] : s;
  const head = last.split(',')[0]?.trim() ?? last;
  if (head.length <= 32) return head;
  return `${head.slice(0, 29)}…`;
}
