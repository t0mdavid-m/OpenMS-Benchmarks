import argparse
import csv
import datetime as dt
import json
import platform
import sys
import traceback
from pathlib import Path

from bench.aggregate import collect_runs, to_wide, write_wide
from bench.config import all_benchmarks, load_config
from bench.images import materialize_image
from bench.runner import run_benchmark
from bench.validate import parse_metrics_tsv, validate_metrics


def host_cpu() -> str:
    return platform.processor() or platform.machine() or "unknown"


def out_dir_for(cfg, openms_ref: str, benchmark) -> Path:
    return (Path(cfg.results_dir) / "runs" / openms_ref
            / benchmark.name / benchmark.input.name)


def filter_benchmarks(pairs, *, types, names, images):
    def keep(pair):
        bt, b = pair
        if types and bt.name not in types:
            return False
        if names and b.name not in names:
            return False
        if images and b.image not in images:
            return False
        return True
    return [p for p in pairs if keep(p)]


def build_run_json(*, openms_ref, benchmark, image_tag, threads, host_cpu,
                   timestamp, returncode, outer_wall_s, validation) -> dict:
    return {
        "run_timestamp": timestamp,
        "openms_ref": openms_ref,
        "tool": benchmark.name,
        "benchmark_type": benchmark.type_name,
        "dataset": benchmark.input.name,
        "image": image_tag,
        "threads": threads,
        "host_cpu": host_cpu,
        "returncode": returncode,
        "outer_wall_s": outer_wall_s,
        "metrics_valid": bool(validation.ok),
        "metrics_missing": list(validation.missing),
        "metrics_unknown": list(validation.unknown),
    }


def _cmd_run(args) -> int:
    cfg = load_config(args.config, args.images, args.benchmarks)
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hcpu = host_cpu()
    pairs = filter_benchmarks(all_benchmarks(cfg), types=args.type,
                              names=args.benchmark, images=args.image)
    if not pairs:
        print("no benchmarks matched the filters", file=sys.stderr)
        return 1

    # Resolve the OpenMS ref label for the output tree (ref override or image default).
    openms_spec = cfg.images.get("openms")
    openms_ref_label = args.openms_ref or (openms_spec.ref if openms_spec else "noref")

    images_cache: dict[str, str] = {}
    failures = 0
    type_by_name = {bt.name: bt for bt in cfg.benchmark_types}
    for bt, b in pairs:
        try:
            spec = cfg.images[b.image]
            if b.image not in images_cache:
                images_cache[b.image] = materialize_image(spec, cfg, args.openms_ref)
            image_tag = images_cache[b.image]
            out_dir = out_dir_for(cfg, openms_ref_label, b)
            result = run_benchmark(image_tag, b, cfg, out_dir)

            metrics_file = out_dir / "metrics.tsv"
            rows = parse_metrics_tsv(metrics_file) if metrics_file.exists() else []
            validation = validate_metrics(rows, type_by_name[b.type_name].metrics)

            run_json = build_run_json(
                openms_ref=openms_ref_label, benchmark=b, image_tag=image_tag,
                threads=cfg.threads, host_cpu=hcpu, timestamp=timestamp,
                returncode=result.returncode, outer_wall_s=result.outer_wall_s,
                validation=validation)
            (out_dir / "run.json").write_text(json.dumps(run_json, indent=2),
                                              encoding="utf-8")
            status = "ok" if (result.returncode == 0 and validation.ok) else "INVALID"
            print(f"[{b.name} x {b.input.name}] rc={result.returncode} "
                  f"valid={validation.ok} -> {status}", file=sys.stderr)
            if result.returncode != 0 or not validation.ok:
                failures += 1
        except Exception as e:
            failures += 1
            print(f"[{b.name}] FAILED: {type(e).__name__}: {e}", file=sys.stderr)
            traceback.print_exc()
            continue
    return 1 if failures else 0


def _cmd_aggregate(args) -> int:
    cfg = load_config(args.config, args.images, args.benchmarks)
    records = collect_runs(cfg.results_dir)
    if args.out:
        write_wide(records, args.out)
    else:
        header, rows = to_wide(records)
        w = csv.writer(sys.stdout, delimiter="\t")
        w.writerow(header)
        w.writerows(rows)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bench")
    ap.add_argument("--config", default="config.toml", type=Path)
    ap.add_argument("--images", default="images.yaml", type=Path)
    ap.add_argument("--benchmarks", default="benchmarks.yaml", type=Path)
    sub = ap.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run")
    run.add_argument("--openms-ref", default=None, help="override the OpenMS ref")
    run.add_argument("--type", action="append", default=None)
    run.add_argument("--benchmark", action="append", default=None)
    run.add_argument("--image", action="append", default=None)
    run.set_defaults(func=_cmd_run)

    agg = sub.add_parser("aggregate")
    agg.add_argument("--out", type=Path, default=None)
    agg.set_defaults(func=_cmd_aggregate)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
