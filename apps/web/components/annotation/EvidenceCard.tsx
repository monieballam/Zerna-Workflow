'use client';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface MarkerEvidence {
  gene: string;
  score: number;
  source: string;
}

export interface ClusterEvidence {
  clusterId: string;
  cellType: string;
  markerScore: number;
  referenceMappingScore: number;
  ontologyAlignmentScore: number;
  compositeScore: number;
  markers: MarkerEvidence[];
}

export interface EvidenceCardProps {
  evidence: ClusterEvidence;
}

// ── Score Bar ─────────────────────────────────────────────────────────────────

function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100);
  let barColor = 'bg-green-400';
  if (value < 0.5) barColor = 'bg-red-400';
  else if (value < 0.75) barColor = 'bg-yellow-400';

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-gray-500 w-32 truncate">{label}</span>
      <div className="flex-1 h-2.5 bg-gray-100 rounded overflow-hidden">
        <div className={`h-full ${barColor} rounded`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-600 w-10 text-right">{pct}%</span>
    </div>
  );
}

// ── Marker Evidence List ──────────────────────────────────────────────────────

function MarkerList({ markers }: { markers: MarkerEvidence[] }) {
  if (markers.length === 0) {
    return <p className="text-xs text-gray-400 italic">No marker evidence</p>;
  }

  const sorted = [...markers].sort((a, b) => b.score - a.score);

  return (
    <div className="space-y-1" data-testid="marker-evidence-list">
      {sorted.map((m) => (
        <div key={m.gene} className="flex items-center gap-2 text-xs">
          <span className="font-mono font-medium text-gray-800 w-16 truncate">{m.gene}</span>
          <div className="flex-1 h-2 bg-gray-100 rounded overflow-hidden">
            <div
              className="h-full bg-indigo-400 rounded"
              style={{ width: `${Math.round(m.score * 100)}%` }}
            />
          </div>
          <span className="text-gray-500 w-10 text-right">{(m.score * 100).toFixed(0)}%</span>
          <span className="text-gray-400 w-16 truncate text-right">{m.source}</span>
        </div>
      ))}
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function EvidenceCard({ evidence }: EvidenceCardProps) {
  const compositePct = Math.round(evidence.compositeScore * 100);
  let borderColor = 'border-green-300';
  if (evidence.compositeScore < 0.5) borderColor = 'border-red-300';
  else if (evidence.compositeScore < 0.75) borderColor = 'border-yellow-300';

  return (
    <div
      className={`border-2 ${borderColor} rounded-lg p-4 space-y-3`}
      data-testid={`evidence-card-${evidence.clusterId}`}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">{evidence.cellType}</h3>
          <p className="text-xs text-gray-500">Cluster {evidence.clusterId}</p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-bold text-gray-900">{compositePct}%</p>
          <p className="text-xs text-gray-500">Composite</p>
        </div>
      </div>

      {/* Score breakdown */}
      <div className="space-y-1.5">
        <ScoreBar label="Marker score" value={evidence.markerScore} />
        <ScoreBar label="Reference mapping" value={evidence.referenceMappingScore} />
        <ScoreBar label="Ontology alignment" value={evidence.ontologyAlignmentScore} />
      </div>

      {/* Marker evidence */}
      <div>
        <h4 className="text-xs font-medium text-gray-500 mb-1.5">Marker evidence</h4>
        <MarkerList markers={evidence.markers} />
      </div>
    </div>
  );
}
