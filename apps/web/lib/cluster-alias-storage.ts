const STORAGE_PREFIX = 'zerna-explorer-cluster-alias:';

/** Legacy key (pre–view-scoped storage): one map per run, folded into global reads. */
function legacyKeyForRun(runId: string): string {
  return `${STORAGE_PREFIX}${runId}`;
}

function scopedKeyForRun(runId: string, viewScope: string): string {
  return `${STORAGE_PREFIX}${runId}:${viewScope}`;
}

function parseAliasesRaw(raw: string | null): Record<string, string> {
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof v === 'string' && v.trim()) out[k] = v.trim();
    }
    return out;
  } catch {
    return {};
  }
}

/**
 * Global aliases (Leiden-style ids, mirrored from lineage renames when ``globalCluster`` links exist).
 * Includes legacy single-bucket key for the run.
 */
export function loadGlobalAliases(runId: string): Record<string, string> {
  if (typeof window === 'undefined') return {};
  let raw = window.localStorage.getItem(scopedKeyForRun(runId, 'global'));
  if (!raw) raw = window.localStorage.getItem(legacyKeyForRun(runId));
  return parseAliasesRaw(raw);
}

/**
 * Overrides for a non-global explorer embedding only (lineage / fine views).
 * Does not include global entries — merge with loadGlobalAliases for display.
 */
export function loadViewOverrideAliases(runId: string, viewScope: string): Record<string, string> {
  if (typeof window === 'undefined' || viewScope === 'global') return {};
  const raw = window.localStorage.getItem(scopedKeyForRun(runId, viewScope));
  return parseAliasesRaw(raw);
}

/**
 * Effective alias map for the active embedding: ``global ∪ viewOverrides`` (overrides win).
 */
export function loadClusterAliases(
  runId: string,
  viewScope: string = 'global'
): Record<string, string> {
  const global = loadGlobalAliases(runId);
  if (viewScope === 'global') return { ...global };
  const ov = loadViewOverrideAliases(runId, viewScope);
  return { ...global, ...ov };
}

export function saveGlobalAliases(runId: string, aliases: Record<string, string>): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(scopedKeyForRun(runId, 'global'), JSON.stringify(aliases));
  } catch {
    // quota / private mode
  }
}

export function saveViewOverrideAliases(
  runId: string,
  viewScope: string,
  aliases: Record<string, string>
): void {
  if (typeof window === 'undefined') return;
  if (viewScope === 'global') {
    saveGlobalAliases(runId, aliases);
    return;
  }
  try {
    window.localStorage.setItem(scopedKeyForRun(runId, viewScope), JSON.stringify(aliases));
  } catch {
    // quota / private mode
  }
}

export function clusterDisplayLabel(
  clusterId: string,
  assignedLabel: string,
  aliases: Record<string, string>,
  opts?: { linkedGlobalClusterId?: string | null }
): string {
  const id = String(clusterId).trim();
  const direct = aliases[id]?.trim();
  if (direct) return direct;
  const g = opts?.linkedGlobalClusterId != null ? String(opts.linkedGlobalClusterId).trim() : '';
  if (g) {
    const via = aliases[g]?.trim();
    if (via) return via;
  }
  return assignedLabel;
}
