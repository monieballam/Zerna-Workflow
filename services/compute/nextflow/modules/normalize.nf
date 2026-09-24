/*
 * NORMALIZE process — wraps methods/preprocessing/normalization.py
 * Labels: gpu_preferred (scaling benefits from GPU)
 */

process NORMALIZE {
    label 'gpu_preferred'
    tag   "${task.index}"

    container "${params.container_registry}/zerna-preprocessing:${params.container_tag}"

    input:
        path adata_path
        val  target_sum
        val  scale
        val  max_value

    output:
        path 'normalized.h5ad', emit: adata

    script:
    """
    python - <<'EOF'
import anndata as ad
from methods.preprocessing.normalization import NormalizationMethod, NormalizationInput

adata = ad.read_h5ad("${adata_path}")
method = NormalizationMethod()
result = method.execute(
    NormalizationInput(
        adata=adata,
        target_sum=${target_sum},
        scale=${scale ? 'True' : 'False'},
        max_value=${max_value},
    ),
    compute=None,
)
result.adata.write_h5ad("normalized.h5ad")
EOF
    """

    stub:
    """
    cp ${adata_path} normalized.h5ad
    """
}
