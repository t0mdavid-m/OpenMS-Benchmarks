# Benchmark Harness Contract Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-architect the OpenMS benchmark harness around a tight, tool-agnostic contract: each tool runs in its own container, a mounted script runs the tool *and self-scores*, emitting one `metrics.tsv` validated against a per-benchmark-type metric schema; the host becomes a thin orchestrator with no central results ledger.

**Architecture:** The host (`bench/`) only *materializes images* (build OpenMS from a git ref, pull external tools), *runs* each benchmark via `docker run` with three mounts (`/work` scripts ro, `/input` data ro, `/out` rw), *harvests* the container-written `metrics.tsv` + `error.log`, validates the metrics against the benchmark-type schema, and writes a host-owned `run.json` provenance sidecar. There is no append-only ledger: `results/runs/<openms-ref>/<tool>/<dataset>/` is the database and `aggregate.py` reconstructs comparisons on demand. All proteomics + scoring logic lives in mounted scripts under `scripts/`, run inside the container (Python installed on demand for the OpenMS image).

**Tech Stack:** Python 3.11+ (`uv`, stdlib `tomllib`, `PyYAML`, `pytest`), Docker, bash/awk + on-demand `python3` in-container.

## Global Constraints

- Python 3.11+; managed with `uv`; `tomllib` used directly (copy verbatim from existing repo conventions).
- **Tests require neither Docker nor network.** Docker-invoking code is covered only at the pure-function level. New logic must stay host-unit-testable. (verbatim invariant from `CLAUDE.md` → Testing.)
- **Never modify `OpenMS/`** except via `git fetch` / `git worktree`. It is the gitignored vendored checkout used as the build context source. `*.worktree/` dirs are transient per-build worktrees. (verbatim invariant.)
- **The harness never edits the branch's `Dockerfile`** and always builds the `tools-thirdparty` target. Python needed for in-container scoring is added by a derived layer or installed on demand by the run script — never by editing the branch Dockerfile. (verbatim invariant, extended per design decision #8.)
- `threads` is fixed (host config) for fair performance comparison. (verbatim invariant.)
- Cross-engine fairness for the OpenMS family stays structural: Trypsin, 2 missed cleavages, fixed Carbamidomethyl(C), variable Oxidation(M), 1% PSM FDR, MBR off, top-3 protein quant; only per-dataset tolerances vary. Enforced by the single ported `scripts/lib/common.sh`. (verbatim invariant from `CLAUDE.md` → Workflow plugin model.)
- The canonical in-container quant format is unchanged: TSV `precursor\tcharge\tprotein\tcondition\treplicate\tintensity`, condition values literal `A`/`B`.
- `metrics.tsv` format (NEW canonical contract): TSV with header `metric\tvalue\tunit`, one row per metric. `metric_value` is `%g`-formatted. This is the only host↔container result seam.

---

## File Structure (target end state)

**Host package `bench/` (thin orchestrator, host-only, NO proteomics logic):**
- `bench/__init__.py` — unchanged marker.
- `bench/__main__.py` — `raise SystemExit(main())`.
- `bench/cli.py` — REWRITE: `run` + `aggregate` subcommands; expands benchmark matrix; per-benchmark loop.
- `bench/config.py` — REWRITE: loads `config.toml` (host settings) + `images.yaml` + `benchmarks.yaml`; dataclasses `Config`, `ImageSpec`, `BenchmarkType`, `MetricSpec`, `Benchmark`.
- `bench/images.py` — NEW: `plan_image()` (pure) + `materialize_image()` (build OpenMS via `gitref`, or pull). Absorbs old `build.py`.
- `bench/runner.py` — NEW: `build_run_command()` (pure) + `run_benchmark()` (docker run, capture `error.log`, harvest `metrics.tsv`, write `run.json`). Replaces old `run.py`.
- `bench/validate.py` — NEW: parse `metrics.tsv`; validate rows against a `BenchmarkType` metric schema.
- `bench/aggregate.py` — NEW: walk `results/runs/**`, join `metrics.tsv` + `run.json`, emit a wide comparison TSV. Replaces `pivot.py`.
- `bench/gitref.py` — KEEP unchanged (`resolve_ref`, `checkout_worktree`); used by `images.py`.

**Mounted scripts `scripts/` (run in-container, Python host-unit-testable):**
- `scripts/lib/spec.py` — NEW: parse `/input/spec.yaml`; emit OpenMS `design.tsv`; emit shell `export`s.
- `scripts/lib/score.py` — NEW: ported `assign_species` + LFQ scorer; reads `quant.tsv` + spec; prints `metric\tvalue\tunit` rows.
- `scripts/lib/emit.sh` — NEW: `metrics_init`, `metric_emit`, `phase_start`/`phase_end` timing, cgroup peak reset/read.
- `scripts/lib/common.sh` — PORT of `workflows/common.sh`: builds DB, per-file search+prepare_ids, ProteomicsLFQ, quant.tsv, then **self-scores** → `metrics.tsv`.
- `scripts/lib/search-comet.sh`, `search-sage.sh`, `search-msgf.sh`, `search-prose.sh` — PORT verbatim from `workflows/lib/`.
- `scripts/openms/comet.sh`, `sage.sh`, `msgf.sh`, `comet-perc.sh`, `msgf-perc.sh`, `prose.sh` — PORT of the `workflows/lfq-*/run.sh` files (path fixups only).
- `scripts/fragpipe/fragpipe.sh` — NEW stub demonstrating an external self-scoring tool (documented, not asserted to run).

**Config + data:**
- `config.toml` / `config.example.toml` — host settings only (threads, paths, timeouts, openms checkout).
- `images.yaml` — per-image build/pull specs (the high-level OpenMS ref knob lives here).
- `benchmarks.yaml` — benchmark-types (metric schema + benchmark list).
- `data/proteobench_module2/spec.yaml` — example input-bundle spec (ported from the old `ground_truth.yaml`); user drops `.mzML` + `.fasta` beside it.

**Tooling + deletions:**
- `tools/fetch.py` — MOVE old `bench/fetch.py` here (optional out-of-band data prep; not in run path).
- DELETE: `bench/run.py`, `bench/build.py`, `bench/results.py`, `bench/workflows.py`, `bench/datasets.py`, `bench/species.py`, `bench/scoring/` (whole dir), `pivot.py`, `workflows/` (whole dir, after porting), `datasets/` (whole dir, after porting one to `data/`).

---

## Task 1: Config model (`bench/config.py`)

**Files:**
- Modify (rewrite): `bench/config.py`
- Create: `images.yaml`, `benchmarks.yaml`, `config.example.toml` (rewrite)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `@dataclass ImageSpec{ name:str, kind:str ("build"|"pull"), pull_ref:str|None, context:Path|None, dockerfile:str|None, target:str|None, ref:str|None, build_args:dict[str,str] }`
  - `@dataclass MetricSpec{ name:str, unit:str, required:bool }` (name may contain a single trailing `*` glob)
  - `@dataclass Benchmark{ name:str, type_name:str, image:str, run:str, input:Path }`
  - `@dataclass BenchmarkType{ name:str, metrics:list[MetricSpec], benchmarks:list[Benchmark] }`
  - `@dataclass Config{ openms_repo:Path, scripts_dir:Path, results_dir:Path, threads:int, build_timeout_s:int, run_timeout_s:int, images:dict[str,ImageSpec], benchmark_types:list[BenchmarkType] }`
  - `load_config(config_path:Path, images_path:Path, benchmarks_path:Path) -> Config`
  - `all_benchmarks(cfg:Config) -> list[tuple[BenchmarkType, Benchmark]]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from pathlib import Path
import textwrap
from bench.config import load_config, all_benchmarks


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_load_config_parses_images_and_benchmarks(tmp_path):
    cfg_toml = _write(tmp_path, "config.toml", """
        openms_repo = "OpenMS"
        threads = 4
        scripts_dir = "scripts"
        results_dir = "results"
    """)
    images = _write(tmp_path, "images.yaml", """
        openms:
          build:
            context: OpenMS
            dockerfile: dockerfiles/Dockerfile
            target: tools-thirdparty
            ref: a5f59d4
            build_args: {NUM_BUILD_CORES: 4}
        fragpipe:
          pull: fragpipe:v21
    """)
    benches = _write(tmp_path, "benchmarks.yaml", """
        benchmark_types:
          - name: DDA-LFQ
            metrics:
              - {name: mean_abs_error_overall, unit: log2, required: true}
              - {name: "median_log2_ratio_*", unit: log2, required: false}
              - {name: wall_clock_s, unit: s, required: true}
            benchmarks:
              - {name: comet, image: openms, run: openms/comet.sh, input: data/pb}
              - {name: fragpipe, image: fragpipe, run: fragpipe/fragpipe.sh, input: data/pb}
    """)
    cfg = load_config(cfg_toml, images, benches)
    assert cfg.threads == 4
    assert cfg.images["openms"].kind == "build"
    assert cfg.images["openms"].ref == "a5f59d4"
    assert cfg.images["openms"].build_args == {"NUM_BUILD_CORES": "4"}
    assert cfg.images["fragpipe"].kind == "pull"
    assert cfg.images["fragpipe"].pull_ref == "fragpipe:v21"

    pairs = all_benchmarks(cfg)
    assert [b.name for _, b in pairs] == ["comet", "fragpipe"]
    bt = pairs[0][0]
    assert bt.name == "DDA-LFQ"
    assert any(m.name == "median_log2_ratio_*" and not m.required for m in bt.metrics)
    assert pairs[1][1].image == "fragpipe"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError` (new symbols not defined yet).

- [ ] **Step 3: Write minimal implementation**

```python
# bench/config.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Author the real top-level config files**

Create `images.yaml`:
```yaml
# How each tool's container image is produced. The OpenMS `ref` is the high-level
# version knob; `--openms-ref` on the CLI overrides it for a sweep.
openms:
  build:
    context: OpenMS                  # vendored checkout = build-context source
    dockerfile: dockerfiles/Dockerfile
    target: tools-thirdparty
    ref: main
    build_args: {NUM_BUILD_CORES: 4}
# Example external tool (pulled, pinned). Uncomment when its script exists.
# fragpipe:
#   pull: fragpipe:v21
```

Create `benchmarks.yaml`:
```yaml
benchmark_types:
  - name: DDA-LFQ
    # Comparability contract: every DDA-LFQ benchmark must emit these.
    metrics:
      - {name: num_precursors_quantified, unit: count, required: true}
      - {name: num_proteins,               unit: count, required: true}
      - {name: mean_abs_error_overall,     unit: log2,  required: true}
      - {name: median_intra_condition_cv,  unit: ratio, required: true}
      - {name: wall_clock_s,               unit: s,     required: true}
      - {name: peak_mem_bytes,             unit: bytes, required: false}
      - {name: "median_log2_ratio_*",      unit: log2,  required: false}
      - {name: "mean_abs_error_*",         unit: log2,  required: false}
    benchmarks:
      - {name: comet, image: openms, run: openms/comet.sh, input: data/proteobench_module2}
      - {name: sage,  image: openms, run: openms/sage.sh,  input: data/proteobench_module2}
      - {name: msgf,  image: openms, run: openms/msgf.sh,  input: data/proteobench_module2}
      - {name: prose, image: openms, run: openms/prose.sh, input: data/proteobench_module2}
      - {name: comet-perc, image: openms, run: openms/comet-perc.sh, input: data/proteobench_module2}
      - {name: msgf-perc,  image: openms, run: openms/msgf-perc.sh,  input: data/proteobench_module2}
```

Rewrite `config.example.toml`:
```toml
# Copy to config.toml and fill in. config.toml is gitignored.
openms_repo   = "OpenMS"   # path to the OpenMS git checkout (build-context source)
threads       = 4          # fixed thread count for fair perf comparison
scripts_dir   = "scripts"  # mounted read-only at /work
results_dir   = "results"  # run tree written under results/runs/
build_timeout_s = 10800
run_timeout_s   = 7200
```

- [ ] **Step 6: Commit**

```bash
git add bench/config.py tests/test_config.py images.yaml benchmarks.yaml config.example.toml
git commit -m "refactor: config model for image specs + benchmark-type metric schema"
```

---

## Task 2: Image materialization (`bench/images.py`)

**Files:**
- Create: `bench/images.py`
- Test: `tests/test_images.py`

**Interfaces:**
- Consumes: `ImageSpec` (Task 1); `bench.gitref.resolve_ref`, `bench.gitref.checkout_worktree` (existing).
- Produces:
  - `image_tag(spec:ImageSpec, resolved_ref:str|None) -> str` — `openms-bench:<sha12>` for build, the literal `pull_ref` for pull.
  - `plan_build_command(spec:ImageSpec, worktree:Path, tag:str) -> list[str]` — the `docker build` argv (pure, testable).
  - `materialize_image(spec:ImageSpec, cfg:Config, ref_override:str|None) -> str` — returns the runnable image tag; builds (resolve→worktree→thirdparty→build, skip if exists) or pulls.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_images.py
from pathlib import Path
from bench.config import ImageSpec
from bench.images import image_tag, plan_build_command


def test_image_tag_pull_is_literal():
    spec = ImageSpec(name="fragpipe", kind="pull", pull_ref="fragpipe:v21")
    assert image_tag(spec, None) == "fragpipe:v21"


def test_image_tag_build_uses_sha12():
    spec = ImageSpec(name="openms", kind="build", ref="main")
    assert image_tag(spec, "a" * 40) == "openms-bench:" + "a" * 12


def test_plan_build_command_uses_target_and_build_args():
    spec = ImageSpec(name="openms", kind="build",
                     dockerfile="dockerfiles/Dockerfile",
                     target="tools-thirdparty",
                     build_args={"NUM_BUILD_CORES": "4"})
    cmd = plan_build_command(spec, Path("/wt"), "openms-bench:abc123abc123")
    assert "build" in cmd
    assert "--target" in cmd and "tools-thirdparty" in cmd
    assert "--build-arg" in cmd and "NUM_BUILD_CORES=4" in cmd
    assert "-t" in cmd and "openms-bench:abc123abc123" in cmd
    # Dockerfile path is under the worktree; context is the worktree.
    assert any(str(Path("/wt") / "dockerfiles" / "Dockerfile") in c for c in cmd)
    assert cmd[-1] == str(Path("/wt"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_images.py -v`
Expected: FAIL with `ImportError` (no `bench.images`).

- [ ] **Step 3: Write minimal implementation**

```python
# bench/images.py
import subprocess
from pathlib import Path

from bench.config import Config, ImageSpec
from bench.gitref import checkout_worktree, resolve_ref


def image_tag(spec: ImageSpec, resolved_ref: str | None) -> str:
    if spec.kind == "pull":
        return spec.pull_ref
    if not resolved_ref:
        raise ValueError("build image requires a resolved 40-char ref")
    return f"openms-bench:{resolved_ref[:12]}"


def plan_build_command(spec: ImageSpec, worktree: Path, tag: str) -> list[str]:
    dockerfile = worktree / spec.dockerfile
    cmd = ["docker", "build", "-f", str(dockerfile),
           "--target", spec.target]
    for k, v in spec.build_args.items():
        cmd += ["--build-arg", f"{k}={v}"]
    cmd += ["-t", tag, str(worktree)]
    return cmd


def _image_exists(tag: str) -> bool:
    res = subprocess.run(["docker", "image", "inspect", tag],
                         capture_output=True, text=True)
    return res.returncode == 0


def _ensure_thirdparty(worktree: Path) -> None:
    # The worktree .git is a linkfile invisible in-container, so the Dockerfile's
    # in-container submodule init fails; pre-populate THIRDPARTY on the host. It
    # also supplies the bundled engines (Sage, Comet, MS-GF+).
    subprocess.run(["git", "-C", str(worktree), "submodule", "update",
                    "--init", "--depth", "1", "THIRDPARTY"],
                   check=True, timeout=1800)


def materialize_image(spec: ImageSpec, cfg: Config,
                      ref_override: str | None) -> str:
    if spec.kind == "pull":
        if not _image_exists(spec.pull_ref):
            subprocess.run(["docker", "pull", spec.pull_ref], check=True,
                           timeout=cfg.build_timeout_s)
        return spec.pull_ref

    ref = ref_override or spec.ref
    sha = resolve_ref(cfg.openms_repo, ref)
    tag = image_tag(spec, sha)
    if _image_exists(tag):
        return tag
    worktree = checkout_worktree(cfg.openms_repo, sha, Path(f"{sha[:12]}.worktree"))
    if not (worktree / spec.dockerfile).exists():
        raise FileNotFoundError(
            f"{worktree / spec.dockerfile} missing — ref cannot be containerized")
    _ensure_thirdparty(worktree)
    try:
        subprocess.run(plan_build_command(spec, worktree, tag),
                       check=True, timeout=cfg.build_timeout_s)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"docker build exceeded {cfg.build_timeout_s}s for {tag}") from e
    return tag
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_images.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bench/images.py tests/test_images.py
git commit -m "feat: image materialization (build OpenMS @ref, pull external)"
```

---

## Task 3: Spec helper (`scripts/lib/spec.py`)

**Files:**
- Create: `scripts/lib/spec.py`
- Test: `tests/test_spec.py`

**Interfaces:**
- Produces (importable by file path; also a CLI):
  - `load_spec(path) -> dict`
  - `design_tsv(spec:dict) -> str` — OpenMS experimental design; spectra paths `/input/<file>`.
  - `shell_exports(spec:dict) -> str` — `export PREC_TOL_PPM=...`, `FRAG_TOL_DA`, `FASTA=/input/<fasta>`.
  - CLI: `python3 spec.py --design SPEC`, `python3 spec.py --shell SPEC` (prints to stdout).

**Note (testability):** `scripts/` is not a Python package; tests import these modules via `importlib.util.spec_from_file_location` so they run both in-container (`python3 /work/lib/spec.py`) and on the host under pytest.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_spec.py
import importlib.util
from pathlib import Path

SPEC_PY = Path(__file__).resolve().parents[1] / "scripts" / "lib" / "spec.py"


def _load_module(path):
    s = importlib.util.spec_from_file_location(path.stem, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


SPEC = {
    "fasta": "HYE.fasta",
    "tolerances": {"precursor_ppm": 10.0, "fragment_da": 0.02},
    "design": {"conditions": {
        "A": {1: ["a1.mzML"], 2: ["a2.mzML"]},
        "B": {1: ["b1.mzML"]},
    }},
}


def test_design_tsv_maps_runs_to_conditions():
    spec = _load_module(SPEC_PY)
    out = spec.design_tsv(SPEC)
    lines = out.strip().splitlines()
    assert lines[0].split("\t") == [
        "Fraction_Group", "Fraction", "Spectra_Filepath", "Label",
        "Sample", "MSstats_Condition", "MSstats_BioReplicate"]
    body = lines[1:]
    assert len(body) == 3                      # a1, a2, b1
    assert all(c.split("\t")[2].startswith("/input/") for c in body)
    assert any(c.split("\t")[5] == "A" and c.endswith("A_1") for c in body)
    assert any(c.split("\t")[5] == "B" and c.endswith("B_1") for c in body)


def test_shell_exports_emit_tolerances_and_fasta():
    spec = _load_module(SPEC_PY)
    exports = spec.shell_exports(SPEC)
    assert "export PREC_TOL_PPM=10.0" in exports
    assert "export FRAG_TOL_DA=0.02" in exports
    assert "export FASTA=/input/HYE.fasta" in exports
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_spec.py -v`
Expected: FAIL (`scripts/lib/spec.py` does not exist).

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/lib/spec.py
"""Parse /input/spec.yaml -> OpenMS design.tsv and shell exports.
Runs in-container (python3 /work/lib/spec.py ...) and is host-unit-tested."""
import sys

import yaml


def load_spec(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def design_tsv(spec) -> str:
    header = ("Fraction_Group\tFraction\tSpectra_Filepath\tLabel\t"
              "Sample\tMSstats_Condition\tMSstats_BioReplicate")
    rows = [header]
    i = 0
    conditions = spec["design"]["conditions"]
    for cond, reps in conditions.items():
        for rep, files in reps.items():
            for fname in files:
                i += 1
                path = f"/input/{fname}"
                rows.append(f"{i}\t1\t{path}\t1\t{i}\t{cond}\t{cond}_{rep}")
    return "\n".join(rows) + "\n"


def shell_exports(spec) -> str:
    tol = spec["tolerances"]
    lines = [
        f"export PREC_TOL_PPM={tol['precursor_ppm']}",
        f"export FRAG_TOL_DA={tol['fragment_da']}",
        f"export FASTA=/input/{spec['fasta']}",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    mode, path = sys.argv[1], sys.argv[2]
    spec = load_spec(path)
    if mode == "--design":
        sys.stdout.write(design_tsv(spec))
    elif mode == "--shell":
        sys.stdout.write(shell_exports(spec))
    else:
        sys.exit(f"unknown mode {mode!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_spec.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/spec.py tests/test_spec.py
git commit -m "feat: in-container spec.py (spec.yaml -> design.tsv + shell exports)"
```

---

## Task 4: Self-scoring scorer (`scripts/lib/score.py`)

**Files:**
- Create: `scripts/lib/score.py`
- Test: `tests/test_score.py`

**Interfaces:**
- Produces (importable by file path; also a CLI):
  - `assign_species(protein_header:str, exclude_regex:str, suffix_map:dict[str,str]) -> str|None` — ported verbatim from `bench/species.py`.
  - `score_quant(quant_rows:Iterable[dict], species_rule:dict, expected_log2:dict) -> list[tuple[str,float,str]]` — ported logic from `bench/scoring/lfq_quant.py`.
  - CLI: `python3 score.py QUANT_TSV SPEC_YAML` → prints `metric\tvalue\tunit` rows to stdout.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_score.py
import importlib.util
from pathlib import Path

SCORE_PY = Path(__file__).resolve().parents[1] / "scripts" / "lib" / "score.py"


def _load():
    s = importlib.util.spec_from_file_location("score", SCORE_PY)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_assign_species_exclude_then_suffix_then_catchall():
    sc = _load()
    sm = {"_HUMAN": "HUMAN", "": "OTHER"}
    assert sc.assign_species("Cont_x_HUMAN", "Cont_", sm) is None     # excluded
    assert sc.assign_species("P1_HUMAN", "Cont_", sm) == "HUMAN"       # suffix
    assert sc.assign_species("weird", "Cont_", sm) == "OTHER"          # catch-all


def test_score_quant_emits_expected_metrics():
    sc = _load()
    # one HUMAN precursor, A=2 reps B=2 reps, ratio log2(100/50)=1.0 vs expected 0.0
    rows = [
        {"precursor": "PEP", "charge": "2", "protein": "P_HUMAN",
         "condition": "A", "replicate": "1", "intensity": "100"},
        {"precursor": "PEP", "charge": "2", "protein": "P_HUMAN",
         "condition": "A", "replicate": "2", "intensity": "100"},
        {"precursor": "PEP", "charge": "2", "protein": "P_HUMAN",
         "condition": "B", "replicate": "1", "intensity": "50"},
        {"precursor": "PEP", "charge": "2", "protein": "P_HUMAN",
         "condition": "B", "replicate": "2", "intensity": "50"},
    ]
    metrics = dict((n, v) for n, v, _ in sc.score_quant(
        rows, {"exclude_regex": "Cont_", "suffix_map": {"_HUMAN": "HUMAN"}},
        {"HUMAN": 0.0}))
    assert metrics["num_precursors_quantified"] == 1.0
    assert abs(metrics["median_log2_ratio_HUMAN"] - 1.0) < 1e-9
    assert abs(metrics["mean_abs_error_HUMAN"] - 1.0) < 1e-9
    assert abs(metrics["mean_abs_error_overall"] - 1.0) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_score.py -v`
Expected: FAIL (`scripts/lib/score.py` does not exist).

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/lib/score.py
"""Self-scoring for the OpenMS family. Reads quant.tsv + spec.yaml, prints
`metric<TAB>value<TAB>unit` rows. Ported verbatim from bench/species.py and
bench/scoring/lfq_quant.py. Runs in-container; host-unit-tested."""
import csv
import math
import re
import statistics
import sys
from collections import defaultdict

import yaml


def assign_species(protein_header, exclude_regex, suffix_map):
    if exclude_regex and re.search(exclude_regex, protein_header):
        return None
    catch_all = None
    for suffix, species in suffix_map.items():
        if suffix == "":
            catch_all = species
            continue
        if protein_header.endswith(suffix):
            return species
    return catch_all


def score_quant(quant_rows, species_rule, expected_log2):
    exclude_regex = species_rule.get("exclude_regex", "")
    suffix_map = species_rule["suffix_map"]
    inten = defaultdict(lambda: defaultdict(list))
    prec_species = defaultdict(set)
    prec_proteins = defaultdict(set)

    for row in quant_rows:
        try:
            intensity = float(row["intensity"])
        except (ValueError, KeyError):
            continue
        if intensity <= 0 or math.isnan(intensity):
            continue
        sp = assign_species(row["protein"], exclude_regex, suffix_map)
        if sp is None:
            continue
        key = (row["precursor"], row["charge"])
        prec_species[key].add(sp)
        inten[key][row["condition"]].append(intensity)
        prec_proteins[key].add(row["protein"])

    per_species_log2 = defaultdict(list)
    cv_values = []
    n_quant = 0
    quantified_proteins = set()

    for key, conds in inten.items():
        species = prec_species[key]
        if len(species) != 1:
            continue
        sp = next(iter(species))
        a = conds.get("A", [])
        b = conds.get("B", [])
        if not a or not b:
            continue
        n_quant += 1
        quantified_proteins |= prec_proteins[key]
        per_species_log2[sp].append(math.log2(statistics.fmean(a) / statistics.fmean(b)))
        for reps in (a, b):
            if len(reps) >= 2:
                m = statistics.fmean(reps)
                if m > 0:
                    cv_values.append(statistics.pstdev(reps) / m)

    metrics = [
        ("num_precursors_quantified", float(n_quant), "count"),
        ("num_proteins", float(len(quantified_proteins)), "count"),
    ]
    all_errors = []
    for sp, observed in sorted(per_species_log2.items()):
        expected = float(expected_log2.get(sp, 0.0))
        errors = [abs(o - expected) for o in observed]
        all_errors.extend(errors)
        metrics.append((f"median_log2_ratio_{sp}", statistics.median(observed), "log2"))
        metrics.append((f"mean_abs_error_{sp}", statistics.fmean(errors), "log2"))
    metrics.append(("mean_abs_error_overall",
                    statistics.fmean(all_errors) if all_errors else 0.0, "log2"))
    metrics.append(("median_intra_condition_cv",
                    statistics.median(cv_values) if cv_values else 0.0, "ratio"))
    return metrics


if __name__ == "__main__":
    quant_tsv, spec_yaml = sys.argv[1], sys.argv[2]
    with open(spec_yaml, encoding="utf-8") as fh:
        spec = yaml.safe_load(fh)
    with open(quant_tsv, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    for name, value, unit in score_quant(rows, spec["species_rule"],
                                         spec["expected_log2_ratio"]):
        sys.stdout.write(f"{name}\t{value:g}\t{unit}\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_score.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/score.py tests/test_score.py
git commit -m "feat: in-container self-scoring score.py (ported from host scorer)"
```

---

## Task 5: Port the OpenMS chain to self-scoring mounted scripts

**Files:**
- Create: `scripts/lib/emit.sh`, `scripts/lib/common.sh`
- Create: `scripts/lib/search-comet.sh`, `search-sage.sh`, `search-msgf.sh`, `search-prose.sh`
- Create: `scripts/openms/comet.sh`, `sage.sh`, `msgf.sh`, `comet-perc.sh`, `msgf-perc.sh`, `prose.sh`
- Test: `tests/test_scripts_contract.py`

**Interfaces:**
- Consumes: `scripts/lib/spec.py`, `scripts/lib/score.py` (Tasks 3–4); env from the runner (Task 6): `THREADS`, `INPUT_DIR=/input`, `OUT_DIR=/out`, `WORK=/work`, `OPENMS_BIN`.
- Produces: each run script, when executed in the OpenMS image, writes `/out/quant.tsv`, `/out/design.tsv`, and `/out/metrics.tsv` (the contract output). `metrics.tsv` always contains `wall_clock_s` (tool phase only) and, when readable, `peak_mem_bytes`.

**Note:** bash isn't unit-tested without Docker; the test asserts the *contract wiring* (files exist, reference the right helpers/markers). Behavior is validated by the integration smoke run in Task 11.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scripts_contract.py
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def test_run_scripts_exist():
    for name in ["comet", "sage", "msgf", "comet-perc", "msgf-perc", "prose"]:
        assert (SCRIPTS / "openms" / f"{name}.sh").exists(), name


def test_common_sh_self_scores_and_provisions():
    body = (SCRIPTS / "lib" / "common.sh").read_text(encoding="utf-8")
    assert "spec.py" in body                       # builds design + exports from spec
    assert "score.py" in body                      # self-scores
    assert "metrics.tsv" in body                   # emits the contract file
    assert "ProteomicsLFQ" in body
    assert "quant.tsv" in body


def test_emit_sh_defines_metric_helpers():
    body = (SCRIPTS / "lib" / "emit.sh").read_text(encoding="utf-8")
    for fn in ["metrics_init", "metric_emit", "phase_start", "phase_end"]:
        assert fn in body, fn


def test_perc_variants_set_percolator_backend():
    for name in ["comet-perc", "msgf-perc"]:
        body = (SCRIPTS / "openms" / f"{name}.sh").read_text(encoding="utf-8")
        assert "FDR_BACKEND=percolator" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scripts_contract.py -v`
Expected: FAIL (scripts not created).

- [ ] **Step 3: Create `scripts/lib/emit.sh`**

```bash
#!/usr/bin/env bash
# Metric emission + measured-phase timing helpers. The MEASURED phase excludes
# on-demand provisioning, so wall_clock_s reflects the tool, not apt/pip.
METRICS_FILE="${OUT_DIR}/metrics.tsv"

metrics_init() { printf 'metric\tvalue\tunit\n' > "$METRICS_FILE"; }
metric_emit()  { printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$METRICS_FILE"; }

# Reset cgroup-v2 peak after provisioning so peak_mem reflects the tool phase.
phase_start() {
  echo 0 > /sys/fs/cgroup/memory.peak 2>/dev/null || true
  PHASE_T0="$(date +%s.%N)"
}
phase_end() {
  local t1; t1="$(date +%s.%N)"
  local wall; wall="$(awk "BEGIN{printf \"%.3f\", ${t1} - ${PHASE_T0}}")"
  metric_emit wall_clock_s "$wall" s
  local peak; peak="$(cat /sys/fs/cgroup/memory.peak 2>/dev/null || true)"
  if [ -n "$peak" ]; then metric_emit peak_mem_bytes "$peak" bytes; fi
}
```

- [ ] **Step 4: Create `scripts/lib/common.sh`** (ported DDA-LFQ chain, now self-scoring)

```bash
#!/usr/bin/env bash
# Shared DDA-LFQ chain. Sourced by each engine's run script, which must define
# run_search() consuming ($mzml $db $out_id). Self-contained: provisions Python,
# builds design + DB, searches, quantifies, then self-scores into metrics.tsv.
set -euo pipefail

: "${INPUT_DIR:?}" "${OUT_DIR:?}" "${THREADS:?}" "${WORK:?}"

source "${WORK}/lib/emit.sh"

# --- provisioning (NOT timed) -------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y -qq python3 python3-yaml >/dev/null
fi

SPEC="${INPUT_DIR}/spec.yaml"
DESIGN_TSV="${OUT_DIR}/design.tsv"
python3 "${WORK}/lib/spec.py" --design "$SPEC" > "$DESIGN_TSV"
eval "$(python3 "${WORK}/lib/spec.py" --shell "$SPEC")"   # PREC_TOL_PPM, FRAG_TOL_DA, FASTA
: "${PREC_TOL_PPM:?}" "${FRAG_TOL_DA:?}" "${FASTA:?}"

RUNWORK="${OUT_DIR}/work"
mkdir -p "$RUNWORK/idxml"

# Target+decoy database (input FASTA is target-only).
DB_FASTA="${RUNWORK}/db_with_decoys.fasta"
DecoyDatabase -in "$FASTA" -out "$DB_FASTA" \
  -decoy_string DECOY_ -decoy_string_position prefix -enzyme Trypsin

# prepare_ids backends (unchanged from the original common.sh).
prepare_ids_default() {
  local raw="$1" out="$2" b="${1%.idXML}"
  PeptideIndexer -in "$raw" -fasta "$DB_FASTA" -out "${b}.idx.idXML" \
    -decoy_string DECOY_ -decoy_string_position prefix -missing_decoy_action warn
  IDPosteriorErrorProbability -in "${b}.idx.idXML" -out "${b}.pep.idXML"
  FalseDiscoveryRate -in "${b}.pep.idXML" -out "${b}.fdr.idXML" \
    -PSM true -protein false -threads "$THREADS"
  IDFilter -in "${b}.fdr.idXML" -out "${b}.filt.idXML" -score:psm 0.01
  IDScoreSwitcher -in "${b}.filt.idXML" -out "$out" \
    -new_score "Posterior Error Probability_score" \
    -new_score_orientation lower_better -new_score_type "Posterior Error Probability"
}
prepare_ids_percolator() {
  local raw="$1" out="$2" b="${1%.idXML}"
  PeptideIndexer -in "$raw" -fasta "$DB_FASTA" -out "${b}.idx.idXML" \
    -decoy_string DECOY_ -decoy_string_position prefix -missing_decoy_action warn
  PSMFeatureExtractor -in "${b}.idx.idXML" -out "${b}.feat.idXML" -threads "$THREADS"
  PercolatorAdapter -in "${b}.feat.idXML" -out "${b}.perc.idXML" \
    -post_processing_tdc -score_type q-value -threads "$THREADS"
  IDFilter -in "${b}.perc.idXML" -out "${b}.filt.idXML" -score:psm 0.01
  IDScoreSwitcher -in "${b}.filt.idXML" -out "${b}.pep.idXML" \
    -new_score "MS:1001493" -new_score_orientation lower_better \
    -new_score_type "Posterior Error Probability"
  sed -E 's#<UserParam type="(int|float|intList|floatList|stringList)" name="[^"]*" value="[^"]*"/>##g' \
    "${b}.pep.idXML" > "$out"
}
if [[ "${FDR_BACKEND:-idpep}" == "percolator" ]]; then
  prepare_ids() { prepare_ids_percolator "$@"; }
elif ! declare -F prepare_ids >/dev/null; then
  prepare_ids() { prepare_ids_default "$@"; }
fi

# --- measured phase: search + quant ------------------------------------------
phase_start

FILTERED_IDS=()
QUANT_MZML=()
shopt -s nullglob
mzml_files=("$INPUT_DIR"/*.mzML)
if [ ${#mzml_files[@]} -eq 0 ]; then
  echo "ERROR: no .mzML files found in $INPUT_DIR" >&2
  exit 1
fi
for mz in "${mzml_files[@]}"; do
  base="$(basename "$mz" .mzML)"
  raw_id="$RUNWORK/idxml/${base}.idXML"
  run_search "$mz" "$DB_FASTA" "$raw_id"
  prepare_ids "$raw_id" "$RUNWORK/idxml/${base}.final.idXML"
  FILTERED_IDS+=("$RUNWORK/idxml/${base}.final.idXML")
  QUANT_MZML+=("$mz")
done

ProteomicsLFQ \
  -in "${QUANT_MZML[@]}" -ids "${FILTERED_IDS[@]}" \
  -design "$DESIGN_TSV" -fasta "$DB_FASTA" \
  -targeted_only true -ProteinQuantification:top:N 3 \
  -out "$RUNWORK/out.mzTab" -out_msstats "$RUNWORK/msstats.csv" \
  -threads "$THREADS"

awk -F',' 'NR==1{for(i=1;i<=NF;i++){h[$i]=i}
    print "precursor\tcharge\tprotein\tcondition\treplicate\tintensity"; next}
  {printf "%s\t%s\t%s\t%s\t%s\t%s\n",
     $h["PeptideSequence"], $h["PrecursorCharge"], $h["ProteinName"],
     $h["Condition"], $h["BioReplicate"], $h["Intensity"]}' \
  "$RUNWORK/msstats.csv" > "$OUT_DIR/quant.tsv"

phase_end   # emits wall_clock_s + peak_mem_bytes (tool phase only)

# --- scoring (after measured phase) ------------------------------------------
metrics_init
phase_end_metrics_tmp="${OUT_DIR}/.perf.tsv"
# Re-emit the perf rows captured above into metrics.tsv, then append quality rows.
# (phase_end appended to metrics.tsv already; metrics_init above reset it, so
#  capture-then-restore: simplest is to score first, then perf. Reorder below.)
```

> **Correction note for the implementer:** the ordering above must be: call `metrics_init` BEFORE `phase_start`, let `phase_end` append the perf rows, then append quality rows. Use this exact tail instead of the placeholder block:

```bash
# (place metrics_init BEFORE phase_start near the measured phase)
# After phase_end has appended perf rows, append quality rows:
python3 "${WORK}/lib/score.py" "$OUT_DIR/quant.tsv" "$SPEC" >> "$METRICS_FILE"
echo "wrote $METRICS_FILE" >&2
```

Final structure of the measured/scoring section (authoritative):
```bash
metrics_init          # header written once
phase_start           # reset peak, start clock
#   ... search loop + ProteomicsLFQ + quant.tsv ...
phase_end             # append wall_clock_s + peak_mem_bytes
python3 "${WORK}/lib/score.py" "$OUT_DIR/quant.tsv" "$SPEC" >> "$METRICS_FILE"
```

- [ ] **Step 5: Create the four engine libs** (ported verbatim from `workflows/lib/`, no changes)

`scripts/lib/search-comet.sh`:
```bash
#!/usr/bin/env bash
run_search() {
  local mzml="$1" db="$2" out_id="$3"
  CometAdapter -in "$mzml" -database "$db" -out "$out_id" \
    -enzyme Trypsin -missed_cleavages 2 \
    -fixed_modifications "Carbamidomethyl (C)" -variable_modifications "Oxidation (M)" \
    -precursor_mass_tolerance "${PREC_TOL_PPM}" -precursor_error_units ppm \
    -fragment_mass_tolerance "${FRAG_TOL_DA}" -fragment_error_units Da \
    -threads "$THREADS"
}
```

`scripts/lib/search-sage.sh`:
```bash
#!/usr/bin/env bash
run_search() {
  local mzml="$1" db="$2" out_id="$3"
  SageAdapter -in "$mzml" -database "$db" -out "$out_id" \
    -enzyme Trypsin -missed_cleavages 2 \
    -fixed_modifications "Carbamidomethyl (C)" -variable_modifications "Oxidation (M)" \
    -precursor_tol_left "-${PREC_TOL_PPM}" -precursor_tol_right "${PREC_TOL_PPM}" -precursor_tol_unit ppm \
    -fragment_tol_left "-${FRAG_TOL_DA}" -fragment_tol_right "${FRAG_TOL_DA}" -fragment_tol_unit Da \
    -threads "$THREADS"
}
```

`scripts/lib/search-msgf.sh`:
```bash
#!/usr/bin/env bash
run_search() {
  local mzml="$1" db="$2" out_id="$3"
  MSGFPlusAdapter -in "$mzml" -database "$db" -out "$out_id" \
    -executable MSGFPlus.jar -enzyme Trypsin/P -max_missed_cleavages 2 -instrument high_res \
    -fixed_modifications "Carbamidomethyl (C)" -variable_modifications "Oxidation (M)" \
    -precursor_mass_tolerance "${PREC_TOL_PPM}" -precursor_error_units ppm \
    -threads "$THREADS"
}
```

`scripts/lib/search-prose.sh`:
```bash
#!/usr/bin/env bash
run_search() {
  local mzml="$1" db="$2" out_id="$3"
  ProSE -in "$mzml" -database "$db" -out_idxml "$out_id" \
    -Search:enzyme Trypsin -Search:peptide:missed_cleavages 2 \
    -Search:modifications:fixed "Carbamidomethyl (C)" \
    -Search:modifications:variable "Oxidation (M)" \
    -Search:precursor:mass_tolerance_lower "${PREC_TOL_PPM}" \
    -Search:precursor:mass_tolerance_upper "${PREC_TOL_PPM}" -Search:precursor:mass_tolerance_unit ppm \
    -Search:fragment:mass_tolerance "${FRAG_TOL_DA}" -Search:fragment:mass_tolerance_unit Da \
    -Search:decoys auto -Search:decoy_prefix DECOY_ -Search:FDR:PSM 0.01 \
    -threads "$THREADS"
}
```

- [ ] **Step 6: Create the six run scripts** (ported; only the source paths change to `${WORK}/lib/...`)

`scripts/openms/comet.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
source "${WORK}/lib/search-comet.sh"
source "${WORK}/lib/common.sh"
```

`scripts/openms/sage.sh`, `scripts/openms/msgf.sh` — identical, swapping `search-comet.sh` for `search-sage.sh` / `search-msgf.sh`.

`scripts/openms/comet-perc.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
export FDR_BACKEND=percolator
source "${WORK}/lib/search-comet.sh"
source "${WORK}/lib/common.sh"
```

`scripts/openms/msgf-perc.sh` — identical, swapping in `search-msgf.sh`.

`scripts/openms/prose.sh` (keeps the prepare_ids override before sourcing common.sh):
```bash
#!/usr/bin/env bash
set -euo pipefail
source "${WORK}/lib/search-prose.sh"
prepare_ids() {
  local raw="$1" out="$2" b="${1%.idXML}"
  PeptideIndexer -in "$raw" -fasta "$DB_FASTA" -out "${b}.idx.idXML" \
    -decoy_string DECOY_ -decoy_string_position prefix -missing_decoy_action warn
  IDScoreSwitcher -in "${b}.idx.idXML" -out "${b}.s1.idXML" \
    -new_score "ln(hyperscore)_score" -new_score_orientation higher_better \
    -new_score_type hyperscore -old_score "ProSE_qvalue"
  IDScoreSwitcher -in "${b}.s1.idXML" -out "$out" \
    -new_score "ProSE_qvalue" -new_score_orientation lower_better \
    -new_score_type "Posterior Error Probability" -old_score "hyperscore"
}
source "${WORK}/lib/common.sh"
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/test_scripts_contract.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add scripts/
git commit -m "feat: port OpenMS chain to self-scoring mounted scripts (provision+score in-container)"
```

---

## Task 6: Runner (`bench/runner.py`)

**Files:**
- Create: `bench/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `Config`, `Benchmark` (Task 1); a materialized image tag (Task 2).
- Produces:
  - `_container_name(image_tag:str, benchmark:str) -> str`
  - `_host_path(p:Path) -> str`
  - `build_run_command(image_tag, scripts_dir, input_dir, out_dir, run_rel, threads, container_name) -> list[str]`
  - `@dataclass RunResult{ out_dir:Path, returncode:int, outer_wall_s:float }`
  - `run_benchmark(image_tag, benchmark, cfg, out_dir) -> RunResult` — docker run, stdout+stderr → `out_dir/error.log`, harvest happens in CLI.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_runner.py
from pathlib import Path
from bench.runner import _container_name, build_run_command


def test_container_name_is_sanitized():
    n = _container_name("openms-bench:abc123", "comet-perc")
    assert " " not in n and ":" not in n
    assert n.startswith("bench-")


def test_build_run_command_mounts_and_env():
    cmd = build_run_command(
        image_tag="openms-bench:abc123",
        scripts_dir=Path("/repo/scripts"),
        input_dir=Path("/repo/data/pb"),
        out_dir=Path("/repo/results/runs/abc123/comet/pb"),
        run_rel="openms/comet.sh",
        threads=4,
        container_name="bench-x",
    )
    joined = " ".join(cmd)
    assert "/work:ro" in joined and "/input:ro" in joined and ":/out" in joined
    assert "INPUT_DIR=/input" in cmd and "OUT_DIR=/out" in cmd and "WORK=/work" in cmd
    assert "THREADS=4" in cmd
    assert "bash /work/openms/comet.sh" in joined
    assert cmd[0:3] == ["docker", "run", "--rm"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_runner.py -v`
Expected: FAIL (`bench.runner` missing).

- [ ] **Step 3: Write minimal implementation**

```python
# bench/runner.py
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from bench.config import Benchmark, Config


def _host_path(p: Path) -> str:
    return str(Path(p).resolve()).replace("\\", "/")


def _container_name(image_tag: str, benchmark: str) -> str:
    raw = f"bench-{image_tag}-{benchmark}"
    return re.sub(r"[^A-Za-z0-9_.-]", "-", raw)[:120]


def build_run_command(image_tag, scripts_dir, input_dir, out_dir, run_rel,
                      threads, container_name) -> list[str]:
    inner = f"bash /work/{run_rel}"
    return [
        "docker", "run", "--rm", "--name", container_name,
        "-v", f"{_host_path(scripts_dir)}:/work:ro",
        "-v", f"{_host_path(input_dir)}:/input:ro",
        "-v", f"{_host_path(out_dir)}:/out",
        "-e", "INPUT_DIR=/input",
        "-e", "OUT_DIR=/out",
        "-e", "WORK=/work",
        "-e", "OPENMS_BIN=/opt/OpenMS/bin",
        "-e", f"THREADS={threads}",
        image_tag, "bash", "-c", inner,
    ]


@dataclass
class RunResult:
    out_dir: Path
    returncode: int
    outer_wall_s: float


def run_benchmark(image_tag: str, benchmark: Benchmark, cfg: Config,
                  out_dir: Path) -> RunResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = _container_name(image_tag, benchmark.name)
    cmd = build_run_command(image_tag, cfg.scripts_dir, benchmark.input, out_dir,
                            benchmark.run, cfg.threads, name)
    log_path = out_dir / "error.log"
    start = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        try:
            proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=cfg.run_timeout_s)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "kill", name], capture_output=True)
            return RunResult(out_dir, 124, time.monotonic() - start)
    return RunResult(out_dir, rc, time.monotonic() - start)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_runner.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bench/runner.py tests/test_runner.py
git commit -m "feat: thin docker-run runner (3 mounts, minimal env, error.log capture)"
```

---

## Task 7: Metric validation (`bench/validate.py`)

**Files:**
- Create: `bench/validate.py`
- Test: `tests/test_validate.py`

**Interfaces:**
- Consumes: `MetricSpec` (Task 1); a `metrics.tsv` written by a container (Task 5).
- Produces:
  - `parse_metrics_tsv(path:Path) -> list[tuple[str,float,str]]`
  - `@dataclass Validation{ ok:bool, missing:list[str], non_numeric:list[str], unknown:list[str] }`
  - `validate_metrics(rows:list[tuple[str,float,str]], specs:list[MetricSpec]) -> Validation` — `*`-suffixed spec names match by prefix; missing `required` → not ok; non-numeric value → not ok; names matching no spec → `unknown` (warning only, still ok).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_validate.py
from bench.config import MetricSpec
from bench.validate import validate_metrics, parse_metrics_tsv


SPECS = [
    MetricSpec("mean_abs_error_overall", "log2", True),
    MetricSpec("wall_clock_s", "s", True),
    MetricSpec("peak_mem_bytes", "bytes", False),
    MetricSpec("median_log2_ratio_*", "log2", False),
]


def test_valid_when_required_present_and_numeric():
    rows = [("mean_abs_error_overall", 0.1, "log2"),
            ("wall_clock_s", 12.0, "s"),
            ("median_log2_ratio_HUMAN", 0.0, "log2")]   # glob match
    v = validate_metrics(rows, SPECS)
    assert v.ok and not v.missing and not v.unknown


def test_missing_required_is_invalid():
    rows = [("wall_clock_s", 12.0, "s")]
    v = validate_metrics(rows, SPECS)
    assert not v.ok
    assert "mean_abs_error_overall" in v.missing


def test_unknown_metric_is_warning_not_failure():
    rows = [("mean_abs_error_overall", 0.1, "log2"),
            ("wall_clock_s", 12.0, "s"),
            ("surprise_metric", 1.0, "x")]
    v = validate_metrics(rows, SPECS)
    assert v.ok
    assert "surprise_metric" in v.unknown


def test_parse_metrics_tsv(tmp_path):
    p = tmp_path / "metrics.tsv"
    p.write_text("metric\tvalue\tunit\nwall_clock_s\t12.5\ts\n", encoding="utf-8")
    rows = parse_metrics_tsv(p)
    assert rows == [("wall_clock_s", 12.5, "s")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_validate.py -v`
Expected: FAIL (`bench.validate` missing).

- [ ] **Step 3: Write minimal implementation**

```python
# bench/validate.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_validate.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bench/validate.py tests/test_validate.py
git commit -m "feat: validate metrics.tsv against benchmark-type metric schema"
```

---

## Task 8: Aggregation (`bench/aggregate.py`, replaces `pivot.py`)

**Files:**
- Create: `bench/aggregate.py`
- Delete: `pivot.py`
- Test: `tests/test_aggregate.py`

**Interfaces:**
- Consumes: the `results/runs/<openms-ref>/<tool>/<dataset>/{metrics.tsv,run.json}` tree (Tasks 6 + 9).
- Produces:
  - `@dataclass RunRecord{ openms_ref:str, tool:str, dataset:str, metrics:dict[str,float], meta:dict }`
  - `collect_runs(results_root:Path) -> list[RunRecord]`
  - `to_wide(records:list[RunRecord]) -> tuple[list[str], list[list[str]]]` — header + rows; identity cols first (`openms_ref, tool, dataset`), then sorted union of metric names.
  - `write_wide(records, dest:Path) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_aggregate.py
import json
from pathlib import Path
from bench.aggregate import collect_runs, to_wide


def _make_run(root, ref, tool, ds, metrics):
    d = root / "runs" / ref / tool / ds
    d.mkdir(parents=True)
    lines = ["metric\tvalue\tunit"] + [f"{k}\t{v}\tu" for k, v in metrics.items()]
    (d / "metrics.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (d / "run.json").write_text(json.dumps({"tool": tool, "dataset": ds}), encoding="utf-8")


def test_collect_and_pivot(tmp_path):
    _make_run(tmp_path, "abc", "comet", "pb", {"mean_abs_error_overall": 0.1, "wall_clock_s": 10})
    _make_run(tmp_path, "abc", "sage", "pb", {"mean_abs_error_overall": 0.2, "wall_clock_s": 8})
    recs = collect_runs(tmp_path)
    assert len(recs) == 2
    header, rows = to_wide(recs)
    assert header[:3] == ["openms_ref", "tool", "dataset"]
    assert "mean_abs_error_overall" in header and "wall_clock_s" in header
    tools = {r[1] for r in rows}
    assert tools == {"comet", "sage"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_aggregate.py -v`
Expected: FAIL (`bench.aggregate` missing).

- [ ] **Step 3: Write minimal implementation**

```python
# bench/aggregate.py
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
```

- [ ] **Step 4: Run test to verify it passes; delete pivot.py**

Run: `uv run pytest tests/test_aggregate.py -v`
Expected: PASS.
Then: `git rm pivot.py`

- [ ] **Step 5: Commit**

```bash
git add bench/aggregate.py tests/test_aggregate.py
git commit -m "feat: aggregate run tree -> wide comparison table; drop pivot.py"
```

---

## Task 9: CLI rewrite (`bench/cli.py`)

**Files:**
- Modify (rewrite): `bench/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above. Writes `run.json` per run.
- Produces:
  - `build_run_json(*, openms_ref, benchmark, image_tag, threads, host_cpu, timestamp, returncode, outer_wall_s, validation) -> dict`
  - `out_dir_for(cfg, openms_ref, benchmark) -> Path` = `results/runs/<openms_ref>/<tool>/<dataset-name>`
  - `filter_benchmarks(pairs, *, types, names, images) -> list` (repeatable CLI filters)
  - `main(argv=None) -> int` — subcommands `run` and `aggregate`.

**Note:** `dataset-name` in the output path is the input folder's basename (`benchmark.input.name`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
from pathlib import Path
from bench.config import Benchmark, BenchmarkType
from bench.cli import build_run_json, out_dir_for, filter_benchmarks


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
        ok = True; missing = []; non_numeric = []; unknown = []
    rj = build_run_json(openms_ref="abc", benchmark=_bench("comet"),
                        image_tag="openms-bench:abc", threads=4, host_cpu="x86",
                        timestamp="2026-06-23T00:00:00Z", returncode=0,
                        outer_wall_s=42.0, validation=V)
    assert rj["openms_ref"] == "abc" and rj["tool"] == "comet"
    assert rj["dataset"] == "pb" and rj["image"] == "openms-bench:abc"
    assert rj["returncode"] == 0 and rj["metrics_valid"] is True
    assert rj["threads"] == 4 and rj["outer_wall_s"] == 42.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL (new symbols not defined).

- [ ] **Step 3: Write minimal implementation**

```python
# bench/cli.py
import argparse
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
            if metrics_file.exists():
                rows = parse_metrics_tsv(metrics_file)
            else:
                rows = []
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
        import csv
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bench/cli.py tests/test_cli.py
git commit -m "feat: CLI run+aggregate subcommands; per-run run.json provenance"
```

---

## Task 10: Delete dead host machinery; relocate fetch helper

**Files:**
- Delete: `bench/run.py`, `bench/build.py`, `bench/results.py`, `bench/workflows.py`, `bench/datasets.py`, `bench/species.py`, `bench/scoring/__init__.py`, `bench/scoring/lfq_quant.py`, `bench/scoring/perf_only.py` (whole `bench/scoring/`)
- Move: `bench/fetch.py` → `tools/fetch.py`
- Delete (after porting in Tasks 5 + 11): `workflows/` (whole dir), `datasets/` (whole dir)
- Delete obsolete tests: any `tests/test_workflows.py`, `tests/test_datasets.py`, `tests/test_results.py`, `tests/test_scoring*.py`, `tests/test_run.py`, `tests/test_build.py` that import deleted modules.

**Interfaces:** none (removal task). `tools/fetch.py` keeps its functions but its `bench.*` imports must be cut or inlined since `bench.datasets`/`bench.config` shapes changed; mark it clearly as a standalone out-of-band helper.

- [ ] **Step 1: Inventory what imports the doomed modules**

Run: `uv run python - <<'PY'`
```python
import subprocess
for mod in ["bench.run", "bench.build", "bench.results", "bench.workflows",
            "bench.datasets", "bench.species", "bench.scoring"]:
    print(mod, subprocess.run(["git", "grep", "-l", mod], capture_output=True, text=True).stdout)
PY
```
Expected: prints the files that still reference each — confirm they are only the deleted modules + their old tests (CLI/run already rewritten in Tasks 1–9).

- [ ] **Step 2: Remove the dead modules and obsolete tests**

```bash
git rm bench/run.py bench/build.py bench/results.py bench/workflows.py \
       bench/datasets.py bench/species.py
git rm -r bench/scoring
# remove only the obsolete tests that import the deleted modules:
git rm tests/test_workflows.py tests/test_datasets.py tests/test_results.py \
       tests/test_scoring.py tests/test_run.py tests/test_build.py 2>/dev/null || true
```

- [ ] **Step 3: Relocate the fetch helper as a standalone tool**

```bash
mkdir -p tools
git mv bench/fetch.py tools/fetch.py
```
Then edit `tools/fetch.py`: replace its `from bench.datasets import ...` / `from bench.config import ...` imports with a self-contained header that reads a manifest + URL directly (no `bench` import), and add a module docstring: `"""Out-of-band data prep helper. NOT in the run path. Fetches + sha-verifies + gunzips spectra/FASTA into an input-bundle folder for use by benchmarks.yaml `input:`."""`. Keep the pure helpers (`sha256_of`, gunzip, manifest read) intact.

- [ ] **Step 4: Verify the suite is green and nothing imports a deleted module**

Run: `uv run pytest -q`
Expected: PASS (only the new tests + any retained pure helper tests). No `ModuleNotFoundError`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: delete dead host machinery (scoring/datasets/results/workflows/run/build); move fetch.py to tools/"
```

---

## Task 11: Example input bundle, docs, integration smoke run

**Files:**
- Create: `data/proteobench_module2/spec.yaml`, `data/proteobench_module2/README.md`
- Delete: `datasets/` (after porting), `workflows/` (already ported in Task 5)
- Modify: `CLAUDE.md`, `docs/benchmark-overview.md`
- Test: `tests/test_example_spec.py`

**Interfaces:** the example `spec.yaml` is the reference for the bring-your-own input-bundle contract consumed by `scripts/lib/spec.py` (Task 3) and `scripts/lib/score.py` (Task 4).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_example_spec.py
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_YAML = ROOT / "data" / "proteobench_module2" / "spec.yaml"
SPEC_PY = ROOT / "scripts" / "lib" / "spec.py"
SCORE_PY = ROOT / "scripts" / "lib" / "score.py"


def _load(path, name):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


def test_example_spec_drives_helpers():
    spec_mod = _load(SPEC_PY, "spec")
    score_mod = _load(SCORE_PY, "score")
    spec = spec_mod.load_spec(SPEC_YAML)
    # design.tsv has 6 spectra (3 A + 3 B) + header
    design = spec_mod.design_tsv(spec).strip().splitlines()
    assert len(design) == 7
    # shell exports parse
    assert "PREC_TOL_PPM=10.0" in spec_mod.shell_exports(spec)
    # species rule + expected ratios present and usable
    assert spec["expected_log2_ratio"]["ECOLI"] == -2.0
    assert score_mod.assign_species("X_YEAST", spec["species_rule"]["exclude_regex"],
                                    spec["species_rule"]["suffix_map"]) == "YEAST"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_example_spec.py -v`
Expected: FAIL (`data/proteobench_module2/spec.yaml` missing).

- [ ] **Step 3: Author the example bundle spec (ported from `datasets/proteobench_module2/ground_truth.yaml`)**

Create `data/proteobench_module2/spec.yaml`:
```yaml
# Input-bundle contract. Drop the 6 .mzML files + the FASTA next to this file,
# then point a benchmark's `input:` at this folder. Filenames here are the
# DECOMPRESSED basenames (the harness no longer fetches/gunzips for you).
fasta: ProteoBenchFASTA_MixedSpecies_HYE.fasta
tolerances:
  precursor_ppm: 10.0
  fragment_da: 0.02
ratio_direction: A_over_B
species_rule:
  exclude_regex: "Cont_"
  suffix_map:
    _HUMAN: HUMAN
    _YEAST: YEAST
    _ECOLI: ECOLI
expected_log2_ratio:
  HUMAN: 0.0
  YEAST: 1.0
  ECOLI: -2.0
design:
  conditions:
    A:
      1: [LFQ_Orbitrap_DDA_Condition_A_Sample_Alpha_01.mzML]
      2: [LFQ_Orbitrap_DDA_Condition_A_Sample_Alpha_02.mzML]
      3: [LFQ_Orbitrap_DDA_Condition_A_Sample_Alpha_03.mzML]
    B:
      1: [LFQ_Orbitrap_DDA_Condition_B_Sample_Alpha_01.mzML]
      2: [LFQ_Orbitrap_DDA_Condition_B_Sample_Alpha_02.mzML]
      3: [LFQ_Orbitrap_DDA_Condition_B_Sample_Alpha_03.mzML]
```

Create `data/proteobench_module2/README.md` documenting where to obtain the 6 spectra + FASTA (point at `tools/fetch.py` and the old `datasets/proteobench_module2/manifest.tsv` checksums preserved in git history) and that files must be decompressed `.mzML`.

- [ ] **Step 4: Run test; then delete the old `datasets/` and `workflows/` trees**

Run: `uv run pytest tests/test_example_spec.py -v`
Expected: PASS.
Then:
```bash
git rm -r datasets workflows
```

- [ ] **Step 5: Update `CLAUDE.md` and `docs/benchmark-overview.md`**

Rewrite the architecture sections to describe: image specs (`images.yaml`, OpenMS builds @ref, externals pull); the `/work`+`/input`+`/out` mount contract with minimal env (`THREADS, INPUT_DIR, OUT_DIR, WORK, OPENMS_BIN`); self-scoring containers emitting `metrics.tsv`; the benchmark-type metric schema + validation; the no-ledger `results/runs/**` tree + `run.json` + `aggregate.py`; bring-your-own input bundles (`spec.yaml` layout) with `tools/fetch.py` as an optional prep helper. Remove references to `results.tsv`, `pivot.py`, `quant.tsv`-as-the-scoring-seam-on-host, `workflows/`, `datasets/`, `fetch_dataset`, `expand_matrix`/`applies_to`.

- [ ] **Step 6: Full suite + a real integration smoke run**

Run: `uv run pytest -q`
Expected: PASS.

Then a manual end-to-end smoke (Docker required; not part of CI). After placing the 6 `.mzML` + FASTA into `data/proteobench_module2/`:
```bash
cp config.example.toml config.toml
uv run python -m bench run --benchmark comet
```
Expected: builds/reuses the OpenMS image, runs the container, and writes
`results/runs/<ref>/comet/proteobench_module2/{metrics.tsv,error.log,run.json}`;
`metrics.tsv` contains `wall_clock_s`, `mean_abs_error_overall`, and per-species rows;
`run.json` shows `"metrics_valid": true`. Then:
```bash
uv run python -m bench aggregate
```
Expected: a wide TSV with `openms_ref, tool, dataset` + metric columns for the comet run.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: example input bundle + docs rewrite; remove datasets/ and workflows/"
```

---

## Self-Review

**1. Spec coverage** (decisions locked during grilling → task):
- Comparison axis = OpenMS vs external tools, heterogeneous self-contained images → Tasks 1, 2, 5 (fragpipe stub), 6.
- Per-image build/pull config; OpenMS builds Dockerfile @ref (high-level knob) → Tasks 1 (`images.yaml`), 2 (`materialize_image`), 9 (`--openms-ref`).
- Mounted run scripts (`/work`), not baked → Tasks 5, 6.
- Self-scoring per container; deps installed on demand → Tasks 4, 5 (`common.sh` provisions python3, calls `score.py`).
- Perf metrics measured by container, tool-phase scoped; host keeps coarse outer time → Task 5 (`emit.sh` `phase_start/phase_end`), Task 9 (`outer_wall_s` in `run.json`).
- Metric schema per benchmark-type + validation → Tasks 1, 7, 9.
- No ledger; tree of `metrics.tsv`/`error.log`/`run.json` + `aggregate.py` → Tasks 6, 8, 9.
- Bring-your-own mounted input folder; no fetch in run path; `spec.yaml` layout → Tasks 3, 6, 11; `tools/fetch.py` (Task 10) is the optional prep helper.
- Greenfield restructure in place; port logic, delete dead machinery → Tasks 4, 5 (ports), 10 (deletions).

**2. Placeholder scan:** the only deliberate prose-over-code spot is the `common.sh` ordering note in Task 5 Step 4 — it is followed by the *authoritative* final ordering block (`metrics_init` → `phase_start` → search/quant → `phase_end` → `score.py >> metrics.tsv`). Implementer must use that ordering; the earlier inline draft's trailing placeholder lines are explicitly superseded. No other TBD/TODO/"handle edge cases" placeholders.

**3. Type consistency:** `metrics.tsv` is `metric\tvalue\tunit` everywhere (`emit.sh`, `score.py` CLI, `parse_metrics_tsv`, `to_wide`). `MetricSpec`/`Benchmark`/`BenchmarkType`/`ImageSpec`/`Config` are defined once in Task 1 and consumed unchanged in Tasks 2, 6, 7, 9. `image_tag`/`materialize_image` signatures match between Tasks 2 and 9. `run_benchmark` returns `RunResult{out_dir,returncode,outer_wall_s}` (Task 6) and the CLI reads exactly those fields (Task 9). `out_dir_for` → `results/runs/<ref>/<tool>/<input.name>` matches `collect_runs`' `*/*/*/metrics.tsv` glob (Task 8).

## Open risks to watch during execution

- **cgroup peak reset** (`echo 0 > /sys/fs/cgroup/memory.peak`) is kernel-version dependent; if the host doesn't support reset, `peak_mem_bytes` includes provisioning. `peak_mem_bytes` is `required: false` so a missing/raw value never invalidates a run.
- **On-demand `apt-get`/`pip` needs network + root** inside the OpenMS image; pin versions if reproducibility of the scoring environment matters. External-tool images must already contain whatever their script invokes.
- **MS-GF+ ignores `FRAG_TOL_DA`** (`-instrument high_res`) — preserved from the original; a known cross-engine fairness gap, not introduced here.
