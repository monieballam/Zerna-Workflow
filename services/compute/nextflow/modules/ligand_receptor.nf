/*
 * LIGAND_RECEPTOR process — wraps methods/annotation/ligand_receptor.py
 * Labels: cpu_large (permutation testing is compute-intensive)
 */

process LIGAND_RECEPTOR {
    label 'cpu_large'
    tag   "${task.index}"

    container "${params.container_registry}/zerna-annotation:${params.container_tag}"

    input:
        path adata_path
        val  cluster_key
        val  resource_name
        val  expr_prop
        val  n_perms

    output:
        path 'lr_results.h5ad',   emit: adata
        path 'lr_results.csv',    emit: csv
        path 'lr_metrics.json',   emit: metrics

    script:
    """
    python - <<'EOF'
import json
import anndata as ad
from methods.annotation.ligand_receptor import (
    LigandReceptorMethod,
    LigandReceptorInput,
    results_to_csv,
)

adata = ad.read_h5ad("${adata_path}")
method = LigandReceptorMethod()
result = method.execute(
    LigandReceptorInput(
        adata=adata,
        cluster_key="${cluster_key}",
        resource_name="${resource_name}",
        expr_prop=${expr_prop},
        n_perms=${n_perms},
    ),
    compute=None,
)
result.adata.write_h5ad("lr_results.h5ad")
csv_bytes = results_to_csv(result.results_df)
with open("lr_results.csv", "wb") as f:
    f.write(csv_bytes)
with open("lr_metrics.json", "w") as f:
    json.dump(result.metrics.model_dump(), f)
EOF
    """

    stub:
    """
    cp ${adata_path} lr_results.h5ad
    echo 'source,target,ligand_complex,receptor_complex,liana_rank' > lr_results.csv
    echo '{}' > lr_metrics.json
    """
}
