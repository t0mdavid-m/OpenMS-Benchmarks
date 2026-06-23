import csv
from dataclasses import dataclass, field
from pathlib import Path

from bench.config import MetricSpec


def parse_metrics_tsv(path: Path) -> list[tuple[str, float, str]]:
    rows: list[tuple[str, float, str]] = []
    with Path(path).open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            rows.append((row["metric"], _to_float(row["value"]), row.get("unit", "")))
    return rows


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@dataclass
class Validation:
    ok: bool
    missing: list[str] = field(default_factory=list)
    non_numeric: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)


def _matches(name: str, spec_name: str) -> bool:
    if spec_name.endswith("*"):
        return name.startswith(spec_name[:-1])
    return name == spec_name


def validate_metrics(rows, specs: list[MetricSpec]) -> Validation:
    present = {n for n, _, _ in rows}
    missing = [s.name for s in specs
               if s.required and not any(_matches(n, s.name) for n in present)]
    non_numeric = [n for n, v, _ in rows if v is None]
    unknown = [n for n, _, _ in rows
               if not any(_matches(n, s.name) for s in specs)]
    ok = not missing and not non_numeric
    return Validation(ok=ok, missing=missing, non_numeric=non_numeric, unknown=unknown)
