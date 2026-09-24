import type { NormalizedLRRow, ScoreSemantics } from './normalize';

export type LrPairMetric = 'count' | 'mean' | 'max' | 'sum';

/** Pair-level metrics allowed for heatmap/network given dataset score semantics. */
export function allowedLrPairMetrics(semantics: ScoreSemantics): LrPairMetric[] {
  if (semantics === 'strength') return ['count', 'mean', 'max', 'sum'];
  return ['count'];
}

export interface SenderReceiverAggregate {
  sender: string;
  receiver: string;
  metric: LrPairMetric;
  value: number;
  /** Top interaction names within this pair (ordering depends on score semantics). */
  topInteractionNames: string[];
}

const PAIR_SEP = '\u0001';

export function pairKey(sender: string, receiver: string): string {
  return `${sender}${PAIR_SEP}${receiver}`;
}

export function parsePairKey(key: string): { sender: string; receiver: string } | null {
  const i = key.indexOf(PAIR_SEP);
  if (i < 0) return null;
  return { sender: key.slice(0, i), receiver: key.slice(i + 1) };
}

interface PairAccum {
  count: number;
  sum: number;
  max: number;
  min: number;
  /** interaction_name -> extremal score for that name in this pair (max for strength, min rank for rank). */
  bestByName: Map<string, number>;
}

function emptyAccum(): PairAccum {
  return { count: 0, sum: 0, max: -Infinity, min: Infinity, bestByName: new Map() };
}

function accumPair(acc: PairAccum, row: NormalizedLRRow, datasetSemantics: ScoreSemantics) {
  acc.count += 1;
  acc.sum += row.score;
  acc.max = Math.max(acc.max, row.score);
  acc.min = Math.min(acc.min, row.score);
  const prev = acc.bestByName.get(row.interaction_name);
  if (datasetSemantics === 'rank') {
    if (prev === undefined || row.score < prev) {
      acc.bestByName.set(row.interaction_name, row.score);
    }
  } else {
    if (prev === undefined || row.score > prev) {
      acc.bestByName.set(row.interaction_name, row.score);
    }
  }
}

function metricValue(acc: PairAccum, metric: LrPairMetric): number {
  if (acc.count === 0) return 0;
  switch (metric) {
    case 'count':
      return acc.count;
    case 'sum':
      return acc.sum;
    case 'max':
      return acc.max === -Infinity ? 0 : acc.max;
    case 'mean':
    default:
      return acc.sum / acc.count;
  }
}

function topNamesFromAccum(
  acc: PairAccum,
  limit: number,
  datasetSemantics: ScoreSemantics
): string[] {
  const entries = [...acc.bestByName.entries()];
  if (datasetSemantics === 'rank') {
    entries.sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0]));
  } else {
    entries.sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }
  return entries.slice(0, limit).map(([name]) => name);
}

/**
 * Aggregate rows by sender–receiver for heatmap / network edge weights.
 */
export function aggregateBySenderReceiver(
  rows: NormalizedLRRow[],
  metric: LrPairMetric,
  datasetSemantics: ScoreSemantics
): Map<string, SenderReceiverAggregate> {
  const safeMetric = datasetSemantics !== 'strength' && metric !== 'count' ? 'count' : metric;

  const map = new Map<string, PairAccum>();

  for (const row of rows) {
    const key = pairKey(row.sender, row.receiver);
    let acc = map.get(key);
    if (!acc) {
      acc = emptyAccum();
      map.set(key, acc);
    }
    accumPair(acc, row, datasetSemantics);
  }

  const out = new Map<string, SenderReceiverAggregate>();
  for (const [key, acc] of map) {
    const { sender, receiver } = parsePairKey(key)!;
    out.set(key, {
      sender,
      receiver,
      metric: safeMetric,
      value: metricValue(acc, safeMetric),
      topInteractionNames: topNamesFromAccum(acc, 5, datasetSemantics),
    });
  }
  return out;
}

export type AxisSortMode = 'strength' | 'alpha';

export function orderedSendersReceivers(
  agg: Map<string, SenderReceiverAggregate>,
  sort: AxisSortMode
): { senders: string[]; receivers: string[] } {
  const sendersSet = new Set<string>();
  const receiversSet = new Set<string>();
  for (const a of agg.values()) {
    sendersSet.add(a.sender);
    receiversSet.add(a.receiver);
  }

  const senders = [...sendersSet];
  const receivers = [...receiversSet];

  if (sort === 'alpha') {
    senders.sort((a, b) => a.localeCompare(b));
    receivers.sort((a, b) => a.localeCompare(b));
    return { senders, receivers };
  }

  const rowStrength = new Map<string, number>();
  const colStrength = new Map<string, number>();
  for (const a of agg.values()) {
    rowStrength.set(a.sender, (rowStrength.get(a.sender) ?? 0) + a.value);
    colStrength.set(a.receiver, (colStrength.get(a.receiver) ?? 0) + a.value);
  }

  senders.sort((a, b) => {
    const da = rowStrength.get(a) ?? 0;
    const db = rowStrength.get(b) ?? 0;
    if (db !== da) return db - da;
    return a.localeCompare(b);
  });
  receivers.sort((a, b) => {
    const da = colStrength.get(a) ?? 0;
    const db = colStrength.get(b) ?? 0;
    if (db !== da) return db - da;
    return a.localeCompare(b);
  });

  return { senders, receivers };
}

/** Rows for a single sender–receiver pair, sorted by score (rank: ascending = best first). */
export function rowsForPair(
  rows: NormalizedLRRow[],
  sender: string,
  receiver: string,
  datasetSemantics: ScoreSemantics
): NormalizedLRRow[] {
  return rows
    .filter((r) => r.sender === sender && r.receiver === receiver)
    .sort((a, b) => {
      if (datasetSemantics === 'rank') {
        if (a.score !== b.score) return a.score - b.score;
      } else {
        if (b.score !== a.score) return b.score - a.score;
      }
      const ap = a.p_value_numeric;
      const bp = b.p_value_numeric;
      if (ap == null && bp == null) return 0;
      if (ap == null) return 1;
      if (bp == null) return -1;
      return ap - bp;
    });
}

export function topInteractionNamesForPair(
  rows: NormalizedLRRow[],
  sender: string,
  receiver: string,
  limit: number,
  datasetSemantics: ScoreSemantics
): string[] {
  const acc = emptyAccum();
  for (const row of rows) {
    if (row.sender === sender && row.receiver === receiver) {
      accumPair(acc, row, datasetSemantics);
    }
  }
  return topNamesFromAccum(acc, limit, datasetSemantics);
}
