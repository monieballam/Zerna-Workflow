'use client';

import { useState } from 'react';
import type { Artifact } from '@zerna/sdk';
import RunArtifactList from './RunArtifactList';
import RunExplorer from './RunExplorer';
import RunResults from './RunResults';
import UMAPViewer from './UMAPViewer';

type ExplorerTab = 'explorer' | 'results' | 'artifacts';

const TABS: Array<{ id: ExplorerTab; label: string; description: string }> = [
  {
    id: 'explorer',
    label: 'Explorer',
    description:
      'Cell composition and biological context first, then filters, interactive embedding, and cluster inspection.',
  },
  {
    id: 'results',
    label: 'Results',
    description: 'Saved QC, preprocessing, batch correction, annotation, and downstream summaries.',
  },
  {
    id: 'artifacts',
    label: 'Artifacts',
    description: 'Download or open the persisted outputs from this run.',
  },
];

export default function RunExplorerWorkspace({
  runId,
  artifacts,
}: {
  runId: string;
  artifacts: Artifact[];
}) {
  const [activeTab, setActiveTab] = useState<ExplorerTab>('explorer');
  const selectedTab = TABS.find((tab) => tab.id === activeTab) ?? TABS[0];

  return (
    <div className="space-y-6">
      <div className="card p-4">
        <div className="flex flex-wrap gap-2">
          {TABS.map((tab) => {
            const isActive = tab.id === activeTab;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-blue-600 text-white'
                    : 'border border-gray-200 bg-white text-gray-700 hover:bg-gray-50'
                }`}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
        <p className="mt-3 text-sm text-gray-500">{selectedTab.description}</p>
      </div>

      {activeTab === 'explorer' && <RunExplorer key={runId} runId={runId} />}

      {activeTab === 'results' && (
        <div className="space-y-4">
          <p className="text-sm text-gray-600">
            Review technical run outputs and saved analysis summaries.
          </p>
          <RunResults runId={runId} mode="details" artifacts={artifacts} />
          <UMAPViewer runId={runId} />
        </div>
      )}

      {activeTab === 'artifacts' && (
        <RunArtifactList
          runId={runId}
          artifacts={artifacts}
          emptyMessage="No saved artifacts yet. When this run finishes, you can open the annotated h5ad in the explorer or download reports and tables from here."
        />
      )}
    </div>
  );
}
