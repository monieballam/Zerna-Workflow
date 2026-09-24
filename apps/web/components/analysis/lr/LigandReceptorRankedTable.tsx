'use client';

import { useEffect, useMemo, useState } from 'react';
import type { NormalizedLRRow, ScoreSemantics } from '@/lib/ligand-receptor';

type SortKey =
  | 'sender'
  | 'receiver'
  | 'ligand'
  | 'receptor'
  | 'interaction_name'
  | 'score'
  | 'p_value';

export interface LigandReceptorRankedTableProps {
  rows: NormalizedLRRow[];
  datasetSemantics: ScoreSemantics;
  selectedPair: { sender: string; receiver: string } | null;
  onSelectPair: (pair: { sender: string; receiver: string }) => void;
  onExportCsv?: () => void;
}

function scoreColumnLabel(sem: ScoreSemantics): string {
  if (sem === 'rank') return 'Rank';
  if (sem === 'strength') return 'Score';
  return 'Value';
}

export default function LigandReceptorRankedTable({
  rows,
  datasetSemantics,
  selectedPair,
  onSelectPair,
  onExportCsv,
}: LigandReceptorRankedTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('score');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>(() =>
    datasetSemantics === 'rank' ? 'asc' : 'desc'
  );

  useEffect(() => {
    if (sortKey === 'score') {
      setSortDir(datasetSemantics === 'rank' ? 'asc' : 'desc');
    }
  }, [datasetSemantics, sortKey]);

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      let cmp: number;
      if (sortKey === 'p_value') {
        const ap = a.p_value_numeric;
        const bp = b.p_value_numeric;
        if (ap == null && bp == null) cmp = a.p_value.localeCompare(b.p_value);
        else if (ap == null) cmp = 1;
        else if (bp == null) cmp = -1;
        else cmp = ap - bp;
      } else if (sortKey === 'score') {
        cmp = a.score - b.score;
      } else {
        cmp = String(a[sortKey]).localeCompare(String(b[sortKey]));
      }
      if (cmp === 0 && sortKey !== 'p_value') {
        const ap = a.p_value_numeric;
        const bp = b.p_value_numeric;
        if (ap != null && bp != null) cmp = ap - bp;
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return copy;
  }, [rows, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      if (key === 'score') {
        setSortDir(datasetSemantics === 'rank' ? 'asc' : 'desc');
      } else {
        setSortDir(key === 'p_value' ? 'asc' : 'asc');
      }
    }
  }

  const isSelected = (r: NormalizedLRRow) =>
    selectedPair != null &&
    r.sender === selectedPair.sender &&
    r.receiver === selectedPair.receiver;

  return (
    <div className="card p-4" data-testid="lr-ranked-table-wrap">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-gray-800">Ranked interactions</h3>
        {onExportCsv ? (
          <button
            type="button"
            onClick={onExportCsv}
            className="rounded-md border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50"
            data-testid="lr-export-filtered-csv"
          >
            Export filtered CSV
          </button>
        ) : null}
      </div>
      {rows.length === 0 ? (
        <p className="text-sm text-gray-500">No interactions match the current filters.</p>
      ) : (
        <div className="max-h-[28rem] overflow-auto overflow-x-auto">
          <table className="w-full min-w-[44rem] text-left text-sm" data-testid="lr-ranked-table">
            <thead className="sticky top-0 z-10 bg-white shadow-sm">
              <tr className="border-b border-gray-100 text-xs text-gray-500">
                {(
                  [
                    ['sender', 'Sender'],
                    ['receiver', 'Receiver'],
                    ['ligand', 'Ligand'],
                    ['receptor', 'Receptor'],
                    ['interaction_name', 'Interaction'],
                    ['score', scoreColumnLabel(datasetSemantics)],
                    ['p_value', 'p-value'],
                  ] as [SortKey, string][]
                ).map(([key, label]) => (
                  <th
                    key={key}
                    className="cursor-pointer select-none pb-2 pr-3 font-medium hover:text-gray-700"
                    onClick={() => toggleSort(key)}
                  >
                    {label}
                    {sortKey === key && (
                      <span className="ml-1 text-blue-600">{sortDir === 'asc' ? '↑' : '↓'}</span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {sorted.map((r, i) => (
                <tr
                  key={`${r.sender}|${r.receiver}|${r.ligand}|${r.receptor}|${i}`}
                  onClick={() => onSelectPair({ sender: r.sender, receiver: r.receiver })}
                  className={`cursor-pointer hover:bg-violet-50/60 ${isSelected(r) ? 'bg-violet-100/80' : ''}`}
                  data-testid={`lr-ranked-row-${i}`}
                >
                  <td
                    className="max-w-[12rem] break-words py-1.5 pr-2 text-gray-800"
                    title={r.sender}
                  >
                    {r.sender}
                  </td>
                  <td
                    className="max-w-[12rem] break-words py-1.5 pr-2 text-gray-800"
                    title={r.receiver}
                  >
                    {r.receiver}
                  </td>
                  <td className="py-1.5 pr-2 font-mono text-gray-900">{r.ligand}</td>
                  <td className="py-1.5 pr-2 font-mono text-gray-900">{r.receptor}</td>
                  <td
                    className="max-w-[14rem] break-words py-1.5 pr-2 text-gray-700"
                    title={r.interaction_name}
                  >
                    {r.interaction_name}
                  </td>
                  <td className="py-1.5 pr-2 font-mono tabular-nums text-blue-700">
                    {r.score.toFixed(3)}
                  </td>
                  <td className="py-1.5 text-gray-600">{r.p_value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
