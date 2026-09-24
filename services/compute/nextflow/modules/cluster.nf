/*
 * CLUSTER process — wraps methods/dimensionality_reduction/clustering.py
 * Supports 'leiden' (default) and 'louvain' methods.
 * Labels: cpu_medium (graph-based clustering, CPU-only)
 */

process CLUSTER {
    label 'cpu_medium'
    tag   "${task.index}"

    container "${params.container_registry}/zerna-dimred:${params.container_tag}"

    input:
        path adata_path
        val  method
        val  resolution
        val  n_neighbors
        val  random_state

    output:
        path 'clustered.h5ad',       emit: adata
        path 'cluster_metrics.json', emit: metrics

    script:
    """
    python - <<'EOF'
import json
import anndata as ad

method_name = "${method}"
if method_name == "louvain":
    from methods.dimensionality_reduction.clustering import LouvainMethod as ClusterMethod, ClusteringInput
else:
    from methods.dimensionality_reduction.clustering import LeidenMethod as ClusterMethod, ClusteringInput

adata = ad.read_h5ad("${adata_path}")
method = ClusterMethod()
result = method.execute(
    ClusteringInput(
        adata=adata,
        resolution=${resolution},
        n_neighbors=${n_neighbors},
        random_state=${random_state},
    ),
    compute=None,
)
result.adata.write_h5ad("clustered.h5ad")
with open("cluster_metrics.json", "w") as f:
    json.dump(result.metrics.model_dump(), f)
EOF
    """

    stub:
    """
    cp ${adata_path} clustered.h5ad
    echo '{}' > cluster_metrics.json
    """
}
