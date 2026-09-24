'use client';

import { useEffect, useState } from 'react';

export default function ClusterAliasEditor({
  clusterId,
  pipelineSavedLabel,
  alias,
  onSave,
  technicalIdKind = 'cluster',
}: {
  clusterId: string;
  /** Server / export label (same as cluster summary ``label``). */
  pipelineSavedLabel: string;
  alias: string;
  onSave: (clusterId: string, nextAlias: string) => void;
  technicalIdKind?: 'cluster' | 'lineage_partition' | 'fine_partition';
}) {
  const technicalNoun =
    technicalIdKind === 'lineage_partition'
      ? 'lineage partition'
      : technicalIdKind === 'fine_partition'
        ? 'fine partition'
        : 'cluster';
  const [draft, setDraft] = useState(alias);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setDraft(alias);
    setDirty(false);
  }, [alias, clusterId]);

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
        Technical display alias (rename)
      </p>
      <p className="mt-1 text-[11px] text-gray-500">
        Technical {technicalNoun} ID <span className="font-mono text-gray-700">{clusterId}</span>{' '}
        and the pipeline / saved label stay fixed for exports; this alias is stored in this browser
        only and never replaces structural biology (lineage / major / fine) in the headline above.
        The same alias is reused across Global, lineage, and fine embeddings when cells share a
        linked global cluster id.
      </p>
      <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
        <input
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            setDirty(true);
          }}
          placeholder={`e.g. curate “${pipelineSavedLabel}”`}
          className="min-w-0 flex-1 rounded-md border border-gray-300 px-2 py-1.5 text-sm text-gray-800"
          aria-label="Technical display alias"
        />
        <button
          type="button"
          disabled={!dirty}
          onClick={() => {
            onSave(clusterId, draft.trim());
            setDirty(false);
          }}
          className="rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-sm font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Save alias
        </button>
        {alias ? (
          <button
            type="button"
            onClick={() => {
              setDraft('');
              onSave(clusterId, '');
            }}
            className="text-sm text-gray-500 hover:text-gray-800"
          >
            Clear
          </button>
        ) : null}
      </div>
    </div>
  );
}
