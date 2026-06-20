from pathlib import Path

from bench.datasets import Dataset

Metric = tuple[str, float, str]


def score(out_dir: Path, dataset: Dataset) -> list[Metric]:
    # Performance is measured by the harness for every workflow type;
    # this scorer adds no quality metrics.
    return []
