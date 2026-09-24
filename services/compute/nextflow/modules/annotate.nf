/*
 * ANNOTATE process — wraps methods/annotation/cell_type_annotation.py
 * Labels: cpu_medium (CellTypist inference)
 */

process ANNOTATE {
    label 'cpu_medium'
    tag   "${task.index}"

    container "${params.container_registry}/zerna-annotation:${params.container_tag}"

    input:
        path adata_path
        val  annotation_method
        val  model_name
        val  majority_voting
        val  cluster_key
        val  min_prob
        val  marker_pack_path
        val  cluster_prior_path
        val  tissue_context
        val  cancer_type
        val  species
        val  cluster_marker_top_n
        val  min_marker_overlap
        val  benchmark_reference_key
        val  knowledge_pack_version

    output:
        path 'annotated.h5ad',         emit: adata
        path 'annotation_metrics.json', emit: metrics
        path 'cluster_markers.csv',    emit: cluster_markers

    script:
    def kp_arg = knowledge_pack_version ? "knowledge_pack_version='${knowledge_pack_version}'" : "knowledge_pack_version=None"
    def cluster_key_arg = cluster_key ? "cluster_key='${cluster_key}'" : "cluster_key=None"
    def marker_pack_arg = marker_pack_path ? "marker_pack_path='${marker_pack_path}'" : "marker_pack_path=None"
    def cluster_prior_arg = cluster_prior_path ? "cluster_prior_path='${cluster_prior_path}'" : "cluster_prior_path=None"
    def cancer_arg = cancer_type ? "cancer_type='${cancer_type}'" : "cancer_type=None"
    def benchmark_arg = benchmark_reference_key ? "benchmark_reference_key='${benchmark_reference_key}'" : "benchmark_reference_key=None"
    """
    python - <<'EOF'
import json
import anndata as ad
from methods.annotation.cell_type_annotation import CellTypistMethod, CellTypistInput

adata = ad.read_h5ad("${adata_path}")
method = CellTypistMethod()
result = method.execute(
    CellTypistInput(
        adata=adata,
        annotation_method="${annotation_method}",
        model_name="${model_name}",
        majority_voting=${majority_voting ? 'True' : 'False'},
        ${cluster_key_arg},
        min_prob=${min_prob},
        ${marker_pack_arg},
        ${cluster_prior_arg},
        tissue_context="${tissue_context}",
        ${cancer_arg},
        species="${species}",
        cluster_marker_top_n=${cluster_marker_top_n},
        min_marker_overlap=${min_marker_overlap},
        cluster_markers_export_path="cluster_markers.csv",
        ${benchmark_arg},
        ${kp_arg},
    ),
    compute=None,
)
result.adata.write_h5ad("annotated.h5ad")
with open("annotation_metrics.json", "w") as f:
    json.dump(result.metrics.model_dump(), f)
EOF
    """

    stub:
    """
    cp ${adata_path} annotated.h5ad
    echo '{}' > annotation_metrics.json
    echo 'cluster,gene,score,logfoldchange,pval_adj' > cluster_markers.csv
    """
}
