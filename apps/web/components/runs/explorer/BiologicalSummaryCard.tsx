'use client';

import type { BiologicalHighlights, PopulationCount } from '@/lib/run-composition';

function Row({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
        {label}
      </span>
      <span className="text-sm font-medium text-gray-900">{value ?? '—'}</span>
    </div>
  );
}

export default function BiologicalSummaryCard({
  highlights,
  nSamples,
  nConditions,
  topPopulations,
}: {
  highlights: BiologicalHighlights;
  nSamples: number | null;
  nConditions: number | null;
  topPopulations: PopulationCount[];
}) {
  return (
    <div className="card flex h-full flex-col p-4">
      <h3 className="text-sm font-semibold text-gray-800">Quick Biological Summary</h3>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Row label="Dominant cell type" value={highlights.dominantCellType} />
        <Row label="Dominant stromal subtype" value={highlights.dominantStromalSubtype} />
        <Row label="Dominant immune subtype" value={highlights.dominantImmuneSubtype} />
        <Row label="Samples" value={nSamples != null ? String(nSamples) : null} />
        <Row label="Conditions" value={nConditions != null ? String(nConditions) : null} />
      </div>
      <div className="mt-5 border-t border-gray-100 pt-4">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
          Top populations
        </p>
        {topPopulations.length === 0 ? (
          <p className="mt-2 text-xs text-gray-400">No population breakdown for this view.</p>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {topPopulations.map((p) => (
              <li key={p.label} className="flex items-baseline justify-between gap-2 text-xs">
                <span className="min-w-0 truncate text-gray-700" title={p.label}>
                  {p.label}
                </span>
                <span className="shrink-0 tabular-nums text-gray-500">
                  {p.count.toLocaleString()} ({p.pct.toFixed(1)}%)
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
