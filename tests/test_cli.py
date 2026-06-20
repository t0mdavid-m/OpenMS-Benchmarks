from bench.cli import build_identity, filter_matrix
from bench.workflows import Workflow
from pathlib import Path


def _wf(name, applies="lfq"):
    return Workflow(name=name, engine="e", type="lfq-quant",
                    applies_to=applies, run_script=Path("r"), dir=Path("d"))


def test_build_identity_has_all_columns():
    idn = build_identity(sha="a" * 40, tag="develop", workflow=_wf("lfq-sage"),
                         dataset_name="proteobench_module2",
                         instrument="QExactiveHF", threads=4,
                         host_cpu="cpu", timestamp="2026-06-19T00:00:00Z")
    assert idn["openms_sha"] == "a" * 40
    assert idn["workflow"] == "lfq-sage"
    assert idn["instrument"] == "QExactiveHF"
    assert idn["threads"] == "4"


def test_filter_matrix_by_workflow_name():
    pairs = [(_wf("lfq-sage"), "d1"), (_wf("lfq-comet"), "d1")]
    kept = filter_matrix(pairs, workflows=["lfq-sage"], datasets=None,
                         instruments=None)
    assert [w.name for w, _ in kept] == ["lfq-sage"]
