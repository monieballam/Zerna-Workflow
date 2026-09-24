import { deModeLabel } from '@/components/runs/DownstreamAnalysisPanels';

type GenericMetrics = { skipped?: boolean; reason?: string; [k: string]: unknown };

function scalarToDisplayString(v: unknown): string {
  if (v == null) return '';
  if (typeof v === 'string') return v.trim();
  if (typeof v === 'number' || typeof v === 'boolean' || typeof v === 'bigint') return String(v);
  return '';
}

export type BiologicalSummaryItem = {
  id: string;
  text: string;
};

/** Build concise “at a glance” lines from existing run results metrics only. */
export function buildBiologicalSummaryItems(
  stepMetrics: Record<string, GenericMetrics | undefined>
): {
  items: BiologicalSummaryItem[];
  dominantLine: string | null;
} {
  const items: BiologicalSummaryItem[] = [];
  const m = stepMetrics;

  const qc = m.qc_filter;
  if (qc && !qc.skipped && typeof qc.n_cells_after === 'number') {
    items.push({
      id: 'qc-cells',
      text: `~${qc.n_cells_after.toLocaleString()} cells after QC${typeof qc.n_genes_after === 'number' ? `, ${qc.n_genes_after.toLocaleString()} genes` : ''}.`,
    });
  }

  const cluster = m.cluster;
  if (cluster && !cluster.skipped && typeof cluster.n_clusters === 'number') {
    const ck =
      typeof cluster.cluster_key === 'string' && cluster.cluster_key.trim()
        ? cluster.cluster_key.trim()
        : 'clustering';
    const rowsRaw = Array.isArray(cluster.clusters) ? cluster.clusters : [];
    type ClusterTopRow = { label?: unknown; cluster_id?: unknown; n_cells: number };
    const isClusterTopRow = (r: unknown): r is ClusterTopRow =>
      Boolean(
        r && typeof r === 'object' && typeof (r as { n_cells?: unknown }).n_cells === 'number'
      );
    const top = rowsRaw
      .filter(isClusterTopRow)
      .sort((a, b) => b.n_cells - a.n_cells)
      .slice(0, 3);
    const parts = top.map((r) => {
      const labelStr = scalarToDisplayString(r.label);
      const idStr = scalarToDisplayString(r.cluster_id);
      const lab = labelStr || `cluster ${idStr || '?'}`;
      return `${lab} (${r.n_cells.toLocaleString()} cells)`;
    });
    let line = `${cluster.n_clusters} clusters (${ck})`;
    if (parts.length > 0) line += ` — largest: ${parts.join(', ')}`;
    items.push({ id: 'clusters', text: line });
  }

  const batch = m.batch_correction_harmony ?? m.batch_correction_scvi;
  if (batch && !batch.skipped) {
    const method = m.batch_correction_scvi ? 'scVI' : 'Harmony';
    const nb = typeof batch.n_batches === 'number' ? batch.n_batches : null;
    const bk =
      typeof batch.batch_key === 'string' && batch.batch_key.trim() ? batch.batch_key.trim() : null;
    items.push({
      id: 'batch',
      text: `Batch correction (${method})${nb != null ? `, ${nb} batches` : ''}${bk ? `, key \`${bk}\`` : ''}.`,
    });
  }

  const embed = m.embed;
  if (embed && !embed.skipped) {
    const rep =
      typeof embed.representation_used === 'string' && embed.representation_used.trim()
        ? embed.representation_used.trim()
        : null;
    const ek =
      typeof embed.embedding_key === 'string' && embed.embedding_key.trim()
        ? embed.embedding_key.trim()
        : null;
    if (rep || ek) {
      items.push({
        id: 'embedding',
        text: `Embedding uses ${ek ?? 'saved coordinates'}${rep ? ` from ${rep}` : ''}.`,
      });
    }
  }

  const ann = m.annotate;
  if (ann) {
    if (ann.skipped) {
      items.push({
        id: 'annotation',
        text: `Annotation skipped${typeof ann.reason === 'string' && ann.reason.trim() ? `: ${ann.reason.trim()}` : '.'}`,
      });
    } else {
      const nTypes =
        typeof ann.n_cell_types_predicted === 'number' ? ann.n_cell_types_predicted : null;
      const conf =
        typeof ann.mean_confidence === 'number' && Number.isFinite(ann.mean_confidence)
          ? ann.mean_confidence
          : null;
      let confPhrase = '';
      if (conf != null) {
        const pct = conf * 100;
        confPhrase =
          pct >= 55
            ? 'mean confidence is relatively high overall.'
            : 'mean confidence is mixed — review labels in the explorer.';
      }
      items.push({
        id: 'annotation',
        text: `Annotation${nTypes != null ? `: ${nTypes} predicted cell types` : ' completed'}${confPhrase ? `; ${confPhrase}` : '.'}`,
      });
    }
  }

  const de = m.differential_expression;
  if (de) {
    if (de.skipped) {
      items.push({
        id: 'de',
        text: `Differential expression skipped${typeof de.reason === 'string' && de.reason.trim() ? `: ${de.reason.trim()}` : '.'}`,
      });
    } else {
      const mode = deModeLabel(typeof de.de_mode === 'string' ? de.de_mode : undefined);
      items.push({ id: 'de', text: `DE: ${mode}.` });
    }
  }

  const pathway = m.pathway_scoring;
  if (pathway) {
    items.push({
      id: 'pathway',
      text: pathway.skipped
        ? `Pathway activity scoring skipped${pathway.reason ? `: ${pathway.reason}` : '.'}`
        : `Pathway activity scoring ran (${typeof pathway.n_pathways_scored === 'number' ? `${pathway.n_pathways_scored.toLocaleString()} pathways` : 'per-cell scores'}).`,
    });
  }

  const lr = m.ligand_receptor_analysis;
  if (lr) {
    items.push({
      id: 'lr',
      text: lr.skipped
        ? `Ligand–receptor analysis skipped${lr.reason ? `: ${lr.reason}` : '.'}`
        : `Ligand–receptor analysis ran (${typeof lr.n_interactions === 'number' ? `${lr.n_interactions.toLocaleString()} interactions` : 'LIANA output'}).`,
    });
  }

  const dominantLine =
    items.find((i) => i.id === 'clusters')?.text ??
    items.find((i) => i.id === 'annotation')?.text ??
    items[0]?.text ??
    null;

  return { items, dominantLine };
}
