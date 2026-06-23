import importlib.util
from pathlib import Path

SCORE_PY = Path(__file__).resolve().parents[1] / "scripts" / "lib" / "score.py"


def _load():
    s = importlib.util.spec_from_file_location("score", SCORE_PY)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_assign_species_exclude_then_suffix_then_catchall():
    sc = _load()
    sm = {"_HUMAN": "HUMAN", "": "OTHER"}
    assert sc.assign_species("Cont_x_HUMAN", "Cont_", sm) is None     # excluded
    assert sc.assign_species("P1_HUMAN", "Cont_", sm) == "HUMAN"       # suffix
    assert sc.assign_species("weird", "Cont_", sm) == "OTHER"          # catch-all


def test_score_quant_emits_expected_metrics():
    sc = _load()
    # one HUMAN precursor, A=2 reps B=2 reps, ratio log2(100/50)=1.0 vs expected 0.0
    rows = [
        {"precursor": "PEP", "charge": "2", "protein": "P_HUMAN",
         "condition": "A", "replicate": "1", "intensity": "100"},
        {"precursor": "PEP", "charge": "2", "protein": "P_HUMAN",
         "condition": "A", "replicate": "2", "intensity": "100"},
        {"precursor": "PEP", "charge": "2", "protein": "P_HUMAN",
         "condition": "B", "replicate": "1", "intensity": "50"},
        {"precursor": "PEP", "charge": "2", "protein": "P_HUMAN",
         "condition": "B", "replicate": "2", "intensity": "50"},
    ]
    metrics = dict((n, v) for n, v, _ in sc.score_quant(
        rows, {"exclude_regex": "Cont_", "suffix_map": {"_HUMAN": "HUMAN"}},
        {"HUMAN": 0.0}))
    assert metrics["num_precursors_quantified"] == 1.0
    assert abs(metrics["median_log2_ratio_HUMAN"] - 1.0) < 1e-9
    assert abs(metrics["mean_abs_error_HUMAN"] - 1.0) < 1e-9
    assert abs(metrics["mean_abs_error_overall"] - 1.0) < 1e-9
