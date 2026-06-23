import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_YAML = ROOT / "data" / "proteobench_module2" / "spec.yaml"
SPEC_PY = ROOT / "scripts" / "lib" / "spec.py"
SCORE_PY = ROOT / "scripts" / "lib" / "score.py"


def _load(path, name):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_example_spec_drives_helpers():
    spec_mod = _load(SPEC_PY, "spec")
    score_mod = _load(SCORE_PY, "score")
    spec = spec_mod.load_spec(SPEC_YAML)
    # design.tsv has 6 spectra (3 A + 3 B) + header
    design = spec_mod.design_tsv(spec).strip().splitlines()
    assert len(design) == 7
    # shell exports parse
    assert "PREC_TOL_PPM=10.0" in spec_mod.shell_exports(spec)
    # species rule + expected ratios present and usable
    assert spec["expected_log2_ratio"]["ECOLI"] == -2.0
    assert score_mod.assign_species("X_YEAST", spec["species_rule"]["exclude_regex"],
                                    spec["species_rule"]["suffix_map"]) == "YEAST"
