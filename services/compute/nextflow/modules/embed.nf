/*
 * EMBED process — wraps methods/dimensionality_reduction/embedding.py
 * Supports 'umap' (default) and 'tsne' methods.
 * Labels: gpu_preferred (UMAP/t-SNE benefit from GPU)
 */

process EMBED {
    label 'gpu_preferred'
    tag   "${task.index}"

    container "${params.container_registry}/zerna-dimred:${params.container_tag}"

    input:
        path adata_path
        val  method
        val  umap_n_components
        val  umap_min_dist
        val  tsne_perplexity
        val  n_neighbors
        val  random_state

    output:
        path 'embedded.h5ad',         emit: adata
        path 'embedding_key.txt',     emit: embedding_key

    script:
    """
    python - <<'EOF'
import anndata as ad

method_name = "${method}"
adata = ad.read_h5ad("${adata_path}")

if method_name == "tsne":
    from methods.dimensionality_reduction.embedding import TSNEMethod, TSNEInput
    method = TSNEMethod()
    result = method.execute(
        TSNEInput(
            adata=adata,
            n_components=${umap_n_components},
            n_neighbors=${n_neighbors},
            perplexity=${tsne_perplexity},
            random_state=${random_state},
        ),
        compute=None,
    )
else:
    from methods.dimensionality_reduction.embedding import UMAPMethod, UMAPInput
    method = UMAPMethod()
    result = method.execute(
        UMAPInput(
            adata=adata,
            n_components=${umap_n_components},
            n_neighbors=${n_neighbors},
            min_dist=${umap_min_dist},
            random_state=${random_state},
        ),
        compute=None,
    )

result.adata.write_h5ad("embedded.h5ad")
with open("embedding_key.txt", "w") as f:
    f.write(result.embedding_key)
EOF
    """

    stub:
    """
    cp ${adata_path} embedded.h5ad
    echo 'X_umap' > embedding_key.txt
    """
}
