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

minmax_scale <- function(values) {
  values <- as.numeric(values)
  min_value <- min(values, na.rm = TRUE)
  max_value <- max(values, na.rm = TRUE)
  if (!is.finite(min_value) || !is.finite(max_value) || identical(min_value, max_value)) {
    return(rep(0, length(values)))
  }
  (values - min_value) / (max_value - min_value)
}

args <- parse_args(commandArgs(trailingOnly = TRUE))
method <- args[["method"]]
matrix_path <- args[["matrix"]]
obs_path <- args[["obs"]]
genes_path <- args[["genes"]]
output_path <- args[["output"]]
threshold <- as.numeric(args[["threshold"]])
expected_doublet_rate <- as.numeric(args[["expected_doublet_rate"]])
random_state <- as.integer(args[["random_state"]])

counts <- Matrix::readMM(matrix_path)
counts <- methods::as(counts, "CsparseMatrix")
obs <- read.csv(obs_path, row.names = 1, check.names = FALSE, stringsAsFactors = FALSE)
genes <- read.csv(genes_path, check.names = FALSE, stringsAsFactors = FALSE)

rownames(counts) <- as.character(genes[["gene"]])
colnames(counts) <- rownames(obs)

if (method == "scDblFinder") {
  suppressPackageStartupMessages({
    library(BiocParallel)
    library(SingleCellExperiment)
    library(scDblFinder)
  })

  set.seed(random_state)
  sce <- SingleCellExperiment::SingleCellExperiment(
    assays = list(counts = counts),
    colData = obs
  )
  sce <- scDblFinder::scDblFinder(
    sce,
    BPPARAM = BiocParallel::SerialParam()
  )
  scores <- as.numeric(SummarizedExperiment::colData(sce)[["scDblFinder.score"]])
  predicted <- as.character(SummarizedExperiment::colData(sce)[["scDblFinder.class"]]) == "doublet"
} else if (method == "scds") {
  suppressPackageStartupMessages({
    library(SingleCellExperiment)
    library(scds)
  })

  set.seed(random_state)
  sce <- SingleCellExperiment::SingleCellExperiment(
    assays = list(counts = counts),
    colData = obs
  )
  sce <- scds::cxds_bcds_hybrid(sce)
  raw_scores <- SummarizedExperiment::colData(sce)[["hybrid_score"]]
  scores <- minmax_scale(raw_scores)
  predicted <- scores >= threshold
} else if (method == "DoubletFinder") {
  suppressPackageStartupMessages({
    library(DoubletFinder)
    library(Seurat)
  })

  set.seed(random_state)
  if (ncol(obs) > 0) {
    seu <- Seurat::CreateSeuratObject(counts = counts, meta.data = obs)
  } else {
    seu <- Seurat::CreateSeuratObject(counts = counts)
  }
  seu <- Seurat::NormalizeData(seu, verbose = FALSE)
  seu <- Seurat::FindVariableFeatures(seu, verbose = FALSE)
  seu <- Seurat::ScaleData(seu, verbose = FALSE)

  npcs <- min(20L, max(5L, ncol(seu) - 1L))
  dims <- seq_len(min(10L, npcs))
  seu <- Seurat::RunPCA(seu, npcs = npcs, verbose = FALSE)
  seu <- Seurat::FindNeighbors(seu, dims = dims, verbose = FALSE)
  seu <- Seurat::FindClusters(seu, resolution = 0.5, verbose = FALSE)

  nExp <- max(1L, round(expected_doublet_rate * ncol(seu)))
  seu <- DoubletFinder::doubletFinder(
    seu,
    PCs = dims,
    pN = 0.25,
    pK = 0.09,
    nExp = nExp,
    reuse.pANN = NULL,
    sct = FALSE
  )

  meta <- seu@meta.data
  score_col <- grep("^pANN", colnames(meta), value = TRUE)[1]
  class_col <- grep("DF.classifications", colnames(meta), value = TRUE)[1]
  raw_scores <- meta[[score_col]]
  scores <- minmax_scale(raw_scores)
  predicted <- as.character(meta[[class_col]]) == "Doublet"
} else {
  stop(sprintf("Unsupported R doublet method: %s", method))
}

result <- data.frame(
  cell_id = rownames(obs),
  doublet_score = as.numeric(scores),
  predicted_doublet = as.logical(predicted)
)
write.csv(result, output_path, row.names = FALSE)
