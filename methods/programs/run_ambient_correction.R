#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(Matrix)
})

parse_args <- function(args) {
  parsed <- list()
  i <- 1
  while (i <= length(args)) {
    key <- args[[i]]
    if (!startsWith(key, "--")) {
      stop(sprintf("Unexpected argument: %s", key))
    }
    if (i == length(args)) {
      stop(sprintf("Missing value for %s", key))
    }
    parsed[[substring(key, 3)]] <- args[[i + 1]]
    i <- i + 2
  }
  parsed
}

build_clusters <- function(counts, obs, random_state) {
  suppressPackageStartupMessages({
    library(Seurat)
  })

  if (ncol(counts) < 4 || nrow(counts) < 20) {
    stop(
      "SoupX ambient correction requires at least 4 cells and 20 genes in this worker. ",
      "Use identity/off for smaller matrices."
    )
  }

  set.seed(random_state)
  if (ncol(obs) > 0) {
    seu <- Seurat::CreateSeuratObject(counts = counts, meta.data = obs)
  } else {
    seu <- Seurat::CreateSeuratObject(counts = counts)
  }

  seu <- Seurat::NormalizeData(seu, verbose = FALSE)
  seu <- Seurat::FindVariableFeatures(
    seu,
    selection.method = "vst",
    nfeatures = min(2000L, nrow(seu)),
    verbose = FALSE
  )

  variable_features <- Seurat::VariableFeatures(seu)
  if (length(variable_features) < 20) {
    stop(
      "SoupX clustering could not identify enough variable genes for automatic ",
      "contamination estimation. Use identity/off for this dataset."
    )
  }

  seu <- Seurat::ScaleData(seu, features = variable_features, verbose = FALSE)

  max_pcs <- min(30L, ncol(seu) - 1L, length(variable_features))
  if (max_pcs < 2L) {
    stop(
      "SoupX clustering requires at least 3 cells and 2 usable principal components. ",
      "Use identity/off for this dataset."
    )
  }

  seu <- Seurat::RunPCA(
    seu,
    features = variable_features,
    npcs = max_pcs,
    verbose = FALSE
  )
  dims <- seq_len(min(10L, max_pcs))
  k_param <- max(2L, min(20L, ncol(seu) - 1L))

  seu <- Seurat::FindNeighbors(seu, dims = dims, k.param = k_param, verbose = FALSE)
  seu <- Seurat::FindClusters(seu, resolution = 0.5, verbose = FALSE)

  clusters <- as.character(seu@meta.data[["seurat_clusters"]])
  names(clusters) <- colnames(seu)
  unique_clusters <- unique(clusters)
  if (length(unique_clusters) < 2L) {
    stop(
      "SoupX automatic contamination estimation needs at least two transcriptionally distinct ",
      "clusters in this filtered-counts-only mode. Use identity/off for homogeneous datasets."
    )
  }

  list(clusters = clusters, n_clusters = length(unique_clusters))
}

args <- parse_args(commandArgs(trailingOnly = TRUE))
matrix_path <- args[["matrix"]]
obs_path <- args[["obs"]]
genes_path <- args[["genes"]]
output_matrix_path <- args[["output_matrix"]]
metrics_path <- args[["metrics"]]
random_state <- as.integer(args[["random_state"]])

counts <- Matrix::readMM(matrix_path)
counts <- methods::as(counts, "CsparseMatrix")
obs <- read.csv(obs_path, row.names = 1, check.names = FALSE, stringsAsFactors = FALSE)
genes <- read.csv(genes_path, check.names = FALSE, stringsAsFactors = FALSE)

rownames(counts) <- as.character(genes[["gene"]])
colnames(counts) <- rownames(obs)

suppressPackageStartupMessages({
  library(SoupX)
})

row_sums <- Matrix::rowSums(counts)
soup_profile <- data.frame(
  row.names = rownames(counts),
  est = row_sums / sum(counts),
  counts = row_sums
)

cluster_info <- build_clusters(counts, obs, random_state)

sc <- SoupX::SoupChannel(counts, counts, calcSoupProfile = FALSE)
sc <- SoupX::setSoupProfile(sc, soup_profile)
sc <- SoupX::setClusters(sc, cluster_info$clusters)
sc <- SoupX::autoEstCont(sc, doPlot = FALSE, verbose = FALSE)

corrected <- SoupX::adjustCounts(sc, roundToInt = TRUE)
rho_values <- unique(as.numeric(sc$metaData$rho))
rho_values <- rho_values[is.finite(rho_values)]
estimated_rho <- if (length(rho_values) > 0L) mean(rho_values) else NA_real_

Matrix::writeMM(corrected, output_matrix_path)
write.csv(
  data.frame(
    estimated_contamination_fraction = estimated_rho,
    soup_profile_source = "filtered_counts_only",
    clustering_source = "seurat_graph",
    cluster_count = cluster_info$n_clusters,
    stringsAsFactors = FALSE
  ),
  metrics_path,
  row.names = FALSE
)
