export interface ClusterCandidate {
  cell_type: string;
  score: number;
  n_markers: number;
}

export interface EvidenceHit {
  cluster_id: string | null;
  label: string;
  lineage: string | null;
  score: number;
}

export interface RunnerUpLabel {
  cell_type: string;
  score: number;
  n_markers: number;
}

export interface ClusterInspectorSummary {
  cluster_id: string;
  n_cells: number;
  label: string;
  /** When present, merged cellType / final_display string differs from canonical hierarchy headline. */
  display_label_secondary?: string | null;
  /** Per-cluster mode of obs ``annotation_label`` (legacy engine); not structural truth. */
  raw_annotation_label_mode?: string | null;
  confidence: string;
  summary: string;
  top_markers: string[];
  evidence_count: number;
  evidence_hits: EvidenceHit[];
  top_cell_types: ClusterCandidate[];
  annotation_mode?: string | null;
  annotation_support_markers?: string[];
  annotation_support_source_label?: string | null;
  /** True when the matched pack key matches the finest hierarchy segment (or full headline / normalized). */
  annotation_support_aligned_with_primary_headline?: boolean;
  /** Partition views: genes are intersection of partition DE with pack markers for ``annotation_support_source_label``. */
  annotation_support_partition_de_overlap?: boolean;
  retrieval_tiebreak_applied?: boolean;
  conservative_status?: string | null;
  conservative_reason?: string | null;
  runner_up_labels?: RunnerUpLabel[];
}
