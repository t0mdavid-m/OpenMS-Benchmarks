from collections.abc import Callable
from pathlib import Path

from bench.datasets import Dataset
from bench.scoring import lfq_quant, perf_only

Metric = tuple[str, float, str]
Scorer = Callable[[Path, Dataset], list[Metric]]

_REGISTRY: dict[str, Scorer] = {
    "lfq-quant": lfq_quant.score,
    "perf-only": perf_only.score,
}


def get_scorer(type_: str) -> Scorer:
    if type_ not in _REGISTRY:
        raise KeyError(f"no scorer registered for type {type_!r}; "
                       f"known: {sorted(_REGISTRY)}")
    return _REGISTRY[type_]
