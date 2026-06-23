import importlib.util
from pathlib import Path

SPEC_PY = Path(__file__).resolve().parents[1] / "scripts" / "lib" / "spec.py"


def _load_module(path):
    s = importlib.util.spec_from_file_location(path.stem, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


SPEC = {
    "fasta": "HYE.fasta",
    "tolerances": {"precursor_ppm": 10.0, "fragment_da": 0.02},
    "design": {"conditions": {
        "A": {1: ["a1.mzML"], 2: ["a2.mzML"]},
        "B": {1: ["b1.mzML"]},
    }},
}


def test_design_tsv_maps_runs_to_conditions():
    spec = _load_module(SPEC_PY)
    out = spec.design_tsv(SPEC)
    lines = out.strip().splitlines()
    assert lines[0].split("\t") == [
        "Fraction_Group", "Fraction", "Spectra_Filepath", "Label",
        "Sample", "MSstats_Condition", "MSstats_BioReplicate"]
    body = lines[1:]
    assert len(body) == 3                      # a1, a2, b1
    assert all(c.split("\t")[2].startswith("/input/") for c in body)
    assert any(c.split("\t")[5] == "A" and c.endswith("A_1") for c in body)
    assert any(c.split("\t")[5] == "B" and c.endswith("B_1") for c in body)


def test_shell_exports_emit_tolerances_and_fasta():
    spec = _load_module(SPEC_PY)
    exports = spec.shell_exports(SPEC)
    assert "export PREC_TOL_PPM=10.0" in exports
    assert "export FRAG_TOL_DA=0.02" in exports
    assert "export FASTA=/input/HYE.fasta" in exports
