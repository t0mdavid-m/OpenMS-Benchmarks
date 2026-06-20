from pathlib import Path

from bench.datasets import load_dataset


def test_load_proteobench_module2():
    ds = load_dataset(Path("datasets/proteobench_module2"))
    assert ds.name == "proteobench_module2"
    assert ds.category == "lfq"
    assert ds.instrument == "QExactiveHF"
    assert len(ds.spectra()) == 6
    assert ds.fasta().filename == "ProteoBenchFASTA_MixedSpecies_HYE.fasta"
    assert ds.fasta().sha256.startswith("d9ac434d")
    assert ds.ground_truth.expected_log2["YEAST"] == 1.0
    assert ds.ground_truth.expected_log2["ECOLI"] == -2.0
    assert ds.ground_truth.expected_log2["HUMAN"] == 0.0
    assert ds.ground_truth.exclude_regex == "Cont_"
    a_files = ds.ground_truth.conditions["A"]
    assert len(a_files) == 3


def test_http_url_and_rsync_path_built_from_layout():
    ds = load_dataset(Path("datasets/proteobench_module2"))
    fasta = ds.fasta()
    assert fasta.http_url.endswith(
        "lfq/QExactiveHF/ProteoBench_Module_2/"
        "ProteoBenchFASTA_MixedSpecies_HYE.fasta"
    )
    assert fasta.rsync_path.startswith("/benchmarks/pride-benchmarks/lfq/QExactiveHF/")
