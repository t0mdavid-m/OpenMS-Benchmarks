import json

from bench.aggregate import collect_runs, to_wide


def _make_run(root, ref, tool, ds, metrics):
    d = root / "runs" / ref / tool / ds
    d.mkdir(parents=True)
    lines = ["metric\tvalue\tunit"] + [f"{k}\t{v}\tu" for k, v in metrics.items()]
    (d / "metrics.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (d / "run.json").write_text(json.dumps({"tool": tool, "dataset": ds}), encoding="utf-8")


def test_collect_and_pivot(tmp_path):
    _make_run(tmp_path, "abc", "comet", "pb", {"mean_abs_error_overall": 0.1, "wall_clock_s": 10})
    _make_run(tmp_path, "abc", "sage", "pb", {"mean_abs_error_overall": 0.2, "wall_clock_s": 8})
    recs = collect_runs(tmp_path)
    assert len(recs) == 2
    header, rows = to_wide(recs)
    assert header[:3] == ["openms_ref", "tool", "dataset"]
    assert "mean_abs_error_overall" in header and "wall_clock_s" in header
    tools = {r[1] for r in rows}
    assert tools == {"comet", "sage"}


def test_collect_runs_empty_tree(tmp_path):
    assert collect_runs(tmp_path) == []
