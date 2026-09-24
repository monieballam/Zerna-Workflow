#!/usr/bin/env nextflow
/*
 * Zerna Single-Cell Pipeline — main entry point (Nextflow DSL2)
 *
 * Orchestrates the full single-cell RNA-seq analysis workflow:
 *   QC → Doublet Detection → Normalization → HVG → PCA
 *   → (optional Batch Correction) → Clustering → Embedding
 *   → Annotation → DE → (optional Pathway Scoring)
 *   → (optional Ligand-Receptor Analysis)
 *
 * Progress events are emitted to the Control Plane after each major step.
 */

nextflow.enable.dsl = 2

// Import all process modules
include { QC_FILTER }              from './modules/qc_filter'
include { DOUBLET_DETECTION }      from './modules/doublet_detection'
include { NORMALIZE }              from './modules/normalize'
include { SELECT_HVG }             from './modules/select_hvg'
include { RUN_PCA }                from './modules/run_pca'
include { BATCH_CORRECT_HARMONY }  from './modules/batch_correct_harmony'
include { BATCH_CORRECT_SCVI }     from './modules/batch_correct_scvi'
include { CLUSTER }                from './modules/cluster'
include { EMBED }                  from './modules/embed'
include { ANNOTATE }               from './modules/annotate'
include { DIFFERENTIAL_EXPRESSION } from './modules/differential_expression'
include { PATHWAY_SCORING }        from './modules/pathway_scoring'
include { LIGAND_RECEPTOR }        from './modules/ligand_receptor'
include { EMIT_PROGRESS }          from './modules/emit_progress'

// ---------------------------------------------------------------------------
// Validate required parameters
// ---------------------------------------------------------------------------
if (!params.dataset_path) {
    error "Parameter 'dataset_path' is required"
}
if (!params.run_id) {
    error "Parameter 'run_id' is required"
}

// ---------------------------------------------------------------------------
// Main workflow
// ---------------------------------------------------------------------------
workflow SINGLE_CELL_PIPELINE {
    take:
        dataset_path   // path to input h5ad file
        run_params     // map of runtime parameters

    main:
        // ── Step 1: QC Filtering ──────────────────────────────────────────
        qc_ch = QC_FILTER(
            dataset_path,
            run_params.qc_min_genes,
            run_params.qc_max_genes,
            run_params.qc_min_cells,
            run_params.qc_max_mito_pct,
            run_params.qc_species,
            run_params.qc_mito_prefix
        )
        EMIT_PROGRESS(run_params.run_id, 'qc_filter', 'completed', run_params.control_plane_url, run_params.control_plane_token)

        // ── Step 2: Doublet Detection ─────────────────────────────────────
        doublet_ch = DOUBLET_DETECTION(
            qc_ch.adata,
            run_params.doublet_expected_rate,
            run_params.random_seed
        )
        EMIT_PROGRESS(run_params.run_id, 'doublet_detection', 'completed', run_params.control_plane_url, run_params.control_plane_token)

        // ── Step 3: Normalization ─────────────────────────────────────────
        norm_ch = NORMALIZE(
            doublet_ch.adata,
            run_params.norm_target_sum,
            run_params.norm_scale,
            run_params.norm_max_value
        )
        EMIT_PROGRESS(run_params.run_id, 'normalization', 'completed', run_params.control_plane_url, run_params.control_plane_token)

        // ── Step 4: HVG Selection ─────────────────────────────────────────
        hvg_ch = SELECT_HVG(
            norm_ch.adata,
            run_params.hvg_n_top_genes,
            run_params.hvg_flavor,
            run_params.hvg_batch_key
        )
        EMIT_PROGRESS(run_params.run_id, 'hvg_selection', 'completed', run_params.control_plane_url, run_params.control_plane_token)

        // ── Step 5: PCA ───────────────────────────────────────────────────
        pca_ch = RUN_PCA(
            hvg_ch.adata,
            run_params.pca_n_components,
            run_params.random_seed
        )
        EMIT_PROGRESS(run_params.run_id, 'pca', 'completed', run_params.control_plane_url, run_params.control_plane_token)

        // ── Step 6: Batch Correction (conditional) ────────────────────────
        if (run_params.batch_correction) {
            if (run_params.integration_mode == 'scvi') {
                corrected_ch = BATCH_CORRECT_SCVI(
                    pca_ch.adata,
                    run_params.batch_key,
                    run_params.random_seed
                )
            } else {
                // Default: Harmony
                corrected_ch = BATCH_CORRECT_HARMONY(
                    pca_ch.adata,
                    run_params.batch_key,
                    run_params.random_seed
                )
            }
            EMIT_PROGRESS(run_params.run_id, 'batch_correction', 'completed', run_params.control_plane_url, run_params.control_plane_token)
        } else {
            corrected_ch = pca_ch
        }

        // ── Step 7: Clustering ────────────────────────────────────────────
        cluster_ch = CLUSTER(
            corrected_ch.adata,
            run_params.clustering_method,
            run_params.clustering_resolution,
            run_params.clustering_n_neighbors,
            run_params.random_seed
        )
        EMIT_PROGRESS(run_params.run_id, 'clustering', 'completed', run_params.control_plane_url, run_params.control_plane_token)

        // ── Step 8: Embedding ─────────────────────────────────────────────
        embedding_ch = EMBED(
            corrected_ch.adata,
            run_params.embedding_method,
            run_params.umap_n_components,
            run_params.umap_min_dist,
            run_params.tsne_perplexity,
            run_params.clustering_n_neighbors,
            run_params.random_seed
        )
        EMIT_PROGRESS(run_params.run_id, 'embedding', 'completed', run_params.control_plane_url, run_params.control_plane_token)

        // ── Step 9: Cell Type Annotation ──────────────────────────────────
        annotate_ch = ANNOTATE(
            cluster_ch.adata,
            run_params.annotation_method,
            run_params.annotation_model,
            run_params.annotation_majority_voting,
            run_params.annotation_cluster_key,
            run_params.annotation_min_prob,
            run_params.annotation_marker_pack_path,
            run_params.annotation_cluster_prior_path,
            run_params.annotation_tissue_context,
            run_params.annotation_cancer_type,
            run_params.annotation_species,
            run_params.annotation_cluster_marker_top_n,
            run_params.annotation_min_marker_overlap,
            run_params.annotation_benchmark_reference_key,
            run_params.knowledge_pack_version
        )
        EMIT_PROGRESS(run_params.run_id, 'annotation', 'completed', run_params.control_plane_url, run_params.control_plane_token)

        // ── Step 10: Differential Expression ─────────────────────────────
        de_ch = DIFFERENTIAL_EXPRESSION(
            annotate_ch.adata,
            run_params.de_cluster_key,
            run_params.de_method,
            run_params.de_n_genes
        )
        EMIT_PROGRESS(run_params.run_id, 'differential_expression', 'completed', run_params.control_plane_url, run_params.control_plane_token)

        // ── Step 11: Pathway Scoring (conditional) ────────────────────────
        if (run_params.pathway_scoring && run_params.pathway_net_path) {
            pathway_ch = PATHWAY_SCORING(
                de_ch.adata,
                run_params.pathway_net_path,
                run_params.pathway_database,
                run_params.knowledge_pack_version
            )
            EMIT_PROGRESS(run_params.run_id, 'pathway_scoring', 'completed', run_params.control_plane_url, run_params.control_plane_token)
            final_adata = pathway_ch.adata
        } else {
            final_adata = de_ch.adata
        }

        // ── Step 12: Ligand-Receptor Analysis (conditional) ───────────────
        if (run_params.ligand_receptor) {
            lr_ch = LIGAND_RECEPTOR(
                final_adata,
                run_params.de_cluster_key,
                run_params.lr_resource_name,
                run_params.lr_expr_prop,
                run_params.lr_n_perms
            )
            EMIT_PROGRESS(run_params.run_id, 'ligand_receptor', 'completed', run_params.control_plane_url, run_params.control_plane_token)
        }

        EMIT_PROGRESS(run_params.run_id, 'pipeline', 'completed', run_params.control_plane_url, run_params.control_plane_token)

    emit:
        h5ad      = final_adata
        de_csv    = de_ch.csv
        embedding = embedding_ch.adata
}

// ---------------------------------------------------------------------------
// Workflow entry point
// ---------------------------------------------------------------------------
workflow {
    // Build runtime params map from Nextflow params
    run_params = [
        run_id:                     params.run_id,
        random_seed:                params.random_seed,
        control_plane_url:          params.control_plane_url,
        control_plane_token:        params.control_plane_token,

        qc_min_genes:               params.qc_min_genes,
        qc_max_genes:               params.qc_max_genes,
        qc_min_cells:               params.qc_min_cells,
        qc_max_mito_pct:            params.qc_max_mito_pct,
        qc_species:                 params.qc_species ?: 'auto',
        qc_mito_prefix:             params.qc_mito_prefix ?: '',

        doublet_expected_rate:      params.doublet_expected_rate,

        norm_target_sum:            params.norm_target_sum,
        norm_scale:                 params.norm_scale,
        norm_max_value:             params.norm_max_value,

        hvg_n_top_genes:            params.hvg_n_top_genes,
        hvg_flavor:                 params.hvg_flavor,
        hvg_batch_key:              params.hvg_batch_key,

        pca_n_components:           params.pca_n_components,

        batch_correction:           params.batch_correction,
        integration_mode:           params.integration_mode ?: params.batch_method,
        batch_method:               params.batch_method,
        batch_key:                  params.batch_key,

        clustering_method:          params.clustering_method,
        clustering_resolution:      params.clustering_resolution,
        clustering_n_neighbors:     params.clustering_n_neighbors,

        embedding_method:           params.embedding_method,
        umap_n_components:          params.umap_n_components,
        umap_min_dist:              params.umap_min_dist,
        tsne_perplexity:            params.tsne_perplexity,

        annotation_method:          params.annotation_method,
        annotation_model:           params.annotation_model,
        annotation_majority_voting: params.annotation_majority_voting,
        annotation_cluster_key:     params.annotation_cluster_key,
        annotation_min_prob:        params.annotation_min_prob,
        annotation_marker_pack_path: params.annotation_marker_pack_path,
        annotation_cluster_prior_path: params.annotation_cluster_prior_path,
        annotation_tissue_context:  params.annotation_tissue_context,
        annotation_cancer_type:     params.annotation_cancer_type,
        annotation_species:         params.annotation_species,
        annotation_cluster_marker_top_n: params.annotation_cluster_marker_top_n,
        annotation_min_marker_overlap: params.annotation_min_marker_overlap,
        annotation_benchmark_reference_key: params.annotation_benchmark_reference_key,
        knowledge_pack_version:     params.knowledge_pack_version,

        de_cluster_key:             params.de_cluster_key,
        de_method:                  params.de_method,
        de_n_genes:                 params.de_n_genes,

        pathway_scoring:            params.pathway_scoring,
        pathway_database:           params.pathway_database,
        pathway_net_path:           params.pathway_net_path,

        ligand_receptor:            params.ligand_receptor,
        lr_resource_name:           params.lr_resource_name,
        lr_expr_prop:               params.lr_expr_prop,
        lr_n_perms:                 params.lr_n_perms,
    ]

    SINGLE_CELL_PIPELINE(
        Channel.fromPath(params.dataset_path),
        run_params
    )
}
