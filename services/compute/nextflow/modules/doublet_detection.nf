/*
 * DOUBLET_DETECTION process — wraps methods/preprocessing/doublet_detection.py
 * Labels: cpu_small (default scrublet; SOLO and legacy backends are configured via worker/Temporal, not this stub)
 */

process DOUBLET_DETECTION {
    label 'cpu_small'
    tag   "${task.index}"

    container "${params.container_registry}/zerna-preprocessing:${params.container_tag}"

    input:
        path adata_path
        val  expected_doublet_rate
        val  random_state

    output:
        path 'doublet_filtered.h5ad',  emit: adata
        path 'doublet_metrics.json',   emit: metrics

    script:
    """
    python - <<'EOF'
import json
import anndata as ad
from methods.preprocessing.doublet_detection import DoubletDetectionMethod, DoubletDetectionInput

adata = ad.read_h5ad("${adata_path}")
method = DoubletDetectionMethod()
result = method.execute(
    DoubletDetectionInput(
        adata=adata,
        expected_doublet_rate=${expected_doublet_rate},
        random_state=${random_state},
    ),
    compute=None,
)
result.adata.write_h5ad("doublet_filtered.h5ad")
with open("doublet_metrics.json", "w") as f:
    json.dump(result.metrics.model_dump(), f)
EOF
    """

    stub:
    """
    cp ${adata_path} doublet_filtered.h5ad
    echo '{}' > doublet_metrics.json
    """
}
