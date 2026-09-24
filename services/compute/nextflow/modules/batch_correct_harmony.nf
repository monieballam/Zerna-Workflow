/*
 * BATCH_CORRECT_HARMONY process — wraps methods/dimensionality_reduction/batch_correction.py (HarmonyMethod)
 * Labels: gpu_preferred
 */

process BATCH_CORRECT_HARMONY {
    label 'gpu_preferred'
    tag   "${task.index}"

    container "${params.container_registry}/zerna-dimred:${params.container_tag}"

    input:
        path adata_path
        val  batch_key
        val  random_state

    output:
        path 'harmony_corrected.h5ad',  emit: adata
        path 'harmony_metrics.json',    emit: metrics

    script:
    def batch_key_arg = batch_key ? "batch_key='${batch_key}'" : "batch_key=None"
    """
    python - <<'EOF'
import json
import anndata as ad
from methods.dimensionality_reduction.batch_correction import HarmonyMethod, HarmonyInput

adata = ad.read_h5ad("${adata_path}")
method = HarmonyMethod()
result = method.execute(
    HarmonyInput(
        adata=adata,
        ${batch_key_arg},
        random_state=${random_state},
    ),
    compute=None,
)
result.adata.write_h5ad("harmony_corrected.h5ad")
with open("harmony_metrics.json", "w") as f:
    json.dump(result.metrics.model_dump(), f)
EOF
    """

    stub:
    """
    cp ${adata_path} harmony_corrected.h5ad
    echo '{}' > harmony_metrics.json
    """
}
