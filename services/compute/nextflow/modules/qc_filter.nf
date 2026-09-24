/*
 * QC_FILTER process — wraps methods/preprocessing/qc_filter.py
 * Labels: cpu_small (QC is CPU-only, lightweight)
 */

process QC_FILTER {
    label 'cpu_small'
    tag   "${task.index}"

    container "${params.container_registry}/zerna-preprocessing:${params.container_tag}"

    input:
        path  adata_path
        val   min_genes
        val   max_genes
        val   min_cells
        val   max_mito_pct
        val   qc_species
        val   mito_prefix

    output:
        path 'qc_filtered.h5ad', emit: adata
        path 'qc_metrics.json',  emit: metrics

    script:
    """
    python - <<'EOF'
import json
import anndata as ad
from methods.preprocessing.qc_filter import QCFilterMethod, QCFilterInput

adata = ad.read_h5ad("${adata_path}")
_raw_mito = """${mito_prefix}"""
_legacy_mito = None if not _raw_mito.strip() else _raw_mito.strip()
method = QCFilterMethod()
result = method.execute(
    QCFilterInput(
        adata=adata,
        species="""${qc_species}""",
        min_genes=${min_genes},
        max_genes=${max_genes},
        min_cells=${min_cells},
        max_mito_pct=${max_mito_pct},
        mito_prefix=_legacy_mito,
    ),
    compute=None,
)
result.adata.write_h5ad("qc_filtered.h5ad")
with open("qc_metrics.json", "w") as f:
    json.dump(result.metrics.model_dump(), f)
EOF
    """

    stub:
    """
    cp ${adata_path} qc_filtered.h5ad
    echo '{}' > qc_metrics.json
    """
}
