/**
 * Normalize ligand–receptor result rows to canonical columns for dashboard views.
 */

/** How to interpret the numeric `score` field for sorting, tooltips, and aggregations. */
export type ScoreSemantics = 'strength' | 'rank' | 'unknown';

export interface NormalizedLRRow {
  sender: string;
  receiver: string;
  ligand: string;
  receptor: string;
  score: number;
  /** Artifact column used to populate `score` (original header from the row). */
  score_source: string;
  /** Whether `score` is a communication strength, a rank (lower = better for LIANA-style ranks), or unknown. */
  score_semantics: ScoreSemantics;
  /** Human-readable p-value (original string when available). */
  p_value: string;
  /** For sorting / threshold filters; null when not parseable. */
  p_value_numeric: number | null;
  interaction_name: string;
  /** Original row as returned by the artifact preview API. */
  raw: Record<string, unknown>;
}

const SENDER_ALIASES = [
  'sender',
  'source',
  'source_cell',
  'source_celltype',
  'from',
  'source_cluster',
] as const;

const RECEIVER_ALIASES = [
  'receiver',
  'target',
  'target_cell',
  'target_celltype',
  'to',
  'target_cluster',
] as const;

const LIGAND_ALIASES = ['ligand', 'ligand_gene', 'ligand_complex'] as const;

const RECEPTOR_ALIASES = ['receptor', 'receptor_gene', 'receptor_complex'] as const;

/** Aliases whose values are higher-is-stronger (or signed strength) communication scores. */
const STRENGTH_SCORE_ALIASES = [
  'score',
  'interaction_score',
  'weight',
  'strength',
  'lrscore',
  'lr_means',
] as const;

/** Aliases whose values are ranks (lower numeric rank = better in LIANA-style outputs). */
const RANK_SCORE_ALIASES = ['aggregate_rank', 'liana_rank'] as const;

const P_ALIASES = ['p_value', 'pvalue', 'p_val', 'adj_p_value', 'fdr', 'cellphone_pvals'] as const;

/** Normalize object keys for alias lookup (case- and spacing-insensitive). */
function buildKeyIndex(row: Record<string, unknown>): Map<string, string> {
  const m = new Map<string, string>();
  for (const k of Object.keys(row)) {
    const norm = k.toLowerCase().replace(/\s+/g, '_');
    if (!m.has(norm)) m.set(norm, k);
  }
  return m;
}

function isNonEmptyPrimitiveValue(value: unknown): value is string | number | boolean {
  return (
    value !== null &&
    value !== undefined &&
    (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') &&
    String(value).trim() !== ''
  );
}

function pickField(
  row: Record<string, unknown>,
  index: Map<string, string>,
  aliases: readonly string[]
) {
  for (const a of aliases) {
    const orig = index.get(a);
    const value = orig !== undefined ? row[orig] : undefined;
    if (isNonEmptyPrimitiveValue(value)) {
      return value;
    }
  }
  return undefined;
}

function pickScoreWithMeta(row: Record<string, unknown>, index: Map<string, string>) {
  for (const a of STRENGTH_SCORE_ALIASES) {
    const orig = index.get(a);
    if (orig !== undefined) {
      const value = row[orig];
      if (isNonEmptyPrimitiveValue(value)) {
        return {
          value,
          score_source: orig,
          score_semantics: 'strength' as const,
        };
      }
    }
  }
  for (const a of RANK_SCORE_ALIASES) {
    const orig = index.get(a);
    if (orig !== undefined) {
      const value = row[orig];
      if (isNonEmptyPrimitiveValue(value)) {
        return {
          value,
          score_source: orig,
          score_semantics: 'rank' as const,
        };
      }
    }
  }
  return undefined;
}

function coerceScore(value: unknown): number {
  if (value == null || value === '') return NaN;
  const n = Number(value);
  return Number.isFinite(n) ? n : NaN;
}

/**
 * Parse p-values that may be numeric or strings like "<0.001", "NS", "n.s.".
 * "<0.001" → numeric 0.001 for filtering/sorting per product spec.
 */
export function parsePValue(value: unknown): { display: string; numeric: number | null } {
  if (value == null) return { display: '—', numeric: null };

  if (typeof value === 'number' && Number.isFinite(value)) {
    return { display: formatPValueDisplay(value), numeric: value };
  }

  const s =
    typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
      ? String(value).trim()
      : '';
  if (!s) return { display: '—', numeric: null };

  const lower = s.toLowerCase();
  if (lower === 'nan' || lower === 'na' || lower === 'n/a') {
    return { display: s, numeric: null };
  }

  const lt = s.match(/^<\s*([\d.eE+-]+)/);
  if (lt) {
    const bound = Number(lt[1]);
    if (Number.isFinite(bound)) {
      return { display: s, numeric: bound };
    }
    return { display: s, numeric: null };
  }

  const gt = s.match(/^>\s*([\d.eE+-]+)/);
  if (gt) {
    const bound = Number(gt[1]);
    if (Number.isFinite(bound)) {
      return { display: s, numeric: bound };
    }
    return { display: s, numeric: null };
  }

  const n = Number(s.replace(/,/g, ''));
  if (Number.isFinite(n)) {
    return { display: s, numeric: n };
  }

  return { display: s, numeric: null };
}

function formatPValueDisplay(n: number): string {
  if (n < 0.001) return '<0.001';
  return n.toFixed(4).replace(/\.?0+$/, '') || '0';
}

/**
 * Single-table semantics: all rows should agree; mixed or empty → `unknown`.
 */
export function getDatasetScoreSemantics(rows: NormalizedLRRow[]): ScoreSemantics {
  if (rows.length === 0) return 'unknown';
  const first = rows[0].score_semantics;
  for (let i = 1; i < rows.length; i++) {
    if (rows[i].score_semantics !== first) return 'unknown';
  }
  return first;
}

/**
 * Normalize artifact preview rows to canonical ligand–receptor records.
 * Drops rows missing sender, receiver, ligand, receptor, or a finite score.
 */
export function normalizeLigandReceptorRows(rows: Record<string, unknown>[]): NormalizedLRRow[] {
  const out: NormalizedLRRow[] = [];

  for (const raw of rows) {
    const index = buildKeyIndex(raw);

    const senderV = pickField(raw, index, SENDER_ALIASES);
    const receiverV = pickField(raw, index, RECEIVER_ALIASES);
    const ligandV = pickField(raw, index, LIGAND_ALIASES);
    const receptorV = pickField(raw, index, RECEPTOR_ALIASES);
    const scoreMeta = pickScoreWithMeta(raw, index);
    const pV = pickField(raw, index, P_ALIASES);

    const sender = senderV != null ? String(senderV).trim() : '';
    const receiver = receiverV != null ? String(receiverV).trim() : '';
    const ligand = ligandV != null ? String(ligandV).trim() : '';
    const receptor = receptorV != null ? String(receptorV).trim() : '';
    const score = scoreMeta != null ? coerceScore(scoreMeta.value) : NaN;

    if (!sender || !receiver || !ligand || !receptor || !Number.isFinite(score)) {
      continue;
    }

    const { display: pDisplay, numeric: pNum } = parsePValue(pV ?? null);
    const interaction_name = `${ligand}–${receptor}`;

    out.push({
      sender,
      receiver,
      ligand,
      receptor,
      score,
      score_source: scoreMeta!.score_source,
      score_semantics: scoreMeta!.score_semantics,
      p_value: pDisplay,
      p_value_numeric: pNum,
      interaction_name,
      raw,
    });
  }

  return out;
}
