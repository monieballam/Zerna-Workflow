'use client';

import type { RunnerUpLabel } from './cluster-inspector-types';

export default function ContradictionEvidencePanel({
  runnerUps,
  conservativeReason,
  conservativeStatus,
  pipelineSavedLabel,
}: {
  runnerUps: RunnerUpLabel[];
  conservativeReason: string | null;
  conservativeStatus: string | null;
  /** Same as cluster ``label`` in the inspector (pipeline / saved annotation). */
  pipelineSavedLabel: string;
}) {
  const hasRunnerUps = runnerUps.length > 0;
  const hasConservative = Boolean(conservativeReason || conservativeStatus);

  if (!hasRunnerUps && !hasConservative) {
    return (
      <p className="text-[11px] text-gray-400">No stored contradiction or runner-up evidence.</p>
    );
  }

  return (
    <div className="space-y-2">
      {hasConservative ? (
        <div className="rounded border border-amber-100 bg-amber-50/60 px-2 py-1.5 text-[11px] text-amber-950">
          {conservativeStatus ? (
            <p>
              <span className="font-semibold">Status:</span> {conservativeStatus}
            </p>
          ) : null}
          {conservativeReason ? (
            <p className={conservativeStatus ? 'mt-0.5' : ''}>
              <span className="font-semibold">Reason:</span> {conservativeReason}
            </p>
          ) : null}
        </div>
      ) : null}
      {hasRunnerUps ? (
        <ul className="space-y-1.5">
          {runnerUps.map((r) => (
            <li
              key={r.cell_type}
              className="rounded border border-gray-100 bg-gray-50/80 px-2 py-1 text-[11px] text-gray-700"
            >
              <span className="font-medium text-gray-900">{r.cell_type}</span> scored lower than the
              pipeline / saved label{' '}
              <span className="font-medium text-gray-900">{pipelineSavedLabel}</span>
              {r.n_markers > 0 ? (
                <>
                  {' '}
                  (score {r.score.toFixed(3)}, {r.n_markers} marker overlap signal)
                </>
              ) : (
                <> (score {r.score.toFixed(3)})</>
              )}
              .
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
