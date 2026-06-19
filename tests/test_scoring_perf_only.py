from pathlib import Path

from bench.datasets import load_dataset
from bench.scoring import get_scorer


def test_perf_only_returns_no_quality_metrics():
    ds = load_dataset(Path("datasets/proteobench_module2"))
    assert get_scorer("perf-only")(Path("."), ds) == []
