/*
 * DIFFERENTIAL_EXPRESSION process — wraps methods/annotation/differential_expression.py
 * Labels: cpu_large (DE across all clusters is memory-intensive)
 */

process DIFFERENTIAL_EXPRESSION {
    label 'cpu_large'
    tag   "${task.index}"

    container "${params.container_registry}/zerna-annotation:${params.container_tag}"

    input:
        path adata_path
        val  cluster_key
        val  method
        val  n_genes

    output:
        path 'de_results.h5ad',    emit: adata
        path 'de_results.csv',     emit: csv
        path 'de_metrics.json',    emit: metrics

    script:
    """
    python - <<'EOF'
import json
import anndata as ad
from methods.annotation.differential_expression import (
    DifferentialExpressionMethod,
    DifferentialExpressionInput,
    results_to_csv,
)

adata = ad.read_h5ad("${adata_path}")
method = DifferentialExpressionMethod()
result = method.execute(
    DifferentialExpressionInput(
        adata=adata,
        cluster_key="${cluster_key}",
        method="${method}",
        n_genes=${n_genes},
    ),
    compute=None,
)
result.adata.write_h5ad("de_results.h5ad")
csv_bytes = results_to_csv(result.results_df)
with open("de_results.csv", "wb") as f:
    f.write(csv_bytes)
with open("de_metrics.json", "w") as f:
    json.dump(result.metrics.model_dump(), f)
EOF
    """

    stub:
    """
    cp ${adata_path} de_results.h5ad
    echo 'cluster,gene,score,logfoldchange,pval,pval_adj' > de_results.csv
    echo '{}' > de_metrics.json
    """
}
