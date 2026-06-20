from dataclasses import dataclass
from pathlib import Path

import yaml

from bench.datasets import Dataset


@dataclass
class Workflow:
    name: str
    engine: str
    type: str
    applies_to: str
    run_script: Path
    dir: Path


def discover_workflows(root: Path) -> list[Workflow]:
    root = Path(root)
    out: list[Workflow] = []
    for meta_file in sorted(root.glob("*/meta.yaml")):
        run_script = meta_file.parent / "run.sh"
        if not run_script.exists():
            continue
        meta = yaml.safe_load(meta_file.read_text(encoding="utf-8"))
        out.append(Workflow(
            name=meta["name"],
            engine=meta["engine"],
            type=meta["type"],
            applies_to=meta["applies_to"],
            run_script=run_script,
            dir=meta_file.parent,
        ))
    return out


def expand_matrix(workflows: list[Workflow],
                  datasets: list[Dataset]) -> list[tuple[Workflow, Dataset]]:
    return [(w, d) for w in workflows for d in datasets
            if w.applies_to == d.category]
