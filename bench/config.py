import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ImageSpec:
    name: str
    kind: str  # "build" | "pull"
    pull_ref: str | None = None
    context: Path | None = None
    dockerfile: str | None = None
    target: str | None = None
    ref: str | None = None
    build_args: dict[str, str] = field(default_factory=dict)


@dataclass
class MetricSpec:
    name: str
    unit: str
    required: bool


@dataclass
class Benchmark:
    name: str
    type_name: str
    image: str
    run: str
    input: Path


@dataclass
class BenchmarkType:
    name: str
    metrics: list[MetricSpec]
    benchmarks: list[Benchmark]


@dataclass
class Config:
    openms_repo: Path
    scripts_dir: Path
    results_dir: Path
    threads: int
    build_timeout_s: int
    run_timeout_s: int
    images: dict[str, ImageSpec]
    benchmark_types: list[BenchmarkType]


def _load_images(path: Path) -> dict[str, ImageSpec]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out: dict[str, ImageSpec] = {}
    for name, spec in raw.items():
        if "build" in spec:
            b = spec["build"]
            out[name] = ImageSpec(
                name=name, kind="build",
                context=Path(b["context"]),
                dockerfile=b["dockerfile"],
                target=b["target"],
                ref=str(b["ref"]),
                build_args={k: str(v) for k, v in b.get("build_args", {}).items()},
            )
        elif "pull" in spec:
            out[name] = ImageSpec(name=name, kind="pull", pull_ref=str(spec["pull"]))
        else:
            raise ValueError(f"image {name!r} must have a 'build' or 'pull' key")
    return out


def _load_benchmarks(path: Path) -> list[BenchmarkType]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out: list[BenchmarkType] = []
    for bt in raw.get("benchmark_types", []):
        metrics = [MetricSpec(name=m["name"], unit=m.get("unit", ""),
                              required=bool(m.get("required", False)))
                   for m in bt.get("metrics", [])]
        benches = [Benchmark(name=b["name"], type_name=bt["name"], image=b["image"],
                            run=b["run"], input=Path(b["input"]))
                   for b in bt.get("benchmarks", [])]
        out.append(BenchmarkType(name=bt["name"], metrics=metrics, benchmarks=benches))
    return out


def load_config(config_path: Path, images_path: Path,
                benchmarks_path: Path) -> Config:
    with Path(config_path).open("rb") as fh:
        data = tomllib.load(fh)
    root = Path(config_path).resolve().parent
    return Config(
        openms_repo=Path(data.get("openms_repo", "OpenMS")),
        scripts_dir=Path(data.get("scripts_dir", root / "scripts")),
        results_dir=Path(data.get("results_dir", root / "results")),
        threads=int(data.get("threads", 4)),
        build_timeout_s=int(data.get("build_timeout_s", 10800)),
        run_timeout_s=int(data.get("run_timeout_s", 7200)),
        images=_load_images(images_path),
        benchmark_types=_load_benchmarks(benchmarks_path),
    )


def all_benchmarks(cfg: Config) -> list[tuple[BenchmarkType, Benchmark]]:
    return [(bt, b) for bt in cfg.benchmark_types for b in bt.benchmarks]
