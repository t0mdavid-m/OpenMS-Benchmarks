from pathlib import Path

from bench.datasets import load_dataset
from bench.scoring import get_scorer


def _write_quant(p: Path, rows: list[tuple]):
    lines = ["precursor\tcharge\tprotein\tcondition\treplicate\tintensity"]
    for r in rows:
        lines.append("\t".join(str(x) for x in r))
    (p / "quant.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_lfq_quant_perfect_human_ratio(tmp_path: Path):
    ds = load_dataset(Path("datasets/proteobench_module2"))
    # Human expected log2(A/B)=0 -> equal intensity in A and B.
    rows = []
    for rep in (1, 2, 3):
        rows.append(("PEPTIDEK", 2, "sp|P1|ALB_HUMAN", "A", rep, 1000))
        rows.append(("PEPTIDEK", 2, "sp|P1|ALB_HUMAN", "B", rep, 1000))
    _write_quant(tmp_path, rows)
    metrics = dict((m[0], m[1]) for m in get_scorer("lfq-quant")(tmp_path, ds))
    assert metrics["num_precursors_quantified"] == 1
    # observed log2(A/B)=0, expected 0 -> error 0
    assert abs(metrics["mean_abs_error_HUMAN"]) < 1e-9
    assert abs(metrics["median_log2_ratio_HUMAN"]) < 1e-9


def test_lfq_quant_excludes_contaminant(tmp_path: Path):
    ds = load_dataset(Path("datasets/proteobench_module2"))
    rows = []
    for rep in (1, 2, 3):
        rows.append(("CONTPEP", 2, "sp|Cont_P00722|BGAL_ECOLI", "A", rep, 500))
        rows.append(("CONTPEP", 2, "sp|Cont_P00722|BGAL_ECOLI", "B", rep, 500))
    _write_quant(tmp_path, rows)
    metrics = dict((m[0], m[1]) for m in get_scorer("lfq-quant")(tmp_path, ds))
    # Contaminant dropped -> nothing quantified.
    assert metrics["num_precursors_quantified"] == 0


def test_lfq_quant_yeast_ratio_error(tmp_path: Path):
    ds = load_dataset(Path("datasets/proteobench_module2"))
    # Yeast expected log2(A/B)=+1. Make observed A=2000,B=1000 -> log2=1 -> error 0.
    rows = []
    for rep in (1, 2, 3):
        rows.append(("YPEP", 2, "sp|P2|ADH1_YEAST", "A", rep, 2000))
        rows.append(("YPEP", 2, "sp|P2|ADH1_YEAST", "B", rep, 1000))
    _write_quant(tmp_path, rows)
    metrics = dict((m[0], m[1]) for m in get_scorer("lfq-quant")(tmp_path, ds))
    assert abs(metrics["mean_abs_error_YEAST"]) < 1e-9
