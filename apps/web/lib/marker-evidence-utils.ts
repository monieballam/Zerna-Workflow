/**
 * Explorer cluster-inspector display filtering.
 *
 * UI-only display filtering for cluster-inspector marker lists.
 * Does not change persisted h5ad / annotation labels.
 */

const DEFAULT_CELL_CYCLE_GENES = new Set<string>([
  'MKI67',
  'TOP2A',
  'PCNA',
  'CDK1',
  'CCNB1',
  'CCNB2',
  'STMN1',
  'UBE2C',
  'BIRC5',
  'TYMS',
]);

/** Common ribosomal / mitochondrial / heat-shock prefixes. */
const NOISE_PREFIXES = ['RPL', 'RPS', 'MRPL', 'MRPS', 'MT-', 'HSP'] as const;

const NOISE_EXACT = new Set<string>(['MALAT1', 'NEAT1', 'FOS', 'JUN', 'EEF1A1', 'TPT1']);

export type NoiseGeneOptions = {
  allowCellCycle?: boolean;
  /** Stop after this many informative genes (deduped, order preserved). */
  maxOut?: number | null;
};

/**
 * True if the gene should not be shown as primary interpretive evidence in the cluster inspector.
 */
export function isNoiseGeneMarkerForDisplay(symbol: string, opts?: NoiseGeneOptions): boolean {
  if (symbol == null || typeof symbol !== 'string') {
    return true;
  }
  const g = symbol.trim().toUpperCase();
  if (!g) {
    return true;
  }
  if (NOISE_EXACT.has(g)) {
    return true;
  }
  for (const p of NOISE_PREFIXES) {
    if (g.startsWith(p)) {
      return true;
    }
  }
  if (!opts?.allowCellCycle && DEFAULT_CELL_CYCLE_GENES.has(g)) {
    return true;
  }
  if (/^HSP[A-Z0-9]*$/.test(g)) {
    return true;
  }
  return false;
}

/**
 * Return genes in input order, excluding noise genes; optionally cap length.
 */
export function filterNoiseGenesForDisplay(
  genes: Iterable<string>,
  opts?: NoiseGeneOptions
): string[] {
  const maxOut = opts?.maxOut ?? null;
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of genes) {
    if (isNoiseGeneMarkerForDisplay(raw, opts)) {
      continue;
    }
    const g = String(raw).trim();
    if (!g || seen.has(g)) {
      continue;
    }
    seen.add(g);
    out.push(g);
    if (maxOut != null && out.length >= maxOut) {
      break;
    }
  }
  return out;
}

/**
 * Distinctive / DE-style list for display: drop noise, preserve order, cap length.
 */
export function rankDistinctiveMarkers(markers: string[], max = 8): string[] {
  return filterNoiseGenesForDisplay(markers, { maxOut: max });
}

export function subtractGenes(base: string[], remove: Set<string>): string[] {
  return base.filter((g) => !remove.has(g.trim()));
}
