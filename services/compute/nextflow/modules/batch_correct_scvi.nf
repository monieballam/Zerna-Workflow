/*
 * BATCH_CORRECT_SCVI process — wraps methods/dimensionality_reduction/batch_correction.py (ScVIMethod)
 * Labels: gpu_preferred (scVI trains faster on GPU)
 */

process BATCH_CORRECT_SCVI {
    label 'gpu_preferred'
    tag   "${task.index}"

    container "${params.container_registry}/zerna-dimred:${params.container_tag}"

    input:
        path adata_path
        val  batch_key
        val  random_state

    output:
        path 'scvi_corrected.h5ad',  emit: adata
        path 'scvi_metrics.json',    emit: metrics

    script:
    def batch_key_arg = batch_key ? "batch_key='${batch_key}'" : "batch_key=None"
    """
    python - <<'EOF'
import json
import anndata as ad
from methods.dimensionality_reduction.batch_correction import ScVIMethod, ScVIInput

adata = ad.read_h5ad("${adata_path}")
method = ScVIMethod()
result = method.execute(
    ScVIInput(
        adata=adata,
        ${batch_key_arg},
        random_state=${random_state},
    ),
    compute=None,
)
result.adata.write_h5ad("scvi_corrected.h5ad")
with open("scvi_metrics.json", "w") as f:
    json.dump(result.metrics.model_dump(), f)
EOF
    """

    stub:
    """
    cp ${adata_path} scvi_corrected.h5ad
    echo '{}' > scvi_metrics.json
    """
}
