import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from bench.validate import parse_metrics_tsv


@dataclass
class RunRecord:
    openms_ref: str
    tool: str
    dataset: str
    metrics: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


def collect_runs(results_root: Path) -> list[RunRecord]:
    runs = Path(results_root) / "runs"
    out: list[RunRecord] = []
    if not runs.exists():
        return out
    for metrics_file in sorted(runs.glob("*/*/*/metrics.tsv")):
        ds_dir = metrics_file.parent
        tool_dir = ds_dir.parent
        ref_dir = tool_dir.parent
        metrics = {n: v for n, v, _ in parse_metrics_tsv(metrics_file)}
        meta = {}
        run_json = ds_dir / "run.json"
        if run_json.exists():
            meta = json.loads(run_json.read_text(encoding="utf-8"))
        out.append(RunRecord(ref_dir.name, tool_dir.name, ds_dir.name, metrics, meta))
    return out


def to_wide(records: list[RunRecord]):
    metric_names = sorted({m for r in records for m in r.metrics})
    header = ["openms_ref", "tool", "dataset"] + metric_names
    rows = []
    for r in records:
        row = [r.openms_ref, r.tool, r.dataset]
        row += ["%g" % r.metrics[m] if m in r.metrics else "" for m in metric_names]
        rows.append(row)
    return header, rows


def write_wide(records, dest: Path) -> None:
    header, rows = to_wide(records)
    with Path(dest).open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(header)
        w.writerows(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bench-aggregate")
    ap.add_argument("results_root", type=Path, nargs="?", default=Path("results"))
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    records = collect_runs(args.results_root)
    if args.out:
        write_wide(records, args.out)
    else:
        header, rows = to_wide(records)
        w = csv.writer(sys.stdout, delimiter="\t")
        w.writerow(header)
        w.writerows(rows)
    return 0
