"""Regression tests for metadata-aware dataset loading."""

from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import sparse
from scipy.io import mmwrite


def test_load_adata_merges_meta_txt_for_10x_uploads(tmp_path):
    from workflows.run_execution.activities import _load_adata

    obs_names = ["cell_a", "cell_b"]
    counts = sparse.coo_matrix(np.array([[1, 0], [0, 2], [3, 4]], dtype=np.int32))

    meta = pd.DataFrame(
        {
            "orig.ident": ["sample_1", "sample_2"],
            "CellType": ["T cell", "B cell"],
        },
        index=obs_names,
    )
    meta_path = tmp_path / "meta.txt"
    meta.to_csv(meta_path, sep="\t")

    matrix_path = tmp_path / "matrix.mtx"
    barcodes_path = tmp_path / "barcodes.tsv"
    genes_path = tmp_path / "genes.tsv"
    mmwrite(matrix_path, counts)
    barcodes_path.write_text("cell_a\ncell_b\n")
    genes_path.write_text("ENSG1\tGeneA\nENSG2\tGeneB\nENSG3\tGeneC\n")

    downloaded = [
        ("matrix.mtx", str(matrix_path)),
        ("barcodes.tsv", str(barcodes_path)),
        ("genes.tsv", str(genes_path)),
        ("meta.txt", str(meta_path)),
    ]

    loaded = _load_adata(str(tmp_path), downloaded)

    assert loaded.shape == (2, 3)
    assert list(loaded.var_names) == ["GeneA", "GeneB", "GeneC"]
    assert list(loaded.obs["orig.ident"]) == ["sample_1", "sample_2"]
    assert list(loaded.obs["CellType"]) == ["T cell", "B cell"]
    assert list(loaded.obs["condition"]) == ["sample_1", "sample_2"]


def test_load_adata_prefers_gene_expression_from_features_file(tmp_path):
    from workflows.run_execution.activities import _load_adata

    counts = sparse.coo_matrix(np.array([[1, 2], [5, 6]], dtype=np.int32))
    matrix_path = tmp_path / "matrix.mtx"
    barcodes_path = tmp_path / "barcodes.tsv"
    features_path = tmp_path / "features.tsv.gz"
    mmwrite(matrix_path, counts)
    barcodes_path.write_text("cell_a\ncell_b\n")

    feature_rows = pd.DataFrame(
        [
            ["ENSG1", "GeneA", "Gene Expression"],
            ["ADT1", "CD3", "Antibody Capture"],
        ]
    )
    feature_rows.to_csv(features_path, sep="\t", header=False, index=False, compression="gzip")

    loaded = _load_adata(
        str(tmp_path),
        [
            ("matrix.mtx", str(matrix_path)),
            ("barcodes.tsv", str(barcodes_path)),
            ("features.tsv.gz", str(features_path)),
        ],
    )

    assert loaded.shape == (2, 1)
    assert list(loaded.var_names) == ["GeneA"]
    assert loaded.X.dtype == np.int32


def test_load_adata_accepts_gzipped_10x_matrix_and_metadata(tmp_path):
    from workflows.run_execution.activities import _load_adata

    obs_names = ["cell_a", "cell_b"]
    counts = sparse.coo_matrix(np.array([[1, 0], [0, 2], [3, 4]], dtype=np.int32))

    meta = pd.DataFrame(
        {
            "orig.ident": ["sample_1", "sample_2"],
            "cluster": ["0", "1"],
        },
        index=obs_names,
    )
    meta_path = tmp_path / "meta.txt"
    meta.to_csv(meta_path, sep="\t")

    matrix_path = tmp_path / "matrix.mtx"
    matrix_gz_path = tmp_path / "matrix.mtx.gz"
    barcodes_path = tmp_path / "barcodes.tsv"
    genes_path = tmp_path / "genes.tsv"
    mmwrite(matrix_path, counts)
    with open(matrix_path, "rb") as source, gzip.open(matrix_gz_path, "wb") as target:
        target.write(source.read())
    barcodes_path.write_text("cell_a\ncell_b\n")
    genes_path.write_text("ENSG1\tGeneA\nENSG2\tGeneB\nENSG3\tGeneC\n")

    loaded = _load_adata(
        str(tmp_path),
        [
            ("matrix.mtx.gz", str(matrix_gz_path)),
            ("barcodes.tsv", str(barcodes_path)),
            ("genes.tsv", str(genes_path)),
            ("meta.txt", str(meta_path)),
        ],
    )

    assert loaded.shape == (2, 3)
    assert list(loaded.var_names) == ["GeneA", "GeneB", "GeneC"]
    assert list(loaded.obs["orig.ident"]) == ["sample_1", "sample_2"]
    assert list(loaded.obs["cluster"].astype(str)) == ["0", "1"]
    assert list(loaded.obs["condition"]) == ["sample_1", "sample_2"]


def _write_gene_by_cell_csv_gz(path: Path, barcodes: list[str]) -> None:
    lines = ["gene," + ",".join(barcodes)]
    lines.append("g1," + ",".join(["1.0"] * len(barcodes)))
    lines.append("g2," + ",".join(["2.0"] * len(barcodes)))
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def test_load_adata_reads_csv_gz_and_concatenates_two_matrices(tmp_path):
    from workflows.run_execution.activities import _load_adata

    p1 = tmp_path / "BMET1-Tumor.count.csv.gz"
    p2 = tmp_path / "BMET2-Distal.count.csv.gz"
    _write_gene_by_cell_csv_gz(p1, ["c1", "c2"])
    _write_gene_by_cell_csv_gz(p2, ["c3", "c4"])

    downloaded = [(p1.name, str(p1)), (p2.name, str(p2))]
    loaded = _load_adata(
        str(tmp_path),
        downloaded,
        expression_sample_labels=["Tumor", "Distal"],
    )
    assert loaded.n_obs == 4
    assert loaded.n_vars == 2
    assert loaded.obs["condition"].tolist() == ["Tumor", "Tumor", "Distal", "Distal"]
    assert loaded.obs["sample"].tolist() == ["Tumor", "Tumor", "Distal", "Distal"]
    assert loaded.obs["dataset_name"].tolist() == ["Tumor", "Tumor", "Distal", "Distal"]
    d = loaded.uns["zerna_concat_diagnostics"]
    assert d["n_parts"] == 2
    assert d["raw_dropped"] is False
    assert d["deduplicated_inputs"][0]["dataset"] == "Tumor"


def test_load_adata_per_file_upload_metadata_sets_dataset_name_and_sample(tmp_path):
    from workflows.run_execution.activities import _load_adata

    p1 = tmp_path / "a.count.csv.gz"
    p2 = tmp_path / "b.count.csv.gz"
    _write_gene_by_cell_csv_gz(p1, ["c1"])
    _write_gene_by_cell_csv_gz(p2, ["c2"])

    downloaded = [(p1.name, str(p1)), (p2.name, str(p2))]
    loaded = _load_adata(
        str(tmp_path),
        downloaded,
        expression_sample_labels=["fallbackA", "fallbackB"],
        per_file_upload_metadata=[
            {"dataset_name": "Donor1", "condition": "ctrl", "sample_id": "S1"},
            {"dataset_name": "Donor2", "condition": "treat", "sample_id": "S2"},
        ],
    )
    assert loaded.n_obs == 2
    assert loaded.obs["dataset_name"].tolist() == ["Donor1", "Donor2"]
    assert loaded.obs["sample"].tolist() == ["S1", "S2"]
    assert loaded.obs["condition"].tolist() == ["ctrl", "treat"]


def test_partition_10x_bundles_splits_prefixed_samples():
    from workflows.run_execution.activities import _partition_10x_bundles

    downloaded = [
        ("donor1_matrix.mtx", "/a/m1.mtx"),
        ("donor1_barcodes.tsv", "/a/b1.tsv"),
        ("donor2_matrix.mtx", "/b/m2.mtx"),
        ("donor2_barcodes.tsv", "/b/b2.tsv"),
    ]
    bundles = _partition_10x_bundles(downloaded)
    assert len(bundles) == 2
    assert {f for f, _ in bundles[0]} == {"donor1_matrix.mtx", "donor1_barcodes.tsv"}
    assert {f for f, _ in bundles[1]} == {"donor2_matrix.mtx", "donor2_barcodes.tsv"}


def test_partition_10x_bundles_groups_by_parent_folder_for_standard_names():
    from workflows.run_execution.activities import _partition_10x_bundles

    downloaded = [
        ("GSM5793824/matrix.mtx.gz", "/a/m1.mtx.gz"),
        ("GSM5793824/barcodes.tsv.gz", "/a/b1.tsv.gz"),
        ("GSM5793824/features.tsv.gz", "/a/f1.tsv.gz"),
        ("GSM5793831/matrix.mtx.gz", "/b/m2.mtx.gz"),
        ("GSM5793831/barcodes.tsv.gz", "/b/b2.tsv.gz"),
        ("GSM5793831/features.tsv.gz", "/b/f2.tsv.gz"),
    ]
    bundles = _partition_10x_bundles(downloaded)
    assert len(bundles) == 2
    g0 = {f for f, _ in bundles[0]}
    g1 = {f for f, _ in bundles[1]}
    assert g0 | g1 == {f for f, _ in downloaded}


def test_partition_10x_bundles_mixed_folder_and_filename_prefix():
    from workflows.run_execution.activities import _partition_10x_bundles

    downloaded = [
        ("GSM1/matrix.mtx", "/a/m1.mtx"),
        ("GSM1/barcodes.tsv", "/a/b1.tsv"),
        ("GSM1/genes.tsv", "/a/g1.tsv"),
        ("donorX_matrix.mtx", "/b/m2.mtx"),
        ("donorX_barcodes.tsv", "/b/b2.tsv"),
        ("donorX_genes.tsv", "/b/g2.tsv"),
    ]
    bundles = _partition_10x_bundles(downloaded)
    assert len(bundles) == 2


def test_partition_10x_bundles_raises_when_bare_duplicate_matrices_without_folder():
    from workflows.run_execution.activities import _partition_10x_bundles

    downloaded = [
        ("matrix.mtx.gz", "/a/m1.gz"),
        ("matrix.mtx.gz", "/b/m2.gz"),
        ("barcodes.tsv.gz", "/a/b1.gz"),
        ("barcodes.tsv.gz", "/b/b2.gz"),
        ("features.tsv.gz", "/a/f1.gz"),
        ("features.tsv.gz", "/b/f2.gz"),
    ]
    with pytest.raises(ValueError, match="same bundle group"):
        _partition_10x_bundles(downloaded)


def test_load_adata_multi_10x_standard_names_per_folder(tmp_path):
    from workflows.run_execution.activities import _load_adata

    for acc, barcodes in [("GSM5793824", ["a1", "a2"]), ("GSM5793831", ["b1"])]:
        n = len(barcodes)
        mat = np.arange(3 * n, dtype=np.int32).reshape(3, n) + (1 if acc == "GSM5793824" else 20)
        counts = sparse.coo_matrix(mat)
        d = tmp_path / acc
        d.mkdir()
        mtx = d / "matrix.mtx"
        bc = d / "barcodes.tsv"
        genes = d / "genes.tsv"
        mmwrite(mtx, counts)
        bc.write_text("\n".join(barcodes) + "\n")
        genes.write_text("ENSG1\tGeneA\nENSG2\tGeneB\nENSG3\tGeneC\n")

    downloaded = []
    for acc in ("GSM5793824", "GSM5793831"):
        base = tmp_path / acc
        downloaded.extend(
            [
                (f"{acc}/matrix.mtx", str(base / "matrix.mtx")),
                (f"{acc}/barcodes.tsv", str(base / "barcodes.tsv")),
                (f"{acc}/genes.tsv", str(base / "genes.tsv")),
            ]
        )

    loaded = _load_adata(
        str(tmp_path),
        downloaded,
        per_file_upload_metadata=[
            {"dataset_name": "S1", "sample_id": "S1", "condition": "c1"},
            {"dataset_name": "S2", "sample_id": "S2", "condition": "c2"},
        ],
    )
    assert loaded.n_obs == 3
    assert loaded.obs["sample"].tolist() == ["S1", "S1", "S2"]


def test_load_adata_multi_10x_incomplete_folder_raises(tmp_path):
    from workflows.run_execution.activities import _load_adata

    d1 = tmp_path / "GSM1"
    d1.mkdir()
    counts = sparse.coo_matrix(np.arange(6, dtype=np.int32).reshape(3, 2))
    mmwrite(d1 / "matrix.mtx", counts)
    (d1 / "barcodes.tsv").write_text("c1\nc2\n")

    d2 = tmp_path / "GSM2"
    d2.mkdir()
    mmwrite(d2 / "matrix.mtx", counts)
    (d2 / "barcodes.tsv").write_text("c1\nc2\n")
    (d2 / "genes.tsv").write_text("ENSG1\tGeneA\nENSG2\tGeneB\nENSG3\tGeneC\n")

    downloaded = [
        ("GSM1/matrix.mtx", str(d1 / "matrix.mtx")),
        ("GSM1/barcodes.tsv", str(d1 / "barcodes.tsv")),
        ("GSM2/matrix.mtx", str(d2 / "matrix.mtx")),
        ("GSM2/barcodes.tsv", str(d2 / "barcodes.tsv")),
        ("GSM2/genes.tsv", str(d2 / "genes.tsv")),
    ]
    with pytest.raises(
        ValueError, match="Could not load 10x bundle|missing matrix, barcodes, or features"
    ):
        _load_adata(
            str(tmp_path),
            downloaded,
            per_file_upload_metadata=[
                {"dataset_name": "A", "sample_id": "A", "condition": "x"},
                {"dataset_name": "B", "sample_id": "B", "condition": "y"},
            ],
        )


def test_load_adata_multi_h5ad_per_file_metadata(tmp_path):
    import anndata as ad

    from workflows.run_execution.activities import _load_adata

    g = ["g1", "g2", "g3"]
    a1 = ad.AnnData(X=np.eye(2, 3, dtype=np.float32), var=pd.DataFrame(index=g))
    a1.obs_names = ["c1", "c2"]
    p1 = tmp_path / "first.h5ad"
    p2 = tmp_path / "second.h5ad"
    a2 = ad.AnnData(X=np.ones((1, 3), dtype=np.float32), var=pd.DataFrame(index=g))
    a2.obs_names = ["c3"]
    a1.write_h5ad(p1)
    a2.write_h5ad(p2)

    loaded = _load_adata(
        str(tmp_path),
        [("first.h5ad", str(p1)), ("second.h5ad", str(p2))],
        per_file_upload_metadata=[
            {
                "dataset_name": "D1",
                "sample_id": "S1",
                "condition": "ctrl",
                "tissue": "lung",
                "platform": "10x",
            },
            {
                "dataset_name": "D2",
                "sample_id": "S2",
                "condition": "treat",
                "tissue": "spleen",
                "platform": "smartseq2",
            },
        ],
    )
    assert loaded.n_obs == 3
    assert loaded.obs["dataset_name"].tolist() == ["D1", "D1", "D2"]
    assert loaded.obs["sample"].tolist() == ["S1", "S1", "S2"]
    assert loaded.obs["condition"].tolist() == ["ctrl", "ctrl", "treat"]
    assert loaded.obs["tissue"].tolist() == ["lung", "lung", "spleen"]
    assert loaded.obs["platform"].tolist() == ["10x", "10x", "smartseq2"]
    assert loaded.obs_names[0].startswith("s0_S1_")
    assert loaded.obs_names[2].startswith("s1_S2_")


def test_load_adata_rejects_h5ad_when_memory_budget_is_too_small(tmp_path, monkeypatch):
    import anndata as ad

    import workflows.run_execution.activities as activities

    h5ad_path = tmp_path / "largeish.h5ad"
    ad.AnnData(X=np.eye(3, dtype=np.float32)).write_h5ad(h5ad_path)

    monkeypatch.setattr(activities, "_available_memory_bytes", lambda: 8 * 1024 * 1024 * 1024)
    monkeypatch.setattr(
        activities,
        "_estimate_h5ad_in_memory_requirement_bytes",
        lambda path: 10 * 1024 * 1024 * 1024,
    )

    with pytest.raises(ValueError, match="too large for safe in-memory H5AD loading"):
        activities._load_adata(str(tmp_path), [(h5ad_path.name, str(h5ad_path))])


def test_load_adata_multi_10x_bundles_per_file_metadata(tmp_path):
    from workflows.run_execution.activities import _load_adata

    for pre, barcodes in [("donor1", ["a1", "a2"]), ("donor2", ["b1"])]:
        n = len(barcodes)
        mat = np.arange(3 * n, dtype=np.int32).reshape(3, n) + (1 if pre == "donor1" else 10)
        counts = sparse.coo_matrix(mat)
        mtx = tmp_path / f"{pre}_matrix.mtx"
        bc = tmp_path / f"{pre}_barcodes.tsv"
        genes = tmp_path / f"{pre}_genes.tsv"
        mmwrite(mtx, counts)
        bc.write_text("\n".join(barcodes) + "\n")
        genes.write_text("ENSG1\tGeneA\nENSG2\tGeneB\nENSG3\tGeneC\n")

    downloaded = sorted(
        ((p.name, str(p)) for p in tmp_path.iterdir() if p.is_file()),
        key=lambda x: x[0],
    )
    loaded = _load_adata(
        str(tmp_path),
        downloaded,
        per_file_upload_metadata=[
            {"dataset_name": "Donor1", "sample_id": "S1", "condition": "ctrl"},
            {"dataset_name": "Donor2", "sample_id": "S2", "condition": "treat"},
        ],
    )
    assert loaded.n_obs == 3
    assert loaded.obs["dataset_name"].tolist() == ["Donor1", "Donor1", "Donor2"]
    assert loaded.obs["sample"].tolist() == ["S1", "S1", "S2"]
    assert loaded.obs["condition"].tolist() == ["ctrl", "ctrl", "treat"]


def test_load_adata_multi_h5ad_same_sample_id_still_concat_unique_obs(tmp_path):
    """Same sample_id across files must not produce duplicate obs_names (anndata.concat)."""
    import anndata as ad

    from workflows.run_execution.activities import _load_adata

    g = ["g1", "g2", "g3"]
    a1 = ad.AnnData(X=np.eye(1, 3, dtype=np.float32), var=pd.DataFrame(index=g))
    a1.obs_names = ["cell1"]
    a2 = ad.AnnData(X=np.ones((1, 3), dtype=np.float32), var=pd.DataFrame(index=g))
    a2.obs_names = ["cell1"]
    p1 = tmp_path / "a.h5ad"
    p2 = tmp_path / "b.h5ad"
    a1.write_h5ad(p1)
    a2.write_h5ad(p2)

    loaded = _load_adata(
        str(tmp_path),
        [("a.h5ad", str(p1)), ("b.h5ad", str(p2))],
        per_file_upload_metadata=[
            {"dataset_name": "A", "sample_id": "SAME", "condition": "x"},
            {"dataset_name": "B", "sample_id": "SAME", "condition": "y"},
        ],
    )
    assert loaded.n_obs == 2
    assert loaded.obs_names.is_unique
    assert loaded.obs_names[0].startswith("s0_SAME_")
    assert loaded.obs_names[1].startswith("s1_SAME_")


def test_load_adata_multi_h5ad_duplicate_var_and_raw_concat_ok(tmp_path):
    """ad.concat merges .var and .raw.var; duplicate indices must be uniquified."""
    import anndata as ad

    from workflows.run_execution.activities import _load_adata

    X = np.ones((2, 3), dtype=np.float32)
    var_dup = pd.DataFrame(index=["GAPDH", "GAPDH", "ACTB"])
    a1 = ad.AnnData(X.copy(), var=var_dup.copy())
    a1.raw = a1.copy()
    a2 = ad.AnnData(X.copy(), var=var_dup.copy())
    a2.raw = a2.copy()
    p1 = tmp_path / "dup_raw1.h5ad"
    p2 = tmp_path / "dup_raw2.h5ad"
    a1.write_h5ad(p1)
    a2.write_h5ad(p2)

    loaded = _load_adata(
        str(tmp_path),
        [("dup_raw1.h5ad", str(p1)), ("dup_raw2.h5ad", str(p2))],
    )
    assert loaded.n_obs == 4
    assert loaded.var_names.is_unique
    assert loaded.raw is not None
    assert loaded.raw.var_names.is_unique

    diag = loaded.uns.get("zerna_concat_diagnostics")
    assert isinstance(diag, dict)
    assert diag["n_parts"] == 2
    assert diag["final_attempt"] == 1
    assert diag["raw_dropped"] is False
    assert len(diag["attempts"]) >= 1
    assert diag["attempts"][-1]["status"] == "succeeded"
    dedup = {e["dataset"]: e for e in diag["deduplicated_inputs"]}
    assert dedup["dup_raw1.h5ad"]["var_names_deduplicated"] is True
    assert dedup["dup_raw1.h5ad"]["raw_var_deduplicated"] is True
    assert dedup["dup_raw2.h5ad"]["var_names_deduplicated"] is True
    assert dedup["dup_raw2.h5ad"]["raw_var_deduplicated"] is True


def test_load_adata_multi_h5ad_duplicate_var_symbols_concat_ok(tmp_path):
    """Duplicate gene symbols within a part break ad.concat unless var_names_make_unique."""
    import anndata as ad

    from workflows.run_execution.activities import _load_adata

    var_ix = pd.Index(["g1", "g1", "g2"])
    a1 = ad.AnnData(X=np.ones((1, 3), dtype=np.float32), var=pd.DataFrame(index=var_ix))
    a1.obs_names = ["c1"]
    a2 = ad.AnnData(X=np.ones((1, 3), dtype=np.float32), var=pd.DataFrame(index=["g1", "g1", "g2"]))
    a2.obs_names = ["c2"]
    p1 = tmp_path / "d1.h5ad"
    p2 = tmp_path / "d2.h5ad"
    a1.write_h5ad(p1)
    a2.write_h5ad(p2)

    loaded = _load_adata(str(tmp_path), [("d1.h5ad", str(p1)), ("d2.h5ad", str(p2))])
    assert loaded.n_obs == 2
    assert loaded.var_names.is_unique
    diag = loaded.uns["zerna_concat_diagnostics"]
    for row in diag["deduplicated_inputs"]:
        assert row["var_names_deduplicated"] is True
        assert row["raw_var_deduplicated"] is False


def test_concat_adata_axis0_multi_records_failed_attempt_when_merge_same_fails(monkeypatch):
    """First concat strategy fails; diagnostics list a failed attempt before success."""
    import anndata
    import anndata as ad

    from workflows.run_execution.activities import _concat_adata_axis0_multi

    g = ["g1", "g2"]
    a1 = ad.AnnData(X=np.ones((1, 2)), obs=pd.DataFrame(index=["x1"]), var=pd.DataFrame(index=g))
    a2 = ad.AnnData(X=np.ones((1, 2)), obs=pd.DataFrame(index=["x2"]), var=pd.DataFrame(index=g))
    real_concat = ad.concat

    def fake_concat(adatas, axis=0, join=None, merge=None):
        if merge == "same":
            raise ValueError("forced merge=same failure")
        return real_concat(adatas, axis=axis, join=join, merge=merge)

    monkeypatch.setattr(anndata, "concat", fake_concat)
    part_diags = [
        {
            "dataset": "A",
            "var_names_deduplicated": False,
            "raw_var_deduplicated": False,
            "had_raw": False,
        },
        {
            "dataset": "B",
            "var_names_deduplicated": False,
            "raw_var_deduplicated": False,
            "had_raw": False,
        },
    ]
    out = _concat_adata_axis0_multi([a1, a2], part_load_diagnostics=part_diags)
    d = out.uns["zerna_concat_diagnostics"]
    assert d["n_parts"] == 2
    assert d["raw_dropped"] is False
    assert d["final_attempt"] == 2
    att1 = next(a for a in d["attempts"] if a["attempt"] == 1)
    assert att1["status"] == "failed"
    assert att1["error_type"] == "ValueError"
    assert "merge=same" in att1["error_message"]


def test_concat_adata_axis0_multi_sets_raw_dropped_after_forced_raw_failures(monkeypatch):
    """When attempts 1–3 fail on objects with .raw, attempt 4 strips raw; diagnostics reflect it."""
    import anndata
    import anndata as ad

    from workflows.run_execution.activities import _concat_adata_axis0_multi

    g = ["g1", "g2"]
    a1 = ad.AnnData(X=np.ones((1, 2)), obs=pd.DataFrame(index=["x1"]), var=pd.DataFrame(index=g))
    a1.raw = a1.copy()
    a2 = ad.AnnData(X=np.ones((1, 2)), obs=pd.DataFrame(index=["x2"]), var=pd.DataFrame(index=g))
    a2.raw = a2.copy()
    real_concat = ad.concat

    def fake_concat(adatas, axis=0, join=None, merge=None):
        if merge == "same":
            raise RuntimeError("fail1")
        if join == "inner" and merge == "unique":
            raise RuntimeError("fail2")
        if join == "outer" and merge == "unique" and any(x.raw is not None for x in adatas):
            raise RuntimeError("fail3")
        return real_concat(adatas, axis=axis, join=join, merge=merge)

    monkeypatch.setattr(anndata, "concat", fake_concat)
    part_diags = [
        {
            "dataset": "P0",
            "var_names_deduplicated": False,
            "raw_var_deduplicated": False,
            "had_raw": True,
        },
        {
            "dataset": "P1",
            "var_names_deduplicated": False,
            "raw_var_deduplicated": False,
            "had_raw": True,
        },
    ]
    out = _concat_adata_axis0_multi([a1, a2], part_load_diagnostics=part_diags)
    d = out.uns["zerna_concat_diagnostics"]
    assert d["raw_dropped"] is True
    assert d["final_attempt"] == 4
    assert sum(1 for a in d["attempts"] if a["status"] == "failed") == 3
    assert d["attempts"][-1]["status"] == "succeeded"
    assert d["attempts"][-1]["keep_raw"] is False


def test_load_adata_multi_mtx_without_bundle_prefix_raises_with_per_file_manifest(tmp_path):
    from workflows.run_execution.activities import _load_adata

    c = sparse.coo_matrix(np.ones((2, 1), dtype=np.int32))
    mmwrite(tmp_path / "matrix1.mtx", c)
    mmwrite(tmp_path / "matrix2.mtx", c)
    (tmp_path / "barcodes.tsv").write_text("c1\n")
    (tmp_path / "genes.tsv").write_text("ENSG1\tG1\nENSG2\tG2\n")
    downloaded = [
        ("matrix1.mtx", str(tmp_path / "matrix1.mtx")),
        ("matrix2.mtx", str(tmp_path / "matrix2.mtx")),
        ("barcodes.tsv", str(tmp_path / "barcodes.tsv")),
        ("genes.tsv", str(tmp_path / "genes.tsv")),
    ]
    with pytest.raises(ValueError, match="Multiple 10x matrix files"):
        _load_adata(
            str(tmp_path),
            downloaded,
            per_file_upload_metadata=[{"dataset_name": "A"}, {"dataset_name": "B"}],
        )
