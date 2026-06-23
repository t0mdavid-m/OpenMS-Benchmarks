# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A controlled benchmark harness for OpenMS. It builds a **given OpenMS git ref** in Docker, runs pluggable bash workflows on pinned proteomics datasets, scores the output on the host, and appends quality + performance metrics to an append-only TSV. The OpenMS build is the *only* thing that changes between runs, so any metric delta is attributable to OpenMS itself.

The implementation plan in `docs/superpowers/plans/2026-06-19-openms-benchmarking-platform.md` is the authoritative design record (locked decisions, pinned reference facts, rationale).

## Commands

The project is managed with **uv** (Python 3.11+ required; `tomllib` is used directly).

```bash
uv sync --extra test                      # create .venv with pytest
cp config.example.toml config.toml        # required before any run; config.toml is gitignored

# Run the benchmark: build a ref, run all applicable workflow×dataset pairs, score, append metrics
uv run python -m bench --ref main
uv run python -m bench --ref <sha> --workflow lfq-comet --dataset proteobench_module2
#   --workflow/--dataset/--instrument are repeatable filters over the discovered matrix

# Tests (no Docker or network required — see Testing below)
uv run pytest
uv run pytest tests/test_workflows.py::test_discover_finds_lfq_sage   # single test

# View the long/tidy results.tsv as a wide table
uv run python pivot.py results/results.tsv
```

## Architecture

### Host / container split (the central design constraint)

- **Host** = the Python `bench` package. Pure orchestration: resolve ref→SHA, git worktree, `docker build`, fetch+verify datasets, `docker run`, score, append rows. It contains **no proteomics logic**.
- **Container** = an image built from *the branch's own unmodified* `dockerfiles/Dockerfile` (target **`tools-thirdparty`**). It has OpenMS TOPP tools + third-party search engines (Sage, Comet, MS-GF+) only — **no Python**. All in-container logic is bash/awk.
- The two sides communicate **only** through env vars (`INPUT_DIR`, `FASTA`, `OUT_DIR`, `THREADS`, `OPENMS_BIN`, `PREC_TOL_PPM`, `FRAG_TOL_DA`, `DESIGN_TSV`) and three bind mounts: `/work` (workflows, ro), `/data` (dataset cache, ro), `/out` (results). Workflow scripts must never hardcode paths.

### End-to-end flow (`bench/cli.py::main`)

`resolve_ref` → `checkout_worktree` (detached worktree off `OpenMS/`) → `build_image` → discover workflows × datasets → `expand_matrix` (pairs where `workflow.applies_to == dataset.category`) → apply CLI filters → for each pair: `fetch_dataset` (cached, sha-verified) → `run_workflow` (`docker run`) → `get_scorer(wf.type)(out_dir, ds)` → `append_rows`.

Per-pair failures are caught, logged, and recorded as a `run_failed`/`scoring_failed` metric row — the run continues to the next pair. Process exit code is 1 if any pair failed.

### Workflow plugin model (`workflows/`)

Each workflow is a directory `workflows/<name>/` with:
- `meta.yaml` — `name`, `engine`, `type` (selects the scorer), `applies_to` (matched against dataset `category`), `description`.
- `run.sh` — sources an engine search lib then the shared chain:
  ```bash
  source ../lib/search-<engine>.sh   # defines run_search() $mzml $db $out_id
  source ../common.sh                # the shared DDA-LFQ chain
  ```

`workflows/common.sh` is the shared chain: `DecoyDatabase` → per-file [`run_search` → `prepare_ids`] → `ProteomicsLFQ` → MSstats CSV → canonical **`quant.tsv`** (long format: `precursor, charge, protein, condition, replicate, intensity`). **To add a search engine:** add `lib/search-<engine>.sh` defining `run_search()` plus a thin `workflows/lfq-<engine>/` dir. Cross-engine fairness is enforced by keeping search params identical across engines (Trypsin, 2 missed cleavages, fixed Carbamidomethyl(C), variable Oxidation(M), 1% PSM FDR, MBR off, top-3 protein quant); only the per-dataset instrument tolerances vary.

### FDR backends (`prepare_ids` in `common.sh`)

`common.sh` provides two ID-processing paths, both ending with the `Posterior Error Probability` main score that `ProteomicsLFQ` requires:
- **`idpep`** (default): PeptideIndexer → IDPosteriorErrorProbability → FalseDiscoveryRate → IDFilter @1% PSM → IDScoreSwitcher.
- **`percolator`** (`export FDR_BACKEND=percolator` in run.sh): PeptideIndexer → PSMFeatureExtractor → PercolatorAdapter → IDFilter → IDScoreSwitcher, **then a `sed` that strips non-string `UserParam`s** — a required workaround for a `ProteomicsLFQ` crash on non-string PSM metas in this branch.

Percolator variants (`lfq-comet-perc`, `lfq-msgf-perc`) exist **only for Comet and MS-GF+**, because `PSMFeatureExtractor` supports only Comet/X!Tandem/MS-GF+. Sage and ProSE have no `-perc` variant by design. A `run.sh` may also **override `prepare_ids()` entirely before sourcing `common.sh`** — ProSE does this, relabeling its own q-value as PEP (IDPosteriorErrorProbability cannot model ProSE scores).

### Datasets (`datasets/`)

Each `datasets/<name>/` has `ground_truth.yaml` (meta: name/category/instrument/remote_dir/http_base/tolerances; `species_rule` = `exclude_regex` + `suffix_map`; `expected_log2_ratio`; `conditions` A/B → run lists) and `manifest.tsv` (`filename, role` [`spectra`|`fasta`], `condition, replicate, sha256`). A `sha256` of **`PENDING`** means "fetch then pin": `fetch.py` downloads, hashes, and **rewrites the manifest** with the real digest. Fetch order is rsync-over-SSH (if `[rsync]` configured) then HTTPS download-once fallback; everything is sha-verified and cached under `data/cache/`, and `.gz` spectra are auto-decompressed.

> `archive.openms.org` has a broken TLS cert (hostname mismatch). Either set `verify_tls = false` (HTTP fetch; sha256 pins still guarantee integrity) or configure `[rsync]`.

### Scoring (`bench/scoring/`)

`get_scorer(wf.type)` dispatches on the workflow `type`. `lfq_quant.py` reads `quant.tsv`, assigns each protein to a species via `species.assign_species()` (apply `exclude_regex` first to drop contaminants like `Cont_`, *then* `suffix_map`, with `""` as a catch-all), drops cross-species precursors, requires quant in both conditions, and emits per-species median log2(A/B), mean-abs-error vs expected, and intra-condition CV. **Performance metrics (`wall_clock_s`, `peak_container_mem_bytes`, `workflow_returncode`) are added by the harness for every run regardless of scorer** — peak memory is read inside the container from `/sys/fs/cgroup/memory.peak`.

### Results schema (`results/results.tsv`)

Append-only **long/tidy**: 9 identity columns (`run_timestamp, openms_sha, openms_tag, workflow, engine, dataset, instrument, threads, host_cpu`) + `metric_name, metric_value, unit` — one row per measured value. Adding a metric/workflow/dataset must never change the schema. **Performance metrics are never comparable across datasets or hosts**; that is why `dataset`, `instrument`, `host_cpu`, and `threads` are always identity columns.

## Key invariants

- **Never modify `OpenMS/`** except via `git fetch` / `git worktree`. It is a gitignored vendored checkout that serves as the worktree source for builds. (Its own `OpenMS/CLAUDE.md` is for OpenMS development and is unrelated to this harness.) `*.worktree/` dirs are transient per-build worktrees.
- The harness never edits the branch's `Dockerfile`; it always builds the `tools-thirdparty` target.
- `threads` is fixed (config) for fair performance comparison.

## Testing

`pytest` only; tests require **neither Docker nor network**. `test_gitref.py` spins up a throwaway git repo in a tmp dir; dataset/workflow tests read the real `datasets/` and `workflows/` directories; fetch tests exercise pure helpers (hashing, gz, manifest rewrite). Docker-dependent code (`build.py`, the `docker run` in `run.py`) is covered only at the pure-function level (e.g. `_container_name`, `write_design_tsv`). New non-Docker logic should follow suit and stay unit-testable on the host.
