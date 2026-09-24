'use client';

export default function MarkerEvidenceList({
  markers,
  geneOverlayGene,
  onGeneClick,
  compact = true,
}: {
  markers: string[];
  geneOverlayGene: string | null;
  onGeneClick?: (gene: string) => void;
  compact?: boolean;
}) {
  if (markers.length === 0) {
    return <p className="text-[11px] text-gray-400">None listed.</p>;
  }

  return (
    <div className={`flex flex-wrap gap-1 ${compact ? '' : 'gap-1.5'}`}>
      {markers.map((gene) => {
        const active = geneOverlayGene === gene;
        const interactive = Boolean(onGeneClick);
        return (
          <button
            key={gene}
            type="button"
            disabled={!interactive}
            onClick={() => onGeneClick?.(gene)}
            title={interactive ? 'Overlay expression' : undefined}
            className={`rounded-full px-2 py-0.5 text-[11px] font-mono transition-colors ${
              interactive ? 'cursor-pointer' : 'cursor-default'
            } ${
              active
                ? 'bg-blue-100 text-blue-800'
                : interactive
                  ? 'bg-gray-100 text-gray-800 hover:bg-gray-200'
                  : 'bg-gray-50 text-gray-600'
            }`}
          >
            {gene}
          </button>
        );
      })}
    </div>
  );
}
