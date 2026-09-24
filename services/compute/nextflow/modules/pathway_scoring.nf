/*
 * PATHWAY_SCORING process — wraps methods/annotation/pathway_scoring.py
 * Labels: cpu_large (decoupler scoring across many pathways)
 */

process PATHWAY_SCORING {
    label 'cpu_large'
    tag   "${task.index}"

    container "${params.container_registry}/zerna-annotation:${params.container_tag}"

    input:
        path adata_path
        path net_path
        val  pathway_database
        val  knowledge_pack_version

    output:
        path 'pathway_scored.h5ad',    emit: adata
        path 'pathway_metrics.json',   emit: metrics

    script:
    def kp_arg = knowledge_pack_version ? "knowledge_pack_version='${knowledge_pack_version}'" : "knowledge_pack_version=None"
    """
    python - <<'EOF'
import json
import anndata as ad
import pandas as pd
from methods.annotation.pathway_scoring import PathwayScoringMethod, PathwayScoringInput

adata = ad.read_h5ad("${adata_path}")
net = pd.read_csv("${net_path}")
method = PathwayScoringMethod()
result = method.execute(
    PathwayScoringInput(
        adata=adata,
        net=net,
        pathway_database="${pathway_database}",
        ${kp_arg},
    ),
    compute=None,
)
result.adata.write_h5ad("pathway_scored.h5ad")
with open("pathway_metrics.json", "w") as f:
    json.dump(result.metrics.model_dump(), f)
EOF
    """

    stub:
    """
    cp ${adata_path} pathway_scored.h5ad
    echo '{}' > pathway_metrics.json
    """
}
