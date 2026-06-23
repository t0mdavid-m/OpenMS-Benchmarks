from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def test_run_scripts_exist():
    for name in ["comet", "sage", "msgf", "comet-perc", "msgf-perc", "prose"]:
        assert (SCRIPTS / "openms" / f"{name}.sh").exists(), name


def test_common_sh_self_scores_and_provisions():
    body = (SCRIPTS / "lib" / "common.sh").read_text(encoding="utf-8")
    assert "spec.py" in body                       # builds design + exports from spec
    assert "score.py" in body                      # self-scores
    assert "metrics.tsv" in body                   # emits the contract file
    assert "ProteomicsLFQ" in body
    assert "quant.tsv" in body


def test_emit_sh_defines_metric_helpers():
    body = (SCRIPTS / "lib" / "emit.sh").read_text(encoding="utf-8")
    for fn in ["metrics_init", "metric_emit", "phase_start", "phase_end"]:
        assert fn in body, fn


def test_perc_variants_set_percolator_backend():
    for name in ["comet-perc", "msgf-perc"]:
        body = (SCRIPTS / "openms" / f"{name}.sh").read_text(encoding="utf-8")
        assert "FDR_BACKEND=percolator" in body
