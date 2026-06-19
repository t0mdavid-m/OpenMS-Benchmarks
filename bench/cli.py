import argparse
import datetime as dt
import platform
import sys
from pathlib import Path

from bench.build import build_image
from bench.config import load_config
from bench.datasets import Dataset, discover_datasets
from bench.fetch import fetch_dataset
from bench.gitref import checkout_worktree, resolve_ref
from bench.results import append_rows
from bench.run import run_workflow
from bench.scoring import get_scorer
from bench.workflows import Workflow, discover_workflows, expand_matrix


def host_cpu() -> str:
    return platform.processor() or platform.machine() or "unknown"


def build_identity(*, sha: str, tag: str, workflow: Workflow,
                   dataset_name: str, instrument: str, threads: int,
                   host_cpu: str, timestamp: str) -> dict[str, str]:
    return {
        "run_timestamp": timestamp,
        "openms_sha": sha,
        "openms_tag": tag,
        "workflow": workflow.name,
        "engine": workflow.engine,
        "dataset": dataset_name,
        "instrument": instrument,
        "threads": str(threads),
        "host_cpu": host_cpu,
    }


def filter_matrix(pairs, *, workflows, datasets, instruments):
    def keep(pair) -> bool:
        wf, ds = pair
        ds_name = ds if isinstance(ds, str) else ds.name
        ds_inst = "" if isinstance(ds, str) else ds.instrument
        if workflows and wf.name not in workflows:
            return False
        if datasets and ds_name not in datasets:
            return False
        if instruments and ds_inst not in instruments:
            return False
        return True
    return [p for p in pairs if keep(p)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench")
    ap.add_argument("--ref", required=True, help="branch name or SHA")
    ap.add_argument("--config", default="config.toml", type=Path)
    ap.add_argument("--workflow", action="append", default=None)
    ap.add_argument("--dataset", action="append", default=None)
    ap.add_argument("--instrument", action="append", default=None)
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    sha = resolve_ref(cfg.openms_repo, args.ref)
    tag = args.ref
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hcpu = host_cpu()

    worktree = checkout_worktree(cfg.openms_repo, sha,
                                 Path(f"{sha[:12]}.worktree"))
    image = build_image(worktree, sha, cfg.threads)

    workflows = discover_workflows(cfg.workflows_dir)
    datasets = discover_datasets(cfg.datasets_dir)
    pairs = filter_matrix(expand_matrix(workflows, datasets),
                          workflows=args.workflow, datasets=args.dataset,
                          instruments=args.instrument)

    if not pairs:
        print("no (workflow, dataset) pairs matched the filters", file=sys.stderr)
        return 1

    fetched: dict[str, Path] = {}
    for wf, ds in pairs:
        if ds.name not in fetched:
            fetched[ds.name] = fetch_dataset(ds, cfg)
        data_dir = fetched[ds.name]
        out_dir = Path("results") / "runs" / sha[:12] / wf.name / ds.name
        result = run_workflow(image, wf, ds, data_dir, out_dir, cfg)
        identity = build_identity(sha=sha, tag=tag, workflow=wf,
                                  dataset_name=ds.name, instrument=ds.instrument,
                                  threads=cfg.threads, host_cpu=hcpu,
                                  timestamp=timestamp)
        metrics = []
        if result.returncode == 0:
            metrics = list(get_scorer(wf.type)(out_dir, ds))
        metrics.append(("wall_clock_s", result.wall_clock_s, "s"))
        if result.peak_mem_bytes is not None:
            metrics.append(("peak_container_mem_bytes",
                            result.peak_mem_bytes, "bytes"))
        metrics.append(("workflow_returncode", float(result.returncode), "code"))
        append_rows(cfg.results_tsv, identity, metrics)
        print(f"[{wf.name} x {ds.name}] rc={result.returncode} "
              f"wall={result.wall_clock_s:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
