/*
 * RUN_PCA process — wraps methods/dimensionality_reduction/pca.py
 * Labels: gpu_preferred (GPU-accelerated SVD)
 */

process RUN_PCA {
    label 'gpu_preferred'
    tag   "${task.index}"

    container "${params.container_registry}/zerna-dimred:${params.container_tag}"

    input:
        path adata_path
        val  n_components
        val  random_state

    output:
        path 'pca.h5ad',         emit: adata
        path 'pca_metrics.json', emit: metrics

    script:
    """
    python - <<'EOF'
import json
import anndata as ad
from methods.dimensionality_reduction.pca import PCAMethod, PCAInput

adata = ad.read_h5ad("${adata_path}")
method = PCAMethod()
result = method.execute(
    PCAInput(
        adata=adata,
        n_components=${n_components},
        use_highly_variable=True,
        random_state=${random_state},
    ),
    compute=None,
)
result.adata.write_h5ad("pca.h5ad")
with open("pca_metrics.json", "w") as f:
    json.dump(result.metrics.model_dump(), f)
EOF
    """

    stub:
    """
    cp ${adata_path} pca.h5ad
    echo '{}' > pca_metrics.json
    """
}
