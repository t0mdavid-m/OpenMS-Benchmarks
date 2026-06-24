# Benchmarking OpenMS against other tools

This repo is a **controlled benchmark** that compares OpenMS against other proteomics
tools (e.g. FragPipe, not yet wired up) on a shared task. Each tool runs in **its own container**; a
**mounted script runs the tool and scores its own output**, emitting one `metrics.tsv`. The
host is a thin orchestrator: it materializes images, runs each benchmark, and harvests the
results. The OpenMS image is *built from a git ref* (the high-level version knob), so you can
also compare OpenMS-vs-OpenMS by bumping that ref.

> **Running example.** `comet × proteobench_module2`: the OpenMS **Comet** workflow on
> **ProteoBench Module 2** (a 3-species mix with known abundance ratios).

## The pipeline at a glance

```mermaid
flowchart LR
    REF(["images.yaml: openms ref<br/>(or --openms-ref)"]):::var

    subgraph HOST["HOST — Python bench: orchestration only (no proteomics, no scoring)"]
        direction TB
        IMG["materialize image<br/>build OpenMS @ref / pull external"]:::host
        RUN["docker run<br/>per benchmark"]:::host
        HARVEST["harvest + validate<br/>metrics.tsv vs schema"]:::host
        TREE[("results/runs/&lt;ref&gt;/&lt;tool&gt;/&lt;ds&gt;/<br/>metrics.tsv · error.log · run.json")]:::host
        AGG["bench aggregate<br/>wide comparison on demand"]:::host
    end

    subgraph CONT["CONTAINER — the tool image: mounted script runs tool AND self-scores"]
        direction TB
        PROV["provision deps<br/>(e.g. apt install) — untimed"]:::cont
        TOOL["run tool<br/>(timed) + score"]:::cont
        METRICS[("/out/metrics.tsv")]:::cont
    end

    REF --> IMG
    IMG -. "image" .-> RUN
    RUN --> PROV --> TOOL --> METRICS
    METRICS --> HARVEST --> TREE --> AGG

    classDef host fill:#eef4ff,stroke:#3b62a8,color:#13294b;
    classDef cont fill:#eafaf0,stroke:#2f9e5f,color:#0b3d23;
    classDef var fill:#ffe27a,stroke:#d48806,stroke-width:3px,color:#5c3d00;
```

The **host** holds no proteomics or scoring logic. The **container** is the tool's own
image: the OpenMS image is the branch's `tools-thirdparty` build (untouched); external tools
are pulled by pinned tag. Whatever a script needs that the image lacks (e.g. Python for the
OpenMS scorer) it installs on demand at run time.

## The host ⇄ container contract

Three bind mounts and a minimal env set — nothing dataset-specific is passed as an env var;
that all lives in the input bundle's `spec.yaml`.

| Channel | Inside the container | Carries |
| --- | --- | --- |
| mount `/work` *(ro)* | `WORK=/work` | mounted scripts: `openms/<tool>.sh`, `lib/` (`common.sh`, `search-*.sh`, `spec.py`, `score.py`, `emit.sh`) |
| mount `/input` *(ro)* | `INPUT_DIR=/input` | the bring-your-own bundle: `spec.yaml` + `.mzML` + FASTA |
| mount `/out` *(rw)* | `OUT_DIR=/out` | the run's `metrics.tsv`, `quant.tsv`, work dir |
| env `THREADS` | fixed thread count | held constant for fair perf comparison |
| env `OPENMS_BIN` | `/opt/OpenMS/bin` | where the TOPP tools live |

The container's only required output is **`/out/metrics.tsv`** (`metric  value  unit`); its
stdout+stderr are captured by the host into `/out/error.log`.

## Inside an OpenMS workflow

An OpenMS workflow is wired from two **yaml declarations** plus a few **mounted scripts** — the
host runs no proteomics code of its own. `benchmarks.yaml` names the benchmark (`{name, image,
run, input}` and the type's metric contract); `images.yaml` says how its `image` is built. The
`run:` script is the entry point: for the OpenMS family it's a thin file that `source`s an engine
**search lib** (which defines `run_search()`) and then the shared **`common.sh`** chain.

```mermaid
flowchart TB
    subgraph DECL["declarative layer — yaml the host reads"]
        direction LR
        BM["benchmarks.yaml<br/>name · image · run · input<br/>+ the type's metric contract"]:::yaml
        IM["images.yaml<br/>openms: build tools-thirdparty @ref"]:::yaml
    end

    ENTRY["scripts/openms/&lt;engine&gt;.sh<br/>comet · sage · msgf · prose<br/>= the run: entry script"]:::cont
    SEARCH["lib/search-&lt;engine&gt;.sh<br/>defines run_search()"]:::plug
    COMMON["lib/common.sh<br/>shared chain: decoy · search<br/>· ProteomicsLFQ · quant · score"]:::cont
    SPEC[("/input/spec.yaml<br/>tolerances · design · species")]:::data
    METRICS[("/out/metrics.tsv<br/>★ the only hard contract")]:::data
    EXT["any non-OpenMS tool's script<br/>scripts/&lt;tool&gt;/&lt;tool&gt;.sh"]:::opt

    BM -- "run:" --> ENTRY
    IM -- "builds image" --> ENTRY
    ENTRY -- "source" --> SEARCH
    ENTRY -- "source" --> COMMON
    SPEC --> COMMON
    COMMON --> METRICS
    EXT -. "bypasses common.sh" .-> METRICS

    classDef yaml fill:#fff7e0,stroke:#d48806,color:#5c3d00;
    classDef cont fill:#eafaf0,stroke:#2f9e5f,color:#0b3d23;
    classDef plug fill:#ffe27a,stroke:#d48806,stroke-width:2px,color:#5c3d00;
    classDef data fill:#eef4ff,stroke:#3b62a8,color:#13294b;
    classDef opt fill:#f5f5f5,stroke:#999999,stroke-dasharray:5 3,color:#444444;
```

Every OpenMS engine reuses the one `common.sh`, but that reuse is a **convention, not a harness
requirement**: the only hard contract is `/out/metrics.tsv`. A non-OpenMS tool's script can skip
`common.sh` entirely and write that file its own way — the *add an external tool* path.

**The declarative layer (yaml).** One benchmark is one line — `image:` keys into `images.yaml`,
`input:` is the bundle mounted read-only at `/input`, `run:` is the script under `/work`:

```yaml
# benchmarks.yaml  (one entry; the same file declares the type's required metrics)
- {name: comet, image: openms, run: openms/comet.sh, input: data/proteobench_module2}
```

**The engine plug.** A `search-<engine>.sh` defines the one engine-specific step — a thin
wrapper over the TOPP search tool, parameterized by tolerances pulled from `spec.yaml`:

```bash
# scripts/lib/search-comet.sh — the only per-engine code
run_search() {                       # common.sh calls this once per .mzML
  local mzml="$1" db="$2" out_id="$3"
  CometAdapter -in "$mzml" -database "$db" -out "$out_id" \
    -enzyme Trypsin -missed_cleavages 2 \
    -fixed_modifications "Carbamidomethyl (C)" -variable_modifications "Oxidation (M)" \
    -precursor_mass_tolerance "$PREC_TOL_PPM" -fragment_mass_tolerance "$FRAG_TOL_DA" \
    -threads "$THREADS"
}
```

`common.sh` then runs the measured chain — build a decoy DB, `run_search` + FDR-filter each
`.mzML`, `ProteomicsLFQ` (top-3, MBR off) → `quant.tsv` — and self-scores into `metrics.tsv`
afterwards (untimed). Everything dataset-specific it reads from the bundle's `spec.yaml`:

```yaml
# data/proteobench_module2/spec.yaml  (excerpt)
tolerances: {precursor_ppm: 10.0, fragment_da: 0.02}      # → run_search params
species_rule:                                             # → score.py
  exclude_regex: "Cont_"                                  # drop contaminants first
  suffix_map: {_HUMAN: HUMAN, _YEAST: YEAST, _ECOLI: ECOLI}
design:                                                   # → design.tsv (A vs B, 3 reps each)
  conditions:
    A: {1: [..._Condition_A_..._01.mzML], 2: [...], 3: [...]}
    B: {1: [..._Condition_B_..._01.mzML], 2: [...], 3: [...]}
```

**Three ways an entry script wires in.** The whole per-engine script is composition; what
differs is how much it customizes *before* sourcing `common.sh`:

```bash
# openms/comet.sh — plain: just plug an engine into the chain
source "$WORK/lib/search-comet.sh"      # defines run_search()
source "$WORK/lib/common.sh"            # FDR backend defaults to idpep

# openms/comet-perc.sh — backend flag: export an env var FIRST
export FDR_BACKEND=percolator           # common.sh then selects the percolator FDR path
source "$WORK/lib/search-comet.sh"
source "$WORK/lib/common.sh"

# openms/prose.sh — override: define the function BEFORE sourcing
source "$WORK/lib/search-prose.sh"
prepare_ids() { ...; }                  # common.sh keeps a pre-defined prepare_ids
source "$WORK/lib/common.sh"
```

`prepare_ids()` must end with the `Posterior Error Probability` main score `ProteomicsLFQ`
requires — which is why the backend is a wiring choice. Three forms: **`idpep`** *(default)* —
`IDPosteriorErrorProbability → FalseDiscoveryRate → IDFilter @1% PSM → PEP`; **`percolator`** —
`PSMFeatureExtractor → PercolatorAdapter → IDFilter → PEP`, used only by `comet-perc`/`msgf-perc`
(`PSMFeatureExtractor` supports only Comet / X!Tandem / MS-GF+); **engine override** — `prose.sh`
replaces `prepare_ids()` entirely, since `IDPosteriorErrorProbability` can't model ProSE scores,
so it relabels ProSE's own q-value as PEP. `sage.sh` and `msgf.sh` use the plain pattern with
their own `search-*.sh`.

That shared chain is also what makes cross-engine comparison **fair**: identical params
throughout (Trypsin, 2 missed cleavages, fixed Carbamidomethyl(C), variable Oxidation(M), 1% PSM
FDR, MBR off, top-3 quant); only per-dataset tolerances vary. (MS-GF+ uses `Trypsin/P` + an
`-instrument high_res` fragment preset — a known gap.)

> **Cross-*tool* fairness** is the metric contract, not shared code: every benchmark of a
> type emits the same metric columns, computed by whatever scorer its script ships. Drift
> between two tools' scorers is a risk the contract makes visible but does not prevent.

## What comes out

`score.py` turns `quant.tsv` into metric rows: assign each protein to a species (drop `Cont_`
contaminants **first**, then match the species suffix), drop cross-species precursors, require
quant in **both** conditions, and report per-species **median log2(A/B)** and **mean-abs-error
vs the expected ratio**, plus precursor/protein counts and intra-condition CV. The script also
emits **`wall_clock_s`** and **`peak_mem_bytes`** scoped to the *timed* phase (it resets the
cgroup peak counter after provisioning).

> For `proteobench_module2` the expected log2(A/B) is **HUMAN 0**, **YEAST +1**, **ECOLI −2**.

There is **no central ledger.** Each run writes three files under
`results/runs/<openms-ref>/<tool>/<dataset>/`:

| file | written by | holds |
| --- | --- | --- |
| `metrics.tsv` | container | `metric  value  unit` rows (the comparable result) |
| `error.log` | host (redirect) | the container's stdout+stderr |
| `run.json` | host | provenance: image tag, ref, threads, host_cpu, timestamp, returncode, outer wall, `metrics_valid` |

The host validates each `metrics.tsv` against the benchmark-type's declared metric schema
(in `benchmarks.yaml`) — missing required metrics → `metrics_valid: false`. Build a wide
comparison across the whole tree on demand:

```bash
uv run python -m bench aggregate            # -> wide TSV on stdout
```

## Run it / add a tool

```bash
cp config.example.toml config.toml
uv run python -m bench run                                  # whole matrix
uv run python -m bench run --benchmark comet                # one benchmark
uv run python -m bench run --openms-ref <sha>               # sweep OpenMS version
```

**Add an OpenMS engine:** drop `scripts/lib/search-<engine>.sh` (defines `run_search()`) +
`scripts/openms/<engine>.sh` (sources it then `common.sh`), and add a `benchmarks.yaml`
entry. **Add an external tool:** add an `images.yaml` entry (`pull: tool:tag`), a
`scripts/<tool>/<tool>.sh` that runs the tool and writes `/out/metrics.tsv` with the
benchmark-type's metric columns, and a `benchmarks.yaml` entry pointing at it.

**Prepare an input bundle:** a folder with `spec.yaml` (design, tolerances, species rules,
expected ratios) + the `.mzML` + FASTA. Populate it however you like; `tools/fetch.py` is an
optional out-of-band helper that fetches + sha-verifies + gunzips into the folder.
