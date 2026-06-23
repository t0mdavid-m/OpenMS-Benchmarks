from pathlib import Path

from bench.cli import build_run_json, filter_benchmarks, out_dir_for
from bench.config import Benchmark, BenchmarkType


def _bench(name, image="openms"):
    return Benchmark(name=name, type_name="DDA-LFQ", image=image,
                     run=f"openms/{name}.sh", input=Path("data/pb"))


def test_out_dir_uses_ref_tool_dataset(tmp_path):
    class C:  # minimal stand-in
        results_dir = tmp_path / "results"
    p = out_dir_for(C, "abc123abc123", _bench("comet"))
    assert p == tmp_path / "results" / "runs" / "abc123abc123" / "comet" / "pb"


def test_filter_benchmarks_by_name_and_image():
    bt = BenchmarkType("DDA-LFQ", [], [])
    pairs = [(bt, _bench("comet")), (bt, _bench("sage")),
             (bt, _bench("fragpipe", image="fragpipe"))]
    assert [b.name for _, b in filter_benchmarks(pairs, types=None, names=["comet"], images=None)] == ["comet"]
    assert [b.name for _, b in filter_benchmarks(pairs, types=None, names=None, images=["fragpipe"])] == ["fragpipe"]


def test_build_run_json_has_provenance():
    class V:
        ok = True
        missing = []
        non_numeric = []
        unknown = []
    rj = build_run_json(openms_ref="abc", benchmark=_bench("comet"),
                        image_tag="openms-bench:abc", threads=4, host_cpu="x86",
                        timestamp="2026-06-23T00:00:00Z", returncode=0,
                        outer_wall_s=42.0, validation=V)
    assert rj["openms_ref"] == "abc" and rj["tool"] == "comet"
    assert rj["dataset"] == "pb" and rj["image"] == "openms-bench:abc"
    assert rj["returncode"] == 0 and rj["metrics_valid"] is True
    assert rj["threads"] == 4 and rj["outer_wall_s"] == 42.0
