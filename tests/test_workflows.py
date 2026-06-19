from pathlib import Path

from bench.datasets import load_dataset
from bench.workflows import discover_workflows, expand_matrix


def test_discover_finds_lfq_sage():
    wfs = discover_workflows(Path("workflows"))
    names = {w.name for w in wfs}
    assert "lfq-sage" in names
    sage = next(w for w in wfs if w.name == "lfq-sage")
    assert sage.engine == "sage"
    assert sage.type == "lfq-quant"
    assert sage.applies_to == "lfq"
    assert sage.run_script.name == "run.sh"


def test_matrix_pairs_by_category():
    wfs = discover_workflows(Path("workflows"))
    ds = load_dataset(Path("datasets/proteobench_module2"))  # category lfq
    pairs = expand_matrix(wfs, [ds])
    assert ("lfq-sage", "proteobench_module2") in {
        (w.name, d.name) for w, d in pairs
    }


def test_matrix_skips_mismatched_category(tmp_path: Path):
    from bench.workflows import Workflow
    from bench.datasets import Dataset, GroundTruth
    wf = Workflow(name="dia-x", engine="x", type="dia-quant",
                  applies_to="dia", run_script=tmp_path / "run.sh", dir=tmp_path)
    ds = load_dataset(Path("datasets/proteobench_module2"))  # lfq
    assert expand_matrix([wf], [ds]) == []
