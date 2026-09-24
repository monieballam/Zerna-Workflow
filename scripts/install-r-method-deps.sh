#!/usr/bin/env bash

set -euo pipefail

if [[ "${ZERNA_SKIP_R_DEPS:-0}" == "1" ]]; then
    echo "Skipping R method dependency installation because ZERNA_SKIP_R_DEPS=1"
    exit 0
fi

if ! command -v Rscript >/dev/null 2>&1; then
    echo "Error: Rscript is required to enable scDblFinder, DoubletFinder, scds, and SoupX."
    exit 1
fi

if command -v brew >/dev/null 2>&1; then
    brew install \
        cmake \
        libomp \
        tbb \
        fribidi \
        cairo \
        harfbuzz \
        freetype \
        pkgconf \
        libpng \
        libtiff \
        jpeg-turbo \
        webp
fi

if [[ -d /opt/homebrew/bin ]]; then
    export PATH="/opt/homebrew/bin:${PATH}"
fi

HOMEBREW_PKGCONFIG_DIRS=(
    "/opt/homebrew/lib/pkgconfig"
    "/opt/homebrew/opt/cairo/lib/pkgconfig"
    "/opt/homebrew/opt/harfbuzz/lib/pkgconfig"
    "/opt/homebrew/opt/freetype/lib/pkgconfig"
    "/opt/homebrew/opt/fribidi/lib/pkgconfig"
    "/opt/homebrew/opt/libpng/lib/pkgconfig"
    "/opt/homebrew/opt/libtiff/lib/pkgconfig"
    "/opt/homebrew/opt/jpeg-turbo/lib/pkgconfig"
    "/opt/homebrew/opt/webp/lib/pkgconfig"
)

for dir in "${HOMEBREW_PKGCONFIG_DIRS[@]}"; do
    if [[ -d "${dir}" ]]; then
        PKG_CONFIG_PATH="${dir}:${PKG_CONFIG_PATH:-}"
    fi
done
export PKG_CONFIG_PATH

Rscript -e "options(Ncpus=max(1L, parallel::detectCores()-1L)); \
install_if_missing <- function(pkgs, installer) { \
  missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly=TRUE)]; \
  if (length(missing) > 0) installer(missing); \
}; \
install_if_missing(c('BiocManager', 'remotes'), function(pkgs) install.packages(pkgs, repos='https://cloud.r-project.org')); \
install_if_missing( \
  c('Cairo', 'textshaping', 'ragg', 'ggrastr', 'SeuratObject', 'Seurat'), \
  function(pkgs) install.packages(pkgs, repos='https://cloud.r-project.org') \
); \
install_if_missing( \
  c('SingleCellExperiment', 'BiocParallel', 'scds', 'scater', 'scDblFinder'), \
  function(pkgs) BiocManager::install(pkgs, ask=FALSE, update=FALSE) \
); \
if (!requireNamespace('DoubletFinder', quietly=TRUE)) remotes::install_github('chris-mcginnis-ucsf/DoubletFinder', upgrade='never'); \
if (!requireNamespace('SoupX', quietly=TRUE)) remotes::install_github('constantAmateur/SoupX', upgrade='never')"
