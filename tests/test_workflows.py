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


# Percolator variants exist only for engines PSMFeatureExtractor supports (Comet, MSGF+).
# Sage and ProSE cannot be rescored by Percolator in this OpenMS image, so they have no
# -perc variant on purpose.
PERC_ENGINES = ("comet", "msgf")
NON_PERC_ENGINES = ("sage", "prose")


def test_percolator_variants_discovered():
    wfs = {w.name: w for w in discover_workflows(Path("workflows"))}
    for engine in PERC_ENGINES:
        name = f"lfq-{engine}-perc"
        assert name in wfs, f"{name} not discovered"
        assert wfs[name].engine == engine
        assert wfs[name].type == "lfq-quant"
        assert wfs[name].applies_to == "lfq"
    for engine in NON_PERC_ENGINES:
        assert f"lfq-{engine}-perc" not in wfs


def test_percolator_variants_select_backend_and_share_search():
    root = Path("workflows")
    for engine in PERC_ENGINES:
        perc = (root / f"lfq-{engine}-perc" / "run.sh").read_text(encoding="utf-8")
        assert "FDR_BACKEND=percolator" in perc
        # Both the plain and -perc variant source the same engine search lib (DRY).
        assert f"lib/search-{engine}.sh" in perc
        plain = (root / f"lfq-{engine}" / "run.sh").read_text(encoding="utf-8")
        assert f"lib/search-{engine}.sh" in plain


def test_matrix_skips_mismatched_category(tmp_path: Path):
    from bench.workflows import Workflow
    wf = Workflow(name="dia-x", engine="x", type="dia-quant",
                  applies_to="dia", run_script=tmp_path / "run.sh", dir=tmp_path)
    ds = load_dataset(Path("datasets/proteobench_module2"))  # lfq
    assert expand_matrix([wf], [ds]) == []
