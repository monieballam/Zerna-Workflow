'use client';

import { useMemo } from 'react';
import type { NormalizedLRRow, ScoreSemantics } from '@/lib/ligand-receptor';
import { rowsForPair } from '@/lib/ligand-receptor';

export interface LigandReceptorDetailPanelProps {
  pair: { sender: string; receiver: string } | null;
  rows: NormalizedLRRow[];
  pinned: { sender: string; receiver: string } | null;
  datasetSemantics: ScoreSemantics;
  onClear: () => void;
  onPin: () => void;
  onUnpin: () => void;
}

function horizontalBarChart(
  items: Array<{ label: string; value: number; barFrac: number }>,
  color: string
) {
  return (
    <div className="space-y-2" data-testid="lr-detail-bars">
      {items.map((i) => (
        <div key={i.label} className="flex items-center gap-2 text-xs">
          <span
            className="w-[min(100%,12rem)] shrink-0 break-words font-medium text-gray-800"
            title={i.label}
          >
            {i.label}
          </span>
          <div className="h-2.5 min-w-0 flex-1 rounded-full bg-gray-100">
            <div
              className="h-2.5 rounded-full"
              style={{
                width: `${Math.min(100, i.barFrac * 100)}%`,
                backgroundColor: color,
              }}
            />
          </div>
          <span className="w-14 shrink-0 tabular-nums text-right text-gray-600">
            {i.value.toFixed(3)}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function LigandReceptorDetailPanel({
  pair,
  rows,
  pinned,
  datasetSemantics,
  onClear,
  onPin,
  onUnpin,
}: LigandReceptorDetailPanelProps) {
  const effective = pinned ?? pair;

  const pairRows = useMemo(() => {
    if (!effective) return [];
    return rowsForPair(rows, effective.sender, effective.receiver, datasetSemantics);
  }, [rows, effective, datasetSemantics]);

  const stats = useMemo(() => {
    if (pairRows.length === 0) {
      return {
        n: 0,
        mean: 0,
        max: 0,
        min: 0,
        topName: '—',
      };
    }
    const sum = pairRows.reduce((s, r) => s + r.score, 0);
    const max = Math.max(...pairRows.map((r) => r.score));
    const min = Math.min(...pairRows.map((r) => r.score));
    let top: NormalizedLRRow;
    if (datasetSemantics === 'rank') {
      top = [...pairRows].sort((a, b) => a.score - b.score)[0]!;
    } else {
      top = [...pairRows].sort((a, b) => b.score - a.score)[0]!;
    }
    return {
      n: pairRows.length,
      mean: sum / pairRows.length,
      max,
      min,
      topName: top.interaction_name,
    };
  }, [pairRows, datasetSemantics]);

  const top10Bars = useMemo(() => {
    const byName = new Map<string, number>();
    for (const r of pairRows) {
      const prev = byName.get(r.interaction_name);
      if (datasetSemantics === 'rank') {
        if (prev === undefined || r.score < prev) {
          byName.set(r.interaction_name, r.score);
        }
      } else {
        if (prev === undefined || r.score > prev) {
          byName.set(r.interaction_name, r.score);
        }
      }
    }
    const entries = [...byName.entries()];
    if (datasetSemantics === 'rank') {
      entries.sort((a, b) => a[1] - b[1]);
    } else {
      entries.sort((a, b) => b[1] - a[1]);
    }
    const slice = entries.slice(0, 10);
    const values = slice.map(([, v]) => v);
    const minV = values.length ? Math.min(...values) : 0;
    const maxV = values.length ? Math.max(...values) : 0;
    const span = maxV - minV;
    return slice.map(([label, value]) => {
      let barFrac = 1;
      if (span > 0) {
        barFrac = datasetSemantics === 'rank' ? (maxV - value) / span : (value - minV) / span;
      }
      return { label, value, barFrac };
    });
  }, [pairRows, datasetSemantics]);

  const chartTitle =
    datasetSemantics === 'strength'
      ? 'Top interactions (by score)'
      : datasetSemantics === 'rank'
        ? 'Top-ranked interactions in loaded data (lower rank is better)'
        : 'Top interaction values in loaded data';

  if (!effective) {
    return (
      <div
        className="card border border-dashed border-gray-200 bg-gray-50/50 p-4 text-sm text-gray-500"
        data-testid="lr-detail-empty"
      >
        Select a sender–receiver pair from the heatmap, network edge, or table to inspect
        ligand–receptor interactions.
      </div>
    );
  }

  const isPinned =
    pinned != null && pinned.sender === effective.sender && pinned.receiver === effective.receiver;

  const scoreHeader =
    datasetSemantics === 'rank' ? 'Rank' : datasetSemantics === 'strength' ? 'Score' : 'Value';

  return (
    <div
      className="card flex flex-col gap-4 border border-violet-200/80 p-4"
      data-testid="lr-detail-panel"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">Selected pair</h3>
          <p
            className="mt-1 break-words text-sm text-gray-800"
            title={`${effective.sender} → ${effective.receiver}`}
          >
            {effective.sender} → {effective.receiver}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onClear}
            className="rounded-md border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
            data-testid="lr-detail-clear"
          >
            Clear selection
          </button>
          {isPinned ? (
            <button
              type="button"
              onClick={onUnpin}
              className="rounded-md border border-violet-300 bg-violet-50 px-2.5 py-1 text-xs font-medium text-violet-800 hover:bg-violet-100"
              data-testid="lr-detail-unpin"
            >
              Unpin
            </button>
          ) : (
            <button
              type="button"
              onClick={onPin}
              className="rounded-md border border-violet-600 bg-violet-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-violet-700"
              data-testid="lr-detail-pin"
            >
              Pin pair
            </button>
          )}
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <div className="rounded-lg bg-gray-50 p-2">
          <dt className="text-gray-500">Interactions</dt>
          <dd className="font-semibold text-gray-900">{stats.n}</dd>
        </div>
        <div className="rounded-lg bg-gray-50 p-2">
          <dt className="text-gray-500">
            {datasetSemantics === 'rank'
              ? 'Mean rank'
              : datasetSemantics === 'strength'
                ? 'Mean score'
                : 'Mean value'}
          </dt>
          <dd className="font-semibold text-gray-900">{stats.n ? stats.mean.toFixed(3) : '—'}</dd>
        </div>
        <div className="rounded-lg bg-gray-50 p-2">
          <dt className="text-gray-500">
            {datasetSemantics === 'rank'
              ? 'Best rank (lowest)'
              : datasetSemantics === 'strength'
                ? 'Max score'
                : 'Max value'}
          </dt>
          <dd className="font-semibold text-gray-900">
            {stats.n
              ? datasetSemantics === 'rank'
                ? stats.min.toFixed(3)
                : stats.max.toFixed(3)
              : '—'}
          </dd>
        </div>
        <div className="rounded-lg bg-gray-50 p-2">
          <dt className="text-gray-500">Top L–R</dt>
          <dd className="break-words font-semibold text-gray-900" title={stats.topName}>
            {stats.topName}
          </dd>
        </div>
      </dl>

      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          {chartTitle}
        </h4>
        {top10Bars.length === 0 ? (
          <p className="mt-2 text-xs text-gray-400">No rows for this pair under current filters.</p>
        ) : (
          <div className="mt-2">{horizontalBarChart(top10Bars, '#7c3aed')}</div>
        )}
      </div>

      <div className="min-w-0 overflow-x-auto">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          Pair-level table
        </h4>
        <table className="mt-2 w-full min-w-[20rem] text-left text-xs">
          <thead>
            <tr className="border-b border-gray-100 text-gray-500">
              <th className="py-1.5 pr-2 font-medium">Ligand</th>
              <th className="py-1.5 pr-2 font-medium">Receptor</th>
              <th className="py-1.5 pr-2 font-medium">Interaction</th>
              <th className="py-1.5 pr-2 font-medium text-right">{scoreHeader}</th>
              <th className="py-1.5 font-medium">p-value</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {pairRows.map((r, idx) => (
              <tr key={`${r.ligand}-${r.receptor}-${idx}`}>
                <td className="py-1.5 pr-2 font-mono text-gray-800">{r.ligand}</td>
                <td className="py-1.5 pr-2 font-mono text-gray-800">{r.receptor}</td>
                <td
                  className="max-w-[14rem] break-words py-1.5 pr-2 text-gray-700"
                  title={r.interaction_name}
                >
                  {r.interaction_name}
                </td>
                <td className="py-1.5 pr-2 text-right tabular-nums text-blue-700">
                  {r.score.toFixed(3)}
                </td>
                <td className="py-1.5 text-gray-600">{r.p_value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
