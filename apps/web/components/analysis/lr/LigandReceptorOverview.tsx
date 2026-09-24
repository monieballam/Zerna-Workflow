'use client';

import { useMemo, useState, type ReactNode } from 'react';
import type { NormalizedLRRow, ScoreSemantics } from '@/lib/ligand-receptor';
import {
  aggregateBySenderReceiver,
  allowedLrPairMetrics,
  orderedSendersReceivers,
  pairKey,
  type AxisSortMode,
  type LrPairMetric,
  type SenderReceiverAggregate,
} from '@/lib/ligand-receptor';

const METRIC_LABELS_STRENGTH: Record<LrPairMetric, string> = {
  count: 'Interaction count',
  mean: 'Mean score',
  max: 'Max score',
  sum: 'Summed score',
};

function metricLabel(metric: LrPairMetric, sem: ScoreSemantics): string {
  if (sem === 'strength') return METRIC_LABELS_STRENGTH[metric];
  return 'Interaction count (rows per pair)';
}

function tooltipTopInteractionsTitle(sem: ScoreSemantics): string {
  if (sem === 'strength') return 'Top interactions by score (loaded preview rows)';
  if (sem === 'rank') return 'Top-ranked interactions in loaded data (lower rank is better)';
  return 'Top interaction values in loaded data';
}

function axisOrderOptionLabel(sem: ScoreSemantics): string {
  if (sem === 'strength') return 'By total communication (selected metric)';
  return 'By total interaction count';
}

function overviewFooterCopy(sem: ScoreSemantics): string {
  if (sem === 'strength') {
    return 'Edges and heatmap cells summarize all ligand–receptor rows for each sender–receiver pair using the selected metric. Click a cell or edge to inspect individual interactions below.';
  }
  if (sem === 'rank') {
    return 'Heatmap and network use interaction counts per sender–receiver pair only (rank values are not summed or averaged). Click a cell or edge to inspect ranks in the tables below.';
  }
  return 'Heatmap and network use interaction counts per pair; score-like aggregations are disabled when score meaning is ambiguous. Click a cell or edge for row-level detail.';
}

export interface LigandReceptorOverviewProps {
  rows: NormalizedLRRow[];
  datasetSemantics: ScoreSemantics;
  metric: LrPairMetric;
  onMetricChange: (m: LrPairMetric) => void;
  axisSort: AxisSortMode;
  onAxisSortChange: (s: AxisSortMode) => void;
  tab: 'heatmap' | 'network';
  onTabChange: (t: 'heatmap' | 'network') => void;
  selectedPair: { sender: string; receiver: string } | null;
  onSelectPair: (p: { sender: string; receiver: string } | null) => void;
}

interface TooltipState {
  x: number;
  y: number;
  content: ReactNode;
}

function HeatmapView({
  rows,
  metric,
  axisSort,
  selectedPair,
  onSelectPair,
  datasetSemantics,
}: {
  rows: NormalizedLRRow[];
  metric: LrPairMetric;
  axisSort: AxisSortMode;
  selectedPair: { sender: string; receiver: string } | null;
  onSelectPair: (p: { sender: string; receiver: string } | null) => void;
  datasetSemantics: ScoreSemantics;
}) {
  const [tip, setTip] = useState<TooltipState | null>(null);

  const agg = useMemo(
    () => aggregateBySenderReceiver(rows, metric, datasetSemantics),
    [rows, metric, datasetSemantics]
  );
  const { senders, receivers } = useMemo(
    () => orderedSendersReceivers(agg, axisSort),
    [agg, axisSort]
  );

  const matrix = useMemo(() => {
    const m = new Map<string, SenderReceiverAggregate>();
    for (const a of agg.values()) {
      m.set(pairKey(a.sender, a.receiver), a);
    }
    return m;
  }, [agg]);

  const maxVal = useMemo(() => {
    let v = 0;
    for (const a of agg.values()) {
      if (a.value > v) v = a.value;
    }
    return v || 1;
  }, [agg]);

  function cellColor(val: number): string {
    if (val <= 0) return 'rgb(249 250 251)';
    const t = val / maxVal;
    const r = Math.round(250 - t * 126);
    const g = Math.round(250 - t * 192);
    const b = Math.round(255 - t * 18);
    return `rgb(${r} ${g} ${b})`;
  }

  const ml = metricLabel(metric, datasetSemantics);
  const topTitle = tooltipTopInteractionsTitle(datasetSemantics);

  if (senders.length === 0 || receivers.length === 0) {
    return (
      <div
        className="flex min-h-[12rem] items-center justify-center rounded-lg border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500"
        data-testid="lr-heatmap-empty"
      >
        No sender–receiver pairs to display for the current filters.
      </div>
    );
  }

  return (
    <div className="relative" data-testid="lr-heatmap">
      <div className="max-h-[min(70vh,36rem)] overflow-auto">
        <table className="border-collapse text-xs">
          <thead>
            <tr>
              <th className="sticky left-0 z-20 min-w-[7rem] bg-white p-1 text-left text-[10px] font-medium text-gray-500 shadow-[2px_0_4px_rgba(0,0,0,0.04)]">
                Sender \ Receiver
              </th>
              {receivers.map((rcv) => (
                <th key={rcv} className="max-w-[6rem] p-1 align-bottom" title={rcv}>
                  <div
                    className="line-clamp-3 whitespace-normal break-words text-[10px] font-medium leading-tight text-gray-700"
                    title={rcv}
                  >
                    {rcv}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {senders.map((snd) => (
              <tr key={snd}>
                <th
                  className="sticky left-0 z-10 max-w-[10rem] bg-white p-1 text-left align-top shadow-[2px_0_4px_rgba(0,0,0,0.04)]"
                  title={snd}
                >
                  <div className="line-clamp-4 break-words font-medium text-gray-800" title={snd}>
                    {snd}
                  </div>
                </th>
                {receivers.map((rcv) => {
                  const cell = matrix.get(pairKey(snd, rcv));
                  const val = cell?.value ?? 0;
                  const isSel = selectedPair?.sender === snd && selectedPair?.receiver === rcv;
                  return (
                    <td key={rcv} className="p-0.5">
                      <button
                        type="button"
                        className={`h-8 w-full min-w-[2rem] rounded border transition ${
                          isSel ? 'ring-2 ring-violet-600 ring-offset-1' : 'border-transparent'
                        }`}
                        style={{ backgroundColor: cellColor(val) }}
                        onClick={() => {
                          if (cell && val > 0) {
                            onSelectPair({ sender: snd, receiver: rcv });
                          }
                        }}
                        onMouseEnter={(e) => {
                          if (!cell || val <= 0) {
                            setTip(null);
                            return;
                          }
                          const rect = e.currentTarget.getBoundingClientRect();
                          setTip({
                            x: rect.left + rect.width / 2,
                            y: rect.top,
                            content: (
                              <div className="max-w-sm text-xs">
                                <p className="font-semibold text-gray-900" title={snd}>
                                  {snd}
                                </p>
                                <p className="font-semibold text-gray-900" title={rcv}>
                                  → {rcv}
                                </p>
                                <p className="mt-1 text-gray-600">
                                  {ml}:{' '}
                                  <span className="font-mono font-medium text-gray-900">
                                    {metric === 'mean' || metric === 'max'
                                      ? val.toFixed(4)
                                      : val.toLocaleString()}
                                  </span>
                                </p>
                                <p className="mt-2 font-medium text-gray-700">{topTitle}</p>
                                <ul className="mt-1 list-inside list-disc text-gray-600">
                                  {cell.topInteractionNames.length === 0 ? (
                                    <li>—</li>
                                  ) : (
                                    cell.topInteractionNames.map((n) => (
                                      <li key={n} className="break-words" title={n}>
                                        {n}
                                      </li>
                                    ))
                                  )}
                                </ul>
                              </div>
                            ),
                          });
                        }}
                        onMouseLeave={() => setTip(null)}
                        aria-label={`${snd} to ${rcv}, ${ml} ${val}`}
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {tip ? (
        <div
          className="pointer-events-none fixed z-50 -translate-x-1/2 -translate-y-full rounded-lg border border-gray-200 bg-white px-3 py-2 shadow-lg"
          style={{ left: tip.x, top: tip.y - 8 }}
          role="tooltip"
        >
          {tip.content}
        </div>
      ) : null}
    </div>
  );
}

function AggregatedNetworkView({
  agg,
  selectedPair,
  onSelectPair,
  metric,
  datasetSemantics,
}: {
  agg: Map<string, SenderReceiverAggregate>;
  selectedPair: { sender: string; receiver: string } | null;
  onSelectPair: (p: { sender: string; receiver: string } | null) => void;
  metric: LrPairMetric;
  datasetSemantics: ScoreSemantics;
}) {
  const [tip, setTip] = useState<TooltipState | null>(null);

  const { clusters, maxEdge } = useMemo(() => {
    const c = new Set<string>();
    let max = 0;
    for (const a of agg.values()) {
      c.add(a.sender);
      c.add(a.receiver);
      if (a.value > max) max = a.value;
    }
    return { clusters: [...c], maxEdge: max || 1 };
  }, [agg]);

  const W = 520;
  const H = 360;
  const cx = W / 2;
  const cy = H / 2;
  const radius = Math.min(W, H) * 0.36;

  const nodePos = useMemo(() => {
    const m = new Map<string, { x: number; y: number }>();
    clusters.forEach((c, i) => {
      const angle = (2 * Math.PI * i) / Math.max(clusters.length, 1) - Math.PI / 2;
      m.set(c, {
        x: cx + radius * Math.cos(angle),
        y: cy + radius * Math.sin(angle),
      });
    });
    return m;
  }, [clusters, cx, cy, radius]);

  const ml = metricLabel(metric, datasetSemantics);
  const topTitle = tooltipTopInteractionsTitle(datasetSemantics);

  if (clusters.length === 0) {
    return (
      <div
        className="flex h-64 items-center justify-center text-sm text-gray-500"
        data-testid="lr-network-empty"
      >
        No nodes to display.
      </div>
    );
  }

  return (
    <div className="relative w-full" data-testid="lr-network-aggregated">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-full">
        {Array.from(agg.values()).map((a) => {
          const s = nodePos.get(a.sender);
          const t = nodePos.get(a.receiver);
          if (!s || !t) return null;
          const w = 1 + (a.value / maxEdge) * 6;
          const isSel = selectedPair?.sender === a.sender && selectedPair?.receiver === a.receiver;
          const key = pairKey(a.sender, a.receiver);
          return (
            <line
              key={key}
              x1={s.x}
              y1={s.y}
              x2={t.x}
              y2={t.y}
              stroke={isSel ? '#7c3aed' : '#94a3b8'}
              strokeWidth={w}
              strokeOpacity={isSel ? 1 : 0.55}
              className="cursor-pointer"
              onClick={() =>
                onSelectPair(isSel ? null : { sender: a.sender, receiver: a.receiver })
              }
              onMouseEnter={(e) => {
                const rect = (e.target as SVGLineElement).getBoundingClientRect();
                setTip({
                  x: rect.left + rect.width / 2,
                  y: rect.top,
                  content: (
                    <div className="max-w-sm text-xs">
                      <p className="font-semibold text-gray-900" title={a.sender}>
                        {a.sender}
                      </p>
                      <p className="font-semibold text-gray-900" title={a.receiver}>
                        → {a.receiver}
                      </p>
                      <p className="mt-1 text-gray-600">
                        {ml}:{' '}
                        <span className="font-mono font-medium">
                          {metric === 'mean' || metric === 'max'
                            ? a.value.toFixed(4)
                            : a.value.toLocaleString()}
                        </span>
                      </p>
                      <p className="mt-2 font-medium text-gray-700">{topTitle}</p>
                      <ul className="mt-1 list-inside list-disc text-gray-600">
                        {a.topInteractionNames.map((n) => (
                          <li key={n} className="break-words" title={n}>
                            {n}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ),
                });
              }}
              onMouseLeave={() => setTip(null)}
            >
              <title>{`${a.sender} → ${a.receiver}`}</title>
            </line>
          );
        })}
        {clusters.map((c, i) => {
          const pos = nodePos.get(c)!;
          const hue = (i * 47) % 360;
          const short = c.length > 14 ? `${c.slice(0, 12)}…` : c;
          return (
            <g key={c}>
              <circle
                cx={pos.x}
                cy={pos.y}
                r={22}
                fill={`hsl(${hue} 65% 52%)`}
                fillOpacity={0.9}
                stroke="white"
                strokeWidth={2}
              />
              <text
                x={pos.x}
                y={pos.y + 3}
                textAnchor="middle"
                fontSize={9}
                fill="white"
                fontWeight={600}
              >
                {short}
              </text>
              <title>{c}</title>
            </g>
          );
        })}
      </svg>
      {tip ? (
        <div
          className="pointer-events-none fixed z-50 -translate-x-1/2 -translate-y-full rounded-lg border border-gray-200 bg-white px-3 py-2 shadow-lg"
          style={{ left: tip.x, top: tip.y - 8 }}
        >
          {tip.content}
        </div>
      ) : null}
    </div>
  );
}

export default function LigandReceptorOverview({
  rows,
  datasetSemantics,
  metric,
  onMetricChange,
  axisSort,
  onAxisSortChange,
  tab,
  onTabChange,
  selectedPair,
  onSelectPair,
}: LigandReceptorOverviewProps) {
  const agg = useMemo(
    () => aggregateBySenderReceiver(rows, metric, datasetSemantics),
    [rows, metric, datasetSemantics]
  );

  const metricOptions = allowedLrPairMetrics(datasetSemantics);

  return (
    <div className="card p-4" data-testid="lr-overview">
      <div className="flex flex-wrap items-center gap-3 border-b border-gray-100 pb-3">
        <div className="flex rounded-lg border border-gray-200 p-0.5 text-xs font-medium">
          <button
            type="button"
            className={`rounded-md px-3 py-1.5 ${tab === 'heatmap' ? 'bg-violet-600 text-white' : 'text-gray-600'}`}
            onClick={() => onTabChange('heatmap')}
            data-testid="lr-tab-heatmap"
          >
            Heatmap
          </button>
          <button
            type="button"
            className={`rounded-md px-3 py-1.5 ${tab === 'network' ? 'bg-violet-600 text-white' : 'text-gray-600'}`}
            onClick={() => onTabChange('network')}
            data-testid="lr-tab-network"
          >
            Network
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="lr-metric" className="text-xs text-gray-500">
            {datasetSemantics === 'strength' ? 'Edge / cell metric' : 'Pair metric'}
          </label>
          <select
            id="lr-metric"
            value={metric}
            onChange={(e) => onMetricChange(e.target.value as LrPairMetric)}
            className="rounded-md border border-gray-300 bg-white px-2 py-1 text-xs text-gray-800"
            data-testid="lr-metric-select"
          >
            {metricOptions.map((k) => (
              <option key={k} value={k}>
                {metricLabel(k, datasetSemantics)}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-gray-500">Axis order</span>
          <select
            value={axisSort}
            onChange={(e) => onAxisSortChange(e.target.value as AxisSortMode)}
            className="rounded-md border border-gray-300 bg-white px-2 py-1 text-xs text-gray-800"
            data-testid="lr-axis-sort"
          >
            <option value="strength">{axisOrderOptionLabel(datasetSemantics)}</option>
            <option value="alpha">Alphabetical</option>
          </select>
        </div>
      </div>

      <div className="mt-4">
        {tab === 'heatmap' ? (
          <HeatmapView
            rows={rows}
            metric={metric}
            axisSort={axisSort}
            selectedPair={selectedPair}
            onSelectPair={onSelectPair}
            datasetSemantics={datasetSemantics}
          />
        ) : (
          <AggregatedNetworkView
            agg={agg}
            selectedPair={selectedPair}
            onSelectPair={onSelectPair}
            metric={metric}
            datasetSemantics={datasetSemantics}
          />
        )}
      </div>
      <p className="mt-3 text-xs text-gray-500">{overviewFooterCopy(datasetSemantics)}</p>
    </div>
  );
}
