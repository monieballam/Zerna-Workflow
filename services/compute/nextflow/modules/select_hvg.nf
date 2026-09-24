/*
 * SELECT_HVG process — wraps methods/preprocessing/hvg_selection.py
 * Labels: cpu_small (HVG selection is CPU-only)
 */

process SELECT_HVG {
    label 'cpu_small'
    tag   "${task.index}"

    container "${params.container_registry}/zerna-preprocessing:${params.container_tag}"

    input:
        path adata_path
        val  n_top_genes
        val  flavor
        val  batch_key

    output:
        path 'hvg_selected.h5ad',  emit: adata
        path 'hvg_metrics.json',   emit: metrics

    script:
    def batch_key_arg = batch_key ? "batch_key='${batch_key}'" : "batch_key=None"
    """
    python - <<'EOF'
import json
import anndata as ad
from methods.preprocessing.hvg_selection import HVGSelectionMethod, HVGSelectionInput

adata = ad.read_h5ad("${adata_path}")
method = HVGSelectionMethod()
result = method.execute(
    HVGSelectionInput(
        adata=adata,
        n_top_genes=${n_top_genes},
        flavor="${flavor}",
        ${batch_key_arg},
    ),
    compute=None,
)
result.adata.write_h5ad("hvg_selected.h5ad")
with open("hvg_metrics.json", "w") as f:
    json.dump(result.metrics.model_dump(), f)
EOF
    """

    stub:
    """
    cp ${adata_path} hvg_selected.h5ad
    echo '{}' > hvg_metrics.json
    """
}
