# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A controlled benchmark harness that compares **OpenMS against other proteomics tools** (and OpenMS-vs-OpenMS) on a shared task. Each tool runs in **its own container**; a **mounted script runs the tool and self-scores**, emitting one `metrics.tsv`. The host is a thin orchestrator with **no proteomics or scoring logic** and **no central results ledger** — `results/runs/<openms-ref>/<tool>/<dataset>/` is the database, reconstructed into comparisons on demand.

The OpenMS image is *built from a git ref* (the high-level version knob in `images.yaml`); external tools are *pulled* by pinned tag. Comparing OpenMS versions = bump the ref.

Two design records: `docs/superpowers/plans/2026-06-23-benchmark-harness-contract-refactor.md` (this contract-refactor; authoritative) supersedes `docs/superpowers/plans/2026-06-19-openms-benchmarking-platform.md` (the original version-vs-version harness). `docs/benchmark-overview.md` is the visual overview.

## Commands

The project is managed with **uv** (Python 3.11+ required; `tomllib` is used directly).

```bash
uv sync --extra test                      # create .venv with pytest
cp config.example.toml config.toml        # required before any run; config.toml is gitignored

# Run benchmarks: materialize images, docker run each benchmark, harvest metrics.tsv + run.json
uv run python -m bench run
uv run python -m bench run --benchmark comet           # one benchmark
uv run python -m bench run --type DDA-LFQ              # one benchmark-type
uv run python -m bench run --openms-ref <sha>          # sweep the OpenMS version
#   --type / --benchmark / --image are repeatable filters

# Build a wide comparison table across the whole results/runs tree (no central ledger)
uv run python -m bench aggregate                       # -> wide TSV on stdout
uv run python -m bench aggregate --out comparison.tsv

# Tests (no Docker or network required — see Testing below)
uv run --no-sync pytest
uv run --no-sync pytest tests/test_validate.py -v      # single file
```

> On Windows, `uv run` may try to re-sync the venv and fail on a `lib64` symlink permission error. Use `uv run --no-sync`, or `rm -rf .venv && uv sync --extra test` to rebuild.

## Architecture

### Host / container split (the central design constraint)

- **Host** = the Python `bench` package. Pure orchestration: materialize images, `docker run` each benchmark, capture `error.log`, validate `metrics.tsv` against the benchmark-type schema, write `run.json`. It contains **no proteomics and no scoring logic**.
- **Container** = the tool's own image. OpenMS = the branch's *unmodified* `dockerfiles/Dockerfile` target **`tools-thirdparty`** (OpenMS TOPP tools + Sage/Comet/MS-GF+/ProSE, **no Python**); external tools are pulled as-is. A mounted script runs the tool **and self-scores**, installing any deps it needs (e.g. `python3` for the OpenMS scorer) **on demand** at run time — the image is never edited.
- The two sides communicate **only** through three bind mounts — `/work` (scripts, ro), `/input` (the input bundle, ro), `/out` (results, rw) — and a minimal env set: `THREADS`, `INPUT_DIR=/input`, `OUT_DIR=/out`, `WORK=/work`, `OPENMS_BIN=/opt/OpenMS/bin`. Everything dataset-specific (tolerances, design, species rules, expected ratios) is read from `/input/spec.yaml`, **never** an env var. Scripts must never hardcode paths.

### End-to-end flow (`bench/cli.py`)

`bench run`: `load_config` (`config.toml` + `images.yaml` + `benchmarks.yaml`) → `all_benchmarks` → `filter_benchmarks` → for each `(benchmark_type, benchmark)`: `materialize_image` (build OpenMS @ref via `gitref` + `_ensure_thirdparty`, memoized; or pull) → `run_benchmark` (`docker run`, stdout+stderr → `out_dir/error.log`) → `parse_metrics_tsv` + `validate_metrics` → write `out_dir/run.json`. Per-benchmark failures are logged and counted; exit code 1 if any failed or was invalid.

`bench aggregate`: `collect_runs` walks `results/runs/*/*/*/metrics.tsv` (+ `run.json`) → `to_wide` → TSV.

### Config (`bench/config.py`, `images.yaml`, `benchmarks.yaml`)

- `config.toml` — host settings only: `openms_repo`, `threads`, `scripts_dir`, `results_dir`, timeouts.
- `images.yaml` — per-image `ImageSpec`: either `build: {context, dockerfile, target, ref, build_args}` (OpenMS; `ref` is the high-level version knob, overridable by `--openms-ref`) or `pull: <tag|digest>` (external).
- `benchmarks.yaml` — `benchmark_types`, each `{name, metrics[], benchmarks[]}`. A `MetricSpec` is `{name, unit, required}` (a trailing `*` in `name` is a glob, e.g. `median_log2_ratio_*`). A `Benchmark` is `{name, image, run, input}` — `image` keys into `images.yaml`, `run` is a script path under `scripts/`, `input` is a folder mounted at `/input`.

### Mounted scripts (`scripts/`)

Run inside the container; the OpenMS Python helpers are also host-unit-tested.
- `scripts/openms/<tool>.sh` — sources `lib/search-<engine>.sh` (defines `run_search()`), then `lib/common.sh`. `comet-perc.sh`/`msgf-perc.sh` `export FDR_BACKEND=percolator` first; `prose.sh` overrides `prepare_ids()` before sourcing `common.sh`.
- `scripts/lib/common.sh` — the shared DDA-LFQ chain: provision `python3` (untimed) → `spec.py` builds `design.tsv` + tolerances/FASTA → `metrics_init` → `phase_start` (reset cgroup peak, start clock) → `DecoyDatabase` → per-file [`run_search` → `prepare_ids`] → `ProteomicsLFQ` → MSstats CSV → awk → `quant.tsv` → `phase_end` (emit `wall_clock_s` + `peak_mem_bytes`) → `score.py >> metrics.tsv`.
- `scripts/lib/spec.py` — `spec.yaml` → `design.tsv` (paths `/input/<file>`) + shell `export`s.
- `scripts/lib/score.py` — the self-scorer (ported from the old host `species.py` + `lfq_quant.py`).
- `scripts/lib/emit.sh` — `metrics_init`, `metric_emit`, `phase_start`/`phase_end`.

**To add an OpenMS engine:** add `lib/search-<engine>.sh` + `openms/<engine>.sh` + a `benchmarks.yaml` entry. **To add an external tool:** add an `images.yaml` `pull:` entry, a `scripts/<tool>/<tool>.sh` that runs the tool and writes `/out/metrics.tsv` with the benchmark-type's metric columns, and a `benchmarks.yaml` entry. Cross-engine fairness for the OpenMS family is structural (one `common.sh`, identical params: Trypsin, 2 missed cleavages, fixed Carbamidomethyl(C), variable Oxidation(M), 1% PSM FDR, MBR off, top-3 quant; only tolerances vary). Cross-*tool* fairness rests on the metric contract, not shared code.

### FDR backends (`prepare_ids` in `common.sh`)

Both end with the `Posterior Error Probability` main score `ProteomicsLFQ` requires:
- **`idpep`** (default): PeptideIndexer → IDPosteriorErrorProbability → FalseDiscoveryRate → IDFilter @1% PSM → IDScoreSwitcher.
- **`percolator`** (`FDR_BACKEND=percolator`): PeptideIndexer → PSMFeatureExtractor → PercolatorAdapter → IDFilter → IDScoreSwitcher, **then a `sed` stripping non-string `UserParam`s** — a required workaround for a `ProteomicsLFQ` crash on non-string PSM metas in this branch. Only `comet-perc`/`msgf-perc` (PSMFeatureExtractor supports Comet/X!Tandem/MS-GF+ only). `prose.sh` overrides `prepare_ids()` to relabel ProSE's q-value as PEP.

### Input bundles (`data/<name>/`, bring-your-own)

A folder mounted read-only at `/input`, named by a benchmark's `input:`. Layout is the contract: `spec.yaml` (committed: `fasta`, `tolerances.{precursor_ppm,fragment_da}`, `species_rule.{exclude_regex,suffix_map}`, `expected_log2_ratio`, `ratio_direction`, `design.conditions.<A|B>.<rep>: [files]`) + the **decompressed** `.mzML` + FASTA (not committed). The harness does **no fetch/verify** in the run path. `tools/fetch.py` is an optional out-of-band helper (HTTP, sha-verify, gunzip, PENDING-pin) that populates a bundle.

### Scoring & metrics contract

`score.py` reads `quant.tsv` (`precursor, charge, protein, condition, replicate, intensity`; conditions literal `A`/`B`) + `spec.yaml`: assign species (`exclude_regex` first → `suffix_map` suffix, `""` catch-all), drop cross-species precursors, require quant in both conditions, emit per-species `median_log2_ratio_<sp>` / `mean_abs_error_<sp>`, `mean_abs_error_overall`, `median_intra_condition_cv`, counts. `common.sh` adds `wall_clock_s` + `peak_mem_bytes` (timed phase only). All land in `metrics.tsv` (`metric\tvalue\tunit`). The host validates against the benchmark-type's declared metrics; `peak_mem_bytes` is non-required so a missing/raw value never invalidates a run.

### Results (`results/runs/<openms-ref>/<tool>/<dataset>/`)

Per run: `metrics.tsv` (container), `error.log` (host redirect of stdout+stderr), `run.json` (host provenance: ref, image, threads, host_cpu, timestamp, returncode, outer_wall_s, `metrics_valid`). No append-only ledger; `bench aggregate` joins the tree into a wide table. **Performance metrics are never comparable across datasets or hosts** — `run.json` records `host_cpu`/`threads` so a comparison can be scoped accordingly.

## Key invariants

- **Never modify `OpenMS/`** except via `git fetch` / `git worktree`. It is a gitignored vendored checkout that serves as the build-context source. `*.worktree/` dirs are transient per-build worktrees.
- The harness **never edits the branch's `Dockerfile`** and always builds the `tools-thirdparty` target. Python for in-container scoring is installed **on demand by the run script**, never by editing the Dockerfile.
- `threads` is fixed (config) for fair performance comparison.
- The metric line (`metric\tvalue\tunit`) is the only host↔container result seam; the benchmark-type metric schema is the comparability contract.

## Testing

`pytest` only; tests require **neither Docker nor network**. `test_gitref.py` spins up a throwaway git repo; `test_config`/`test_images`/`test_runner`/`test_validate`/`test_aggregate`/`test_cli` cover pure host logic (loaders, command/mount/env builders, schema validation, tree aggregation). The in-container helpers `scripts/lib/spec.py` and `score.py` are imported via `importlib.util.spec_from_file_location` (`test_spec`, `test_score`, `test_example_spec`), so they're host-unit-tested *and* run in-container. Bash scripts get a contract test (`test_scripts_contract`). `test_fetch` exercises `tools/fetch.py` pure helpers. Docker-invoking code (`materialize_image`, the `docker run` in `runner.run_benchmark`) is covered only at the pure-function level. New non-Docker logic should stay unit-testable on the host.
