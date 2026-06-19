# OpenMS Benchmarking Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a given OpenMS git ref in Docker, run pluggable benchmark workflows on pinned datasets, and log quality + performance "key values" per `(sha, workflow, dataset)` to an append-only TSV.

**Architecture:** A Python host harness (`bench`) orchestrates: resolve a ref → SHA via a `git worktree` off the local `OpenMS/` checkout; `docker build` using the *branch's own* `dockerfiles/Dockerfile` (target `tools-thirdparty`); fetch dataset spectra+FASTA from `archive.openms.org` (rsync-over-SSH primary, HTTPS download-once fallback) into a local cache; for each discovered workflow × applicable dataset, `docker run` a bash workflow script with our scripts + data bind-mounted in (the image contains OpenMS tools only); a host-side scorer registry turns each workflow's raw output into long/tidy metric rows appended to `results.tsv`. The OpenMS image is the only thing that changes between runs, so any metric delta is attributable to OpenMS.

**Tech Stack:** Python 3.11+ (stdlib `tomllib`, `argparse`, `subprocess`, `csv`; PyYAML for ground-truth/meta), pytest, Docker (Desktop on Windows), git, rsync-over-SSH, OpenMS TOPP tools + third-party search engines (Sage, Comet) inside the container, bash workflow scripts.

## Global Constraints

- Python **3.11+** (uses stdlib `tomllib`). Single runtime dependency: **PyYAML**. Everything else is stdlib.
- The platform repo root is `C:\Tom\Benchmark_Timo`. The `OpenMS/` checkout already present there is the worktree source — **never** modify it except via `git fetch`/`git worktree`.
- Builds use the **branch's own unmodified** `dockerfiles/Dockerfile`, target **`tools-thirdparty`**. The harness never edits that Dockerfile.
- The container has **only** bash + OpenMS tools + third-party engines — **no Python**. All in-container logic is bash/awk.
- Workflow scripts read inputs **only** from env vars `INPUT_DIR`, `FASTA`, `OUT_DIR`, `THREADS`, `OPENMS_BIN` — never hardcoded paths.
- `results.tsv` is **append-only, long/tidy**: one row per measured value. Adding a metric/workflow/dataset must never change the schema.
- Quality metrics are comparable across instruments only when ground-truth designs match; **performance metrics are never comparable across datasets/hosts** — `dataset`, `instrument`, `host_cpu`, `threads` are always identity columns.
- Search params identical across engines (Trypsin, 2 missed cleavages, fixed Carbamidomethyl(C), variable Oxidation(M), 1% PSM FDR, MBR off, top-3 protein quant). Instrument tolerances come from the dataset folder.
- Pinned reference facts (verified 2026-06-19), used verbatim in tasks below:
  - Dataset root (HTTP): `https://archive.openms.org/openms/benchmarks/pride-benchmarks/`
  - rsync chroot root = web `openms/` dir → dataset rsync path `:/benchmarks/pride-benchmarks/<category>/<instrument>/<name>/`
  - FASTA: `…/lfq/QExactiveHF/ProteoBench_Module_2/ProteoBenchFASTA_MixedSpecies_HYE.fasta`, sha256 `d9ac434d88492c10c8e9a587ee7dbc9480fa0995fa07a6ba35a7da8abf39aa25`
  - ProteoBench Module 2 expected log2(A/B): `HUMAN 0.0, YEAST 1.0, ECOLI -2.0`
  - FASTA headers `sp|<acc>|<NAME>_<SPECIES>`; contaminants prefixed `Cont_` and **must be excluded before** species-suffix assignment.

---

## File Structure

```
Benchmark_Timo/
├── pyproject.toml                      # package metadata + deps (PyYAML) + pytest config
├── config.example.toml                 # template; user copies to config.toml (gitignored)
├── .gitignore                          # data/cache, config.toml, *.worktree, .pytest_cache
├── bench/
│   ├── __init__.py
│   ├── config.py                       # load_config() -> Config
│   ├── gitref.py                       # resolve_ref(), checkout_worktree()
│   ├── species.py                      # assign_species()
│   ├── datasets.py                     # FileEntry, GroundTruth, Dataset, load/discover
│   ├── workflows.py                    # Workflow, discover_workflows(), expand_matrix()
│   ├── fetch.py                        # fetch_dataset() (rsync primary, http fallback, verify)
│   ├── build.py                        # build_image()
│   ├── run.py                          # RunResult, run_workflow()
│   ├── results.py                      # Metric, append_rows()
│   ├── cli.py                          # argparse entrypoint (python -m bench)
│   └── scoring/
│       ├── __init__.py                 # registry: get_scorer(type)
│       ├── lfq_quant.py                # score() for type "lfq-quant"
│       └── perf_only.py                # score() for type "perf-only"
├── workflows/
│   ├── common.sh                       # shared chain DecoyDatabase→search→index→FDR→ProteomicsLFQ→quant.tsv
│   ├── lfq-sage/{run.sh, meta.yaml}
│   └── lfq-comet/{run.sh, meta.yaml}
├── datasets/
│   ├── proteobench_module2/{manifest.tsv, ground_truth.yaml}
│   └── <placeholder dataset>/{manifest.tsv, ground_truth.yaml}
├── pivot.py                            # long results.tsv -> wide view
├── results/results.tsv                 # append-only output (created on first run)
└── tests/
    ├── conftest.py
    ├── test_species.py
    ├── test_datasets.py
    ├── test_workflows.py
    ├── test_scoring_lfq_quant.py
    ├── test_scoring_perf_only.py
    ├── test_results.py
    └── test_gitref.py
```

---

## Task 1: Project scaffold, config, gitignore

**Files:**
- Create: `pyproject.toml`, `bench/__init__.py`, `bench/config.py`, `config.example.toml`, `.gitignore`
- Test: `tests/conftest.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `bench.config.Config` dataclass with fields `openms_repo: Path`, `data_cache: Path`, `results_tsv: Path`, `workflows_dir: Path`, `datasets_dir: Path`, `threads: int`, `http_base: str`, `rsync_user: str | None`, `rsync_host: str | None`, `rsync_port: int | None`, `rsync_key: str | None`. Function `load_config(path: Path) -> Config`.

- [ ] **Step 1: Initialize the git repo and package files**

Run:
```bash
cd /c/Tom/Benchmark_Timo
git init
```

Create `pyproject.toml`:
```toml
[project]
name = "openms-bench"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["PyYAML>=6.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.setuptools.packages.find]
include = ["bench*"]
```

Create `.gitignore`:
```
data/cache/
config.toml
*.worktree/
.pytest_cache/
__pycache__/
results/results.tsv
```

Create `bench/__init__.py` (empty file).

- [ ] **Step 2: Write the failing test for config loading**

Create `tests/conftest.py`:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

Create `tests/test_config.py`:
```python
from pathlib import Path

from bench.config import load_config


def test_load_config_reads_values(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        'openms_repo = "OpenMS"\n'
        'threads = 4\n'
        'http_base = "https://archive.openms.org/openms/benchmarks/pride-benchmarks/"\n'
        '[rsync]\n'
        'user = "u"\n'
        'host = "h"\n'
        'port = 22\n'
        'key = "k"\n',
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.threads == 4
    assert cfg.openms_repo == Path("OpenMS")
    assert cfg.rsync_user == "u"
    assert cfg.rsync_port == 22


def test_load_config_rsync_optional(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('openms_repo = "OpenMS"\nthreads = 2\n', encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.rsync_user is None
    assert cfg.threads == 2
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.config'`.

- [ ] **Step 4: Implement `bench/config.py`**

```python
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    openms_repo: Path
    data_cache: Path
    results_tsv: Path
    workflows_dir: Path
    datasets_dir: Path
    threads: int
    http_base: str
    rsync_user: str | None
    rsync_host: str | None
    rsync_port: int | None
    rsync_key: str | None


def load_config(path: Path) -> Config:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    root = Path(path).resolve().parent
    rsync = data.get("rsync", {})
    return Config(
        openms_repo=Path(data.get("openms_repo", "OpenMS")),
        data_cache=Path(data.get("data_cache", root / "data" / "cache")),
        results_tsv=Path(data.get("results_tsv", root / "results" / "results.tsv")),
        workflows_dir=Path(data.get("workflows_dir", root / "workflows")),
        datasets_dir=Path(data.get("datasets_dir", root / "datasets")),
        threads=int(data.get("threads", 4)),
        http_base=data.get(
            "http_base",
            "https://archive.openms.org/openms/benchmarks/pride-benchmarks/",
        ),
        rsync_user=rsync.get("user"),
        rsync_host=rsync.get("host"),
        rsync_port=rsync.get("port"),
        rsync_key=rsync.get("key"),
    )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Create `config.example.toml`**

```toml
# Copy to config.toml and fill in. config.toml is gitignored.
openms_repo = "OpenMS"          # path to the OpenMS git checkout (worktree source)
threads = 4                     # fixed thread count for fair perf comparison
http_base = "https://archive.openms.org/openms/benchmarks/pride-benchmarks/"

# rsync-over-SSH credentials (maintainer only). Omit this section to use HTTP fallback.
[rsync]
user = "FILL_ME"                # ARCHIVE_RRSYNC_USER
host = "FILL_ME"                # ARCHIVE_RRSYNC_HOST
port = 22                       # ARCHIVE_RRSYNC_PORT
key  = "C:/path/to/private.key" # ARCHIVE_RRSYNC_SSH written to a file
```

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .gitignore config.example.toml bench/__init__.py bench/config.py tests/conftest.py tests/test_config.py
git commit -m "feat: project scaffold and config loader"
```

---

## Task 2: Git ref resolution + worktree checkout

**Files:**
- Create: `bench/gitref.py`
- Test: `tests/test_gitref.py`

**Interfaces:**
- Consumes: nothing from prior tasks (operates on a git repo path).
- Produces: `resolve_ref(repo: Path, ref: str) -> str` (returns full 40-char SHA), `checkout_worktree(repo: Path, sha: str, dest: Path) -> Path` (creates a detached worktree at `dest`, returns `dest`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_gitref.py`:
```python
import subprocess
from pathlib import Path

import pytest

from bench.gitref import resolve_ref, checkout_worktree


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def tiny_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("hi", encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-m", "c1")
    return repo


def test_resolve_ref_returns_full_sha(tiny_repo: Path):
    sha = resolve_ref(tiny_repo, "main")
    assert len(sha) == 40
    assert sha == _git(tiny_repo, "rev-parse", "main")


def test_checkout_worktree_materializes_tree(tiny_repo: Path, tmp_path: Path):
    sha = resolve_ref(tiny_repo, "main")
    dest = tmp_path / "wt"
    checkout_worktree(tiny_repo, sha, dest)
    assert (dest / "f.txt").read_text(encoding="utf-8") == "hi"
    assert (dest / ".git").exists()  # worktree has a .git link file
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_gitref.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.gitref'`.

- [ ] **Step 3: Implement `bench/gitref.py`**

```python
import shutil
import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def resolve_ref(repo: Path, ref: str) -> str:
    """Resolve a branch name or SHA to a full 40-char commit SHA.

    Fetches first so remote branches/PR refs are available.
    """
    repo = Path(repo)
    try:
        _git(repo, "fetch", "--all", "--tags", "--quiet")
    except subprocess.CalledProcessError:
        pass  # offline: fall back to whatever objects are local
    return _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")


def checkout_worktree(repo: Path, sha: str, dest: Path) -> Path:
    """Create a clean detached worktree at `dest` checked out at `sha`."""
    repo = Path(repo)
    dest = Path(dest)
    if dest.exists():
        # Remove a stale worktree registration then the dir.
        subprocess.run(["git", "-C", str(repo), "worktree", "remove",
                        "--force", str(dest)], capture_output=True, text=True)
        if dest.exists():
            shutil.rmtree(dest)
    _git(repo, "worktree", "add", "--detach", "--force", str(dest), sha)
    return dest
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_gitref.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add bench/gitref.py tests/test_gitref.py
git commit -m "feat: resolve refs and materialize per-SHA worktrees"
```

---

## Task 3: Species assignment

**Files:**
- Create: `bench/species.py`
- Test: `tests/test_species.py`

**Interfaces:**
- Produces: `assign_species(protein_header: str, exclude_regex: str, suffix_map: dict[str, str]) -> str | None`. Returns `None` if the protein is excluded (matches `exclude_regex`) or matches no suffix.

- [ ] **Step 1: Write the failing test**

Create `tests/test_species.py`:
```python
from bench.species import assign_species

SUFFIX = {"_HUMAN": "HUMAN", "_YEAST": "YEAST", "_ECOLI": "ECOLI"}


def test_assigns_by_suffix():
    assert assign_species("sp|P49327|FAS_HUMAN", "Cont_", SUFFIX) == "HUMAN"
    assert assign_species("sp|P00330|ADH1_YEAST", "Cont_", SUFFIX) == "YEAST"


def test_contaminant_excluded_even_if_suffix_matches():
    # This is the documented trap: contaminant carries an _ECOLI suffix.
    assert assign_species("sp|Cont_P00722|BGAL_ECOLI", "Cont_", SUFFIX) is None


def test_unknown_suffix_returns_none():
    assert assign_species("sp|X|FOO_BAR", "Cont_", SUFFIX) is None


def test_single_group_placeholder_rule():
    # Placeholder datasets map everything non-contaminant to one group.
    assert assign_species("sp|X|FOO_BAR", "Cont_", {"": "ALL"}) == "ALL"
    assert assign_species("sp|Cont_X|FOO_BAR", "Cont_", {"": "ALL"}) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_species.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.species'`.

- [ ] **Step 3: Implement `bench/species.py`**

```python
import re


def assign_species(protein_header: str, exclude_regex: str,
                   suffix_map: dict[str, str]) -> str | None:
    """Assign a protein to a species group.

    1. If `exclude_regex` matches the header, return None (e.g. contaminants).
    2. Otherwise return the species for the first matching suffix.
    3. An empty-string suffix key acts as a catch-all (placeholder "ALL").
    """
    if exclude_regex and re.search(exclude_regex, protein_header):
        return None
    for suffix, species in suffix_map.items():
        if suffix == "":
            return species  # catch-all
        if protein_header.endswith(suffix):
            return species
    return None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_species.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add bench/species.py tests/test_species.py
git commit -m "feat: species assignment with contaminant exclusion"
```

---

## Task 4: Dataset model — manifest + ground_truth loaders

**Files:**
- Create: `bench/datasets.py`, `datasets/proteobench_module2/manifest.tsv`, `datasets/proteobench_module2/ground_truth.yaml`
- Test: `tests/test_datasets.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `FileEntry` dataclass: `filename: str`, `rsync_path: str`, `http_url: str`, `sha256: str`, `role: str` (`"spectra"|"fasta"`), `condition: str | None`, `replicate: int | None`.
  - `GroundTruth` dataclass: `exclude_regex: str`, `suffix_map: dict[str,str]`, `expected_log2: dict[str,float]`, `ratio_direction: str`, `conditions: dict[str, list[str]]`.
  - `Dataset` dataclass: `name: str`, `category: str`, `instrument: str`, `path: Path`, `files: list[FileEntry]`, `ground_truth: GroundTruth`. Property `spectra() -> list[FileEntry]`, `fasta() -> FileEntry`.
  - `load_dataset(path: Path) -> Dataset`, `discover_datasets(root: Path) -> list[Dataset]`.

`manifest.tsv` columns (tab-separated, with header): `filename  role  condition  replicate  sha256`. The `category` and `instrument` are read from a `meta` table in `ground_truth.yaml` (which also pins provenance).

- [ ] **Step 1: Create the real dataset folder for ProteoBench Module 2**

Create `datasets/proteobench_module2/ground_truth.yaml`:
```yaml
meta:
  name: proteobench_module2
  category: lfq
  instrument: QExactiveHF
  precursor_tol_ppm: 10.0
  fragment_tol_da: 0.02
provenance:
  source: https://raw.githubusercontent.com/Proteobench/ProteoBench/main/proteobench/io/parsing/io_parse_settings/Quant/lfq/DDA/ion/QExactive/module_settings.toml
  retrieved: "2026-06-19"
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
conditions:
  A: [LFQ_Orbitrap_DDA_Condition_A_Sample_Alpha_01,
      LFQ_Orbitrap_DDA_Condition_A_Sample_Alpha_02,
      LFQ_Orbitrap_DDA_Condition_A_Sample_Alpha_03]
  B: [LFQ_Orbitrap_DDA_Condition_B_Sample_Alpha_01,
      LFQ_Orbitrap_DDA_Condition_B_Sample_Alpha_02,
      LFQ_Orbitrap_DDA_Condition_B_Sample_Alpha_03]
```

Create `datasets/proteobench_module2/manifest.tsv` (the 6 mzML sha256 values are filled by Task 9's fetch on first run; use the literal `PENDING` sentinel until then — `fetch_dataset` computes and rewrites them. The FASTA sha256 is already known and pinned):
```
filename	role	condition	replicate	sha256
LFQ_Orbitrap_DDA_Condition_A_Sample_Alpha_01.mzML	spectra	A	1	PENDING
LFQ_Orbitrap_DDA_Condition_A_Sample_Alpha_02.mzML	spectra	A	2	PENDING
LFQ_Orbitrap_DDA_Condition_A_Sample_Alpha_03.mzML	spectra	A	3	PENDING
LFQ_Orbitrap_DDA_Condition_B_Sample_Alpha_01.mzML	spectra	B	1	PENDING
LFQ_Orbitrap_DDA_Condition_B_Sample_Alpha_02.mzML	spectra	B	2	PENDING
LFQ_Orbitrap_DDA_Condition_B_Sample_Alpha_03.mzML	spectra	B	3	PENDING
ProteoBenchFASTA_MixedSpecies_HYE.fasta	fasta		d9ac434d88492c10c8e9a587ee7dbc9480fa0995fa07a6ba35a7da8abf39aa25
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_datasets.py`:
```python
from pathlib import Path

from bench.datasets import load_dataset


def test_load_proteobench_module2():
    ds = load_dataset(Path("datasets/proteobench_module2"))
    assert ds.name == "proteobench_module2"
    assert ds.category == "lfq"
    assert ds.instrument == "QExactiveHF"
    assert len(ds.spectra()) == 6
    assert ds.fasta().filename == "ProteoBenchFASTA_MixedSpecies_HYE.fasta"
    assert ds.fasta().sha256.startswith("d9ac434d")
    assert ds.ground_truth.expected_log2["YEAST"] == 1.0
    assert ds.ground_truth.expected_log2["ECOLI"] == -2.0
    assert ds.ground_truth.exclude_regex == "Cont_"
    a_files = ds.ground_truth.conditions["A"]
    assert len(a_files) == 3


def test_http_url_and_rsync_path_built_from_layout():
    ds = load_dataset(Path("datasets/proteobench_module2"))
    fasta = ds.fasta()
    assert fasta.http_url.endswith(
        "lfq/QExactiveHF/proteobench_module2/"
        "ProteoBenchFASTA_MixedSpecies_HYE.fasta"
    ) or fasta.http_url.endswith(
        "lfq/QExactiveHF/ProteoBench_Module_2/"
        "ProteoBenchFASTA_MixedSpecies_HYE.fasta"
    )
    assert fasta.rsync_path.startswith("/benchmarks/pride-benchmarks/lfq/QExactiveHF/")
```

> Note: the archive folder is `ProteoBench_Module_2` while our local dataset dir is `proteobench_module2`. The remote folder name is set via `meta.remote_dir` in `ground_truth.yaml` — add `remote_dir: ProteoBench_Module_2` under `meta:` now.

Add to `datasets/proteobench_module2/ground_truth.yaml` under `meta:`:
```yaml
  remote_dir: ProteoBench_Module_2
  http_base: https://archive.openms.org/openms/benchmarks/pride-benchmarks/
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python -m pytest tests/test_datasets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.datasets'`.

- [ ] **Step 4: Implement `bench/datasets.py`**

```python
import csv
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class FileEntry:
    filename: str
    rsync_path: str
    http_url: str
    sha256: str
    role: str
    condition: str | None
    replicate: int | None


@dataclass
class GroundTruth:
    exclude_regex: str
    suffix_map: dict[str, str]
    expected_log2: dict[str, float]
    ratio_direction: str
    conditions: dict[str, list[str]]


@dataclass
class Dataset:
    name: str
    category: str
    instrument: str
    path: Path
    files: list[FileEntry]
    ground_truth: GroundTruth
    precursor_tol_ppm: float
    fragment_tol_da: float

    def spectra(self) -> list[FileEntry]:
        return [f for f in self.files if f.role == "spectra"]

    def fasta(self) -> FileEntry:
        return next(f for f in self.files if f.role == "fasta")


def load_dataset(path: Path) -> Dataset:
    path = Path(path)
    gt_raw = yaml.safe_load((path / "ground_truth.yaml").read_text(encoding="utf-8"))
    meta = gt_raw["meta"]
    http_base = meta["http_base"].rstrip("/") + "/"
    remote_dir = meta.get("remote_dir", meta["name"])
    rel = f"{meta['category']}/{meta['instrument']}/{remote_dir}"

    files: list[FileEntry] = []
    with (path / "manifest.tsv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            files.append(FileEntry(
                filename=row["filename"],
                rsync_path=f"/benchmarks/pride-benchmarks/{rel}/{row['filename']}",
                http_url=f"{http_base}{rel}/{row['filename']}",
                sha256=row["sha256"].strip(),
                role=row["role"].strip(),
                condition=(row["condition"].strip() or None),
                replicate=(int(row["replicate"]) if row["replicate"].strip() else None),
            ))

    rule = gt_raw["species_rule"]
    gt = GroundTruth(
        exclude_regex=rule.get("exclude_regex", ""),
        suffix_map=rule["suffix_map"],
        expected_log2={k: float(v) for k, v in gt_raw["expected_log2_ratio"].items()},
        ratio_direction=gt_raw["ratio_direction"],
        conditions=gt_raw["conditions"],
    )
    return Dataset(
        name=meta["name"],
        category=meta["category"],
        instrument=meta["instrument"],
        path=path,
        files=files,
        ground_truth=gt,
        precursor_tol_ppm=float(meta["precursor_tol_ppm"]),
        fragment_tol_da=float(meta["fragment_tol_da"]),
    )


def discover_datasets(root: Path) -> list[Dataset]:
    root = Path(root)
    return [load_dataset(p) for p in sorted(root.iterdir())
            if (p / "ground_truth.yaml").exists()]
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_datasets.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add bench/datasets.py datasets/proteobench_module2 tests/test_datasets.py
git commit -m "feat: dataset model with manifest + ground_truth, ProteoBench Module 2"
```

---

## Task 5: Workflow discovery + matrix expansion

**Files:**
- Create: `bench/workflows.py`, `workflows/lfq-sage/meta.yaml`
- Test: `tests/test_workflows.py`

**Interfaces:**
- Consumes: `bench.datasets.Dataset`.
- Produces:
  - `Workflow` dataclass: `name: str`, `engine: str`, `type: str`, `applies_to: str`, `run_script: Path`, `dir: Path`.
  - `discover_workflows(root: Path) -> list[Workflow]` (globs `*/meta.yaml`, requires sibling `run.sh`).
  - `expand_matrix(workflows: list[Workflow], datasets: list[Dataset]) -> list[tuple[Workflow, Dataset]]` (pairs where `workflow.applies_to == dataset.category`).

- [ ] **Step 1: Create the first workflow's meta.yaml**

Create `workflows/lfq-sage/meta.yaml`:
```yaml
name: lfq-sage
engine: sage
type: lfq-quant
applies_to: lfq
description: Label-free DDA quantification using the Sage search engine.
```

Create a placeholder `workflows/lfq-sage/run.sh` (real content in Task 7; needs to exist for discovery):
```bash
#!/usr/bin/env bash
echo "placeholder - implemented in Task 7" >&2
exit 1
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_workflows.py`:
```python
from pathlib import Path

from bench.datasets import load_dataset
from bench.workflows import discover_workflows, expand_matrix


def test_discover_finds_lfq_sage():
    wfs = discover_workflows(Path("workflows"))
    names = {w.name for w in wfs}
    assert "lfq-sage" in names
    sage = next(w for w in wfs if w.name == "lfq-sage")
    assert sage.engine == "sage"
    assert sage.type == "lfq-quant"
    assert sage.applies_to == "lfq"
    assert sage.run_script.name == "run.sh"


def test_matrix_pairs_by_category():
    wfs = discover_workflows(Path("workflows"))
    ds = load_dataset(Path("datasets/proteobench_module2"))  # category lfq
    pairs = expand_matrix(wfs, [ds])
    assert ("lfq-sage", "proteobench_module2") in {
        (w.name, d.name) for w, d in pairs
    }


def test_matrix_skips_mismatched_category(tmp_path: Path):
    from bench.workflows import Workflow
    from bench.datasets import Dataset, GroundTruth
    wf = Workflow(name="dia-x", engine="x", type="dia-quant",
                  applies_to="dia", run_script=tmp_path / "run.sh", dir=tmp_path)
    ds = load_dataset(Path("datasets/proteobench_module2"))  # lfq
    assert expand_matrix([wf], [ds]) == []
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python -m pytest tests/test_workflows.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.workflows'`.

- [ ] **Step 4: Implement `bench/workflows.py`**

```python
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
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_workflows.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add bench/workflows.py workflows/lfq-sage tests/test_workflows.py
git commit -m "feat: workflow discovery and category-based matrix expansion"
```

---

## Task 6: Results TSV append (long/tidy)

**Files:**
- Create: `bench/results.py`
- Test: `tests/test_results.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Metric` = `tuple[str, float, str]` (name, value, unit).
  - `append_rows(results_tsv: Path, identity: dict[str, str], metrics: list[Metric]) -> None`. Writes the header if the file is new. Columns: `run_timestamp, openms_sha, openms_tag, workflow, engine, dataset, instrument, threads, host_cpu, metric_name, metric_value, unit`. One row per metric.

- [ ] **Step 1: Write the failing test**

Create `tests/test_results.py`:
```python
import csv
from pathlib import Path

from bench.results import append_rows

IDENTITY = {
    "run_timestamp": "2026-06-19T10:00:00Z",
    "openms_sha": "abc123",
    "openms_tag": "develop",
    "workflow": "lfq-sage",
    "engine": "sage",
    "dataset": "proteobench_module2",
    "instrument": "QExactiveHF",
    "threads": "4",
    "host_cpu": "test-cpu",
}


def test_append_writes_header_and_rows(tmp_path: Path):
    out = tmp_path / "results.tsv"
    append_rows(out, IDENTITY, [("num_precursors_quantified", 12345.0, "count"),
                                ("wall_clock_s", 42.5, "s")])
    rows = list(csv.DictReader(out.open(encoding="utf-8"), delimiter="\t"))
    assert len(rows) == 2
    assert rows[0]["metric_name"] == "num_precursors_quantified"
    assert rows[0]["openms_sha"] == "abc123"
    assert rows[1]["metric_value"] == "42.5"


def test_append_is_additive_without_duplicate_header(tmp_path: Path):
    out = tmp_path / "results.tsv"
    append_rows(out, IDENTITY, [("a", 1.0, "u")])
    append_rows(out, IDENTITY, [("b", 2.0, "u")])
    text = out.read_text(encoding="utf-8")
    assert text.count("metric_name") == 1  # header only once
    rows = list(csv.DictReader(out.open(encoding="utf-8"), delimiter="\t"))
    assert {r["metric_name"] for r in rows} == {"a", "b"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_results.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.results'`.

- [ ] **Step 3: Implement `bench/results.py`**

```python
import csv
from pathlib import Path

Metric = tuple[str, float, str]

COLUMNS = [
    "run_timestamp", "openms_sha", "openms_tag", "workflow", "engine",
    "dataset", "instrument", "threads", "host_cpu",
    "metric_name", "metric_value", "unit",
]


def append_rows(results_tsv: Path, identity: dict[str, str],
                metrics: list[Metric]) -> None:
    results_tsv = Path(results_tsv)
    results_tsv.parent.mkdir(parents=True, exist_ok=True)
    new_file = not results_tsv.exists()
    with results_tsv.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter="\t")
        if new_file:
            writer.writerow(COLUMNS)
        for name, value, unit in metrics:
            row = [identity.get(c, "") for c in COLUMNS[:9]]
            row += [name, "%g" % float(value), unit]
            writer.writerow(row)
```

> The `metric_value` is formatted with `%g` for a compact, stable representation (`42.5`, `12345`).

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_results.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add bench/results.py tests/test_results.py
git commit -m "feat: append-only long/tidy results TSV writer"
```

---

## Task 7: Workflow scripts — `common.sh` + `lfq-sage/run.sh`

**Files:**
- Create: `workflows/common.sh`
- Modify: `workflows/lfq-sage/run.sh` (replace placeholder)

**Interfaces:**
- Consumes (env vars set by the harness in Task 9): `INPUT_DIR`, `FASTA`, `OUT_DIR`, `THREADS`, `OPENMS_BIN`, `PREC_TOL_PPM`, `FRAG_TOL_DA`, `DESIGN_TSV`.
- Produces: `$OUT_DIR/quant.tsv` with tab-separated header `precursor	charge	protein	condition	replicate	intensity`. This is the seam consumed by the `lfq-quant` scorer (Task 8).

> The container has OpenMS tools + Sage on PATH and **no Python**; all logic is bash/awk. `ProteomicsLFQ` produces an MSstats CSV which `common.sh` transforms to the canonical `quant.tsv`.

- [ ] **Step 1: Write `workflows/common.sh`**

```bash
#!/usr/bin/env bash
# Shared DDA-LFQ chain. Sourced by each engine's run.sh, which must define
# run_search() that consumes $MZML_DIR + $DB_FASTA and writes $IDXML_DIR/<base>.idXML.
set -euo pipefail

: "${INPUT_DIR:?}" "${FASTA:?}" "${OUT_DIR:?}" "${THREADS:?}"
: "${PREC_TOL_PPM:?}" "${FRAG_TOL_DA:?}" "${DESIGN_TSV:?}"

WORK="$OUT_DIR/work"
mkdir -p "$WORK"

# 1) Target+decoy database (ProteoBench FASTA is target-only).
DB_FASTA="$WORK/db_with_decoys.fasta"
DecoyDatabase -in "$FASTA" -out "$DB_FASTA" \
  -decoy_string DECOY_ -decoy_string_position prefix -enzyme Trypsin

# 2) Per-file search (engine-specific) -> idXML, then index + PSM-level FDR.
mkdir -p "$WORK/idxml"
FILTERED_IDS=()
QUANT_MZML=()
for mz in "$INPUT_DIR"/*.mzML; do
  base="$(basename "$mz" .mzML)"
  raw_id="$WORK/idxml/${base}.idXML"
  run_search "$mz" "$DB_FASTA" "$raw_id"            # defined by run.sh

  PeptideIndexer -in "$raw_id" -fasta "$DB_FASTA" \
    -out "$WORK/idxml/${base}.idx.idXML" \
    -decoy_string DECOY_ -decoy_string_position prefix \
    -missing_decoy_action warn

  FalseDiscoveryRate -in "$WORK/idxml/${base}.idx.idXML" \
    -out "$WORK/idxml/${base}.fdr.idXML" -threads "$THREADS"

  IDFilter -in "$WORK/idxml/${base}.fdr.idXML" \
    -out "$WORK/idxml/${base}.filt.idXML" -score:pep 0.01

  FILTERED_IDS+=("$WORK/idxml/${base}.filt.idXML")
  QUANT_MZML+=("$mz")
done

# 3) Quantify with ProteomicsLFQ (MBR off baseline, top-3 protein quant).
ProteomicsLFQ \
  -in "${QUANT_MZML[@]}" \
  -ids "${FILTERED_IDS[@]}" \
  -design "$DESIGN_TSV" \
  -fasta "$DB_FASTA" \
  -targeted_only true \
  -transfer_ids false \
  -protein_quantification strongest_3_peptides \
  -out_msstats "$WORK/msstats.csv" \
  -threads "$THREADS"

# 4) Transform MSstats CSV -> canonical quant.tsv (long format).
#    MSstats columns: ProteinName,PeptideSequence,PrecursorCharge,FragmentIon,
#    ProductCharge,IsotopeLabelType,Condition,BioReplicate,Run,Intensity
awk -F',' 'NR==1{
    for(i=1;i<=NF;i++){h[$i]=i}
    print "precursor\tcharge\tprotein\tcondition\treplicate\tintensity"; next
  }
  {
    printf "%s\t%s\t%s\t%s\t%s\t%s\n",
      $h["PeptideSequence"], $h["PrecursorCharge"], $h["ProteinName"],
      $h["Condition"], $h["BioReplicate"], $h["Intensity"]
  }' "$WORK/msstats.csv" > "$OUT_DIR/quant.tsv"

echo "wrote $OUT_DIR/quant.tsv ($(wc -l < "$OUT_DIR/quant.tsv") lines)" >&2
```

- [ ] **Step 2: Replace `workflows/lfq-sage/run.sh` with the real Sage chain**

```bash
#!/usr/bin/env bash
set -euo pipefail

# Engine-specific search step for the shared chain.
# Shared logical params: Trypsin, 2 missed cleavages, Carbamidomethyl(C) fixed,
# Oxidation(M) variable. Tolerances come from the dataset (PREC_TOL_PPM/FRAG_TOL_DA).
run_search() {
  local mzml="$1" db="$2" out_id="$3"
  SageAdapter \
    -in "$mzml" -database "$db" -out "$out_id" \
    -enzyme Trypsin -allowed_missed_cleavages 2 \
    -fixed_modifications "Carbamidomethyl (C)" \
    -variable_modifications "Oxidation (M)" \
    -precursor_tol_left "-${PREC_TOL_PPM}" -precursor_tol_right "${PREC_TOL_PPM}" \
    -precursor_tol_unit ppm \
    -fragment_tol_left "-${FRAG_TOL_DA}" -fragment_tol_right "${FRAG_TOL_DA}" \
    -fragment_tol_unit Da \
    -threads "$THREADS"
}

# shellcheck source=/dev/null
source "$(dirname "$0")/../common.sh"
```

- [ ] **Step 3: Verify the scripts are syntactically valid bash**

Run (host, Git Bash):
```bash
bash -n workflows/common.sh && bash -n workflows/lfq-sage/run.sh && echo "OK"
```
Expected: `OK` (no syntax errors). Functional verification happens in the Task 13 end-to-end smoke run (requires Docker + data).

- [ ] **Step 4: Commit**

```bash
git add workflows/common.sh workflows/lfq-sage/run.sh
git commit -m "feat: shared LFQ chain + Sage workflow emitting canonical quant.tsv"
```

---

## Task 8: Scoring registry + `lfq-quant` + `perf-only`

**Files:**
- Create: `bench/scoring/__init__.py`, `bench/scoring/lfq_quant.py`, `bench/scoring/perf_only.py`
- Test: `tests/test_scoring_lfq_quant.py`, `tests/test_scoring_perf_only.py`

**Interfaces:**
- Consumes: `bench.datasets.Dataset`, `bench.species.assign_species`, `bench.results.Metric`.
- Produces:
  - `bench.scoring.get_scorer(type: str) -> Callable[[Path, Dataset], list[Metric]]`.
  - `bench.scoring.lfq_quant.score(out_dir: Path, dataset: Dataset) -> list[Metric]`.
  - `bench.scoring.perf_only.score(out_dir: Path, dataset: Dataset) -> list[Metric]` (returns `[]`; perf is harness-measured).

- [ ] **Step 1: Write the failing test for `lfq-quant`**

Create `tests/test_scoring_lfq_quant.py`:
```python
from pathlib import Path

from bench.datasets import load_dataset
from bench.scoring import get_scorer


def _write_quant(p: Path, rows: list[tuple]):
    lines = ["precursor\tcharge\tprotein\tcondition\treplicate\tintensity"]
    for r in rows:
        lines.append("\t".join(str(x) for x in r))
    (p / "quant.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_lfq_quant_perfect_human_ratio(tmp_path: Path):
    ds = load_dataset(Path("datasets/proteobench_module2"))
    # Human expected log2(A/B)=0 -> equal intensity in A and B.
    rows = []
    for rep in (1, 2, 3):
        rows.append(("PEPTIDEK", 2, "sp|P1|ALB_HUMAN", "A", rep, 1000))
        rows.append(("PEPTIDEK", 2, "sp|P1|ALB_HUMAN", "B", rep, 1000))
    _write_quant(tmp_path, rows)
    metrics = dict((m[0], m[1]) for m in get_scorer("lfq-quant")(tmp_path, ds))
    assert metrics["num_precursors_quantified"] == 1
    # observed log2(A/B)=0, expected 0 -> error 0
    assert abs(metrics["mean_abs_error_HUMAN"]) < 1e-9
    assert abs(metrics["median_log2_ratio_HUMAN"]) < 1e-9


def test_lfq_quant_excludes_contaminant(tmp_path: Path):
    ds = load_dataset(Path("datasets/proteobench_module2"))
    rows = []
    for rep in (1, 2, 3):
        rows.append(("CONTPEP", 2, "sp|Cont_P00722|BGAL_ECOLI", "A", rep, 500))
        rows.append(("CONTPEP", 2, "sp|Cont_P00722|BGAL_ECOLI", "B", rep, 500))
    _write_quant(tmp_path, rows)
    metrics = dict((m[0], m[1]) for m in get_scorer("lfq-quant")(tmp_path, ds))
    # Contaminant dropped -> nothing quantified.
    assert metrics["num_precursors_quantified"] == 0


def test_lfq_quant_yeast_ratio_error(tmp_path: Path):
    ds = load_dataset(Path("datasets/proteobench_module2"))
    # Yeast expected log2(A/B)=+1. Make observed A=2000,B=1000 -> log2=1 -> error 0.
    rows = []
    for rep in (1, 2, 3):
        rows.append(("YPEP", 2, "sp|P2|ADH1_YEAST", "A", rep, 2000))
        rows.append(("YPEP", 2, "sp|P2|ADH1_YEAST", "B", rep, 1000))
    _write_quant(tmp_path, rows)
    metrics = dict((m[0], m[1]) for m in get_scorer("lfq-quant")(tmp_path, ds))
    assert abs(metrics["mean_abs_error_YEAST"]) < 1e-9
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_scoring_lfq_quant.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.scoring'`.

- [ ] **Step 3: Implement `bench/scoring/lfq_quant.py`**

```python
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

from bench.datasets import Dataset
from bench.species import assign_species

Metric = tuple[str, float, str]


def score(out_dir: Path, dataset: Dataset) -> list[Metric]:
    gt = dataset.ground_truth
    # precursor key -> condition -> list of intensities (one per replicate)
    inten: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list))
    # precursor key -> set of species (to drop cross-species)
    prec_species: dict[tuple[str, str], set[str]] = defaultdict(set)
    proteins_seen: set[str] = set()

    with (Path(out_dir) / "quant.tsv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            try:
                intensity = float(row["intensity"])
            except (ValueError, KeyError):
                continue
            if intensity <= 0 or math.isnan(intensity):
                continue
            sp = assign_species(row["protein"], gt.exclude_regex, gt.suffix_map)
            if sp is None:
                continue
            key = (row["precursor"], row["charge"])
            prec_species[key].add(sp)
            inten[key][row["condition"]].append(intensity)
            proteins_seen.add(row["protein"])

    per_species_log2: dict[str, list[float]] = defaultdict(list)
    cv_values: list[float] = []
    n_quant = 0

    for key, conds in inten.items():
        species = prec_species[key]
        if len(species) != 1:
            continue  # cross-species, drop
        sp = next(iter(species))
        a = conds.get("A", [])
        b = conds.get("B", [])
        if not a or not b:
            continue  # require quant in both conditions
        n_quant += 1
        mean_a = statistics.fmean(a)
        mean_b = statistics.fmean(b)
        per_species_log2[sp].append(math.log2(mean_a / mean_b))
        for reps in (a, b):
            if len(reps) >= 2:
                m = statistics.fmean(reps)
                if m > 0:
                    cv_values.append(statistics.pstdev(reps) / m)

    metrics: list[Metric] = [
        ("num_precursors_quantified", float(n_quant), "count"),
        ("num_proteins", float(len(proteins_seen)), "count"),
    ]
    all_errors: list[float] = []
    for sp, observed in sorted(per_species_log2.items()):
        expected = gt.expected_log2.get(sp, 0.0)
        errors = [abs(o - expected) for o in observed]
        all_errors.extend(errors)
        metrics.append((f"median_log2_ratio_{sp}",
                        statistics.median(observed), "log2"))
        metrics.append((f"mean_abs_error_{sp}",
                        statistics.fmean(errors), "log2"))
    metrics.append(("mean_abs_error_overall",
                    statistics.fmean(all_errors) if all_errors else 0.0, "log2"))
    metrics.append(("median_intra_condition_cv",
                    statistics.median(cv_values) if cv_values else 0.0, "ratio"))
    return metrics
```

- [ ] **Step 4: Implement `bench/scoring/perf_only.py`**

```python
from pathlib import Path

from bench.datasets import Dataset

Metric = tuple[str, float, str]


def score(out_dir: Path, dataset: Dataset) -> list[Metric]:
    # Performance is measured by the harness for every workflow type;
    # this scorer adds no quality metrics.
    return []
```

- [ ] **Step 5: Implement `bench/scoring/__init__.py`**

```python
from collections.abc import Callable
from pathlib import Path

from bench.datasets import Dataset
from bench.scoring import lfq_quant, perf_only

Metric = tuple[str, float, str]
Scorer = Callable[[Path, Dataset], list[Metric]]

_REGISTRY: dict[str, Scorer] = {
    "lfq-quant": lfq_quant.score,
    "perf-only": perf_only.score,
}


def get_scorer(type_: str) -> Scorer:
    if type_ not in _REGISTRY:
        raise KeyError(f"no scorer registered for type {type_!r}; "
                       f"known: {sorted(_REGISTRY)}")
    return _REGISTRY[type_]
```

- [ ] **Step 6: Write and run the `perf-only` test**

Create `tests/test_scoring_perf_only.py`:
```python
from pathlib import Path

from bench.datasets import load_dataset
from bench.scoring import get_scorer


def test_perf_only_returns_no_quality_metrics():
    ds = load_dataset(Path("datasets/proteobench_module2"))
    assert get_scorer("perf-only")(Path("."), ds) == []
```

Run: `python -m pytest tests/test_scoring_lfq_quant.py tests/test_scoring_perf_only.py -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
git add bench/scoring tests/test_scoring_lfq_quant.py tests/test_scoring_perf_only.py
git commit -m "feat: scorer registry with lfq-quant and perf-only scorers"
```

---

## Task 9: Dataset fetch (rsync primary, HTTP fallback, checksum verify)

**Files:**
- Create: `bench/fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Consumes: `bench.config.Config`, `bench.datasets.Dataset`, `bench.datasets.FileEntry`.
- Produces:
  - `sha256_file(path: Path) -> str`.
  - `fetch_dataset(dataset: Dataset, config: Config) -> Path` → ensures every manifest file is present + checksum-valid under `config.data_cache/<dataset>/`, returns that dir. Uses rsync when `config.rsync_host` is set, else HTTP. For files whose manifest `sha256` is `PENDING`, computes the sha256 after download and **rewrites `manifest.tsv`** with the value (pinning on first fetch).

- [ ] **Step 1: Write the failing test (HTTP path + verification, using a local file:// server substitute)**

Create `tests/test_fetch.py`:
```python
import hashlib
from pathlib import Path

import pytest

from bench.fetch import sha256_file, verify_or_raise


def test_sha256_file(tmp_path: Path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    assert sha256_file(f) == hashlib.sha256(b"hello").hexdigest()


def test_verify_or_raise_detects_mismatch(tmp_path: Path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    good = hashlib.sha256(b"hello").hexdigest()
    verify_or_raise(f, good)  # no raise
    with pytest.raises(ValueError):
        verify_or_raise(f, "deadbeef")


def test_verify_skips_when_pending(tmp_path: Path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    verify_or_raise(f, "PENDING")  # PENDING means "not pinned yet": no raise
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_fetch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.fetch'`.

- [ ] **Step 3: Implement `bench/fetch.py`**

```python
import csv
import hashlib
import subprocess
import urllib.request
from pathlib import Path

from bench.config import Config
from bench.datasets import Dataset, FileEntry


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_or_raise(path: Path, expected: str) -> None:
    if expected == "PENDING":
        return
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"checksum mismatch for {path}: "
                         f"expected {expected}, got {actual}")


def _fetch_http(entry: FileEntry, dest: Path) -> None:
    with urllib.request.urlopen(entry.http_url) as resp, dest.open("wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)


def _fetch_rsync(entry: FileEntry, dest: Path, cfg: Config) -> None:
    remote = f"{cfg.rsync_user}@{cfg.rsync_host}:{entry.rsync_path}"
    ssh = (f"ssh -i {cfg.rsync_key} -p {cfg.rsync_port} "
           f"-o StrictHostKeyChecking=no")
    subprocess.run(["rsync", "-avz", "-e", ssh, remote, str(dest)], check=True)


def fetch_dataset(dataset: Dataset, config: Config) -> Path:
    cache = Path(config.data_cache) / dataset.name
    cache.mkdir(parents=True, exist_ok=True)
    use_rsync = bool(config.rsync_host)

    pinned: dict[str, str] = {}
    for entry in dataset.files:
        dest = cache / entry.filename
        need = not dest.exists()
        if not need and entry.sha256 != "PENDING":
            try:
                verify_or_raise(dest, entry.sha256)
            except ValueError:
                need = True  # cached copy is corrupt/stale: refetch
        if need:
            if use_rsync:
                _fetch_rsync(entry, dest, config)
            else:
                _fetch_http(entry, dest)
            verify_or_raise(dest, entry.sha256)
        if entry.sha256 == "PENDING":
            pinned[entry.filename] = sha256_file(dest)

    if pinned:
        _rewrite_manifest(dataset.path / "manifest.tsv", pinned)
    return cache


def _rewrite_manifest(manifest: Path, pinned: dict[str, str]) -> None:
    rows = list(csv.DictReader(manifest.open(encoding="utf-8"), delimiter="\t"))
    fields = rows[0].keys() if rows else []
    for r in rows:
        if r["filename"] in pinned and r["sha256"].strip() == "PENDING":
            r["sha256"] = pinned[r["filename"]]
    with manifest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(fields), delimiter="\t")
        w.writeheader()
        w.writerows(rows)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_fetch.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Integration smoke (manual, requires network) — fetch only the FASTA**

This confirms the HTTP path and pinning against the real archive without pulling 3 GB. Run a Python one-liner:
```bash
python - <<'PY'
from pathlib import Path
from bench.config import load_config
from bench.datasets import load_dataset, Dataset
cfg = load_config(Path("config.toml"))
ds = load_dataset(Path("datasets/proteobench_module2"))
# Fetch just the FASTA entry to keep it light.
from bench.fetch import _fetch_http, verify_or_raise
fasta = ds.fasta()
dest = Path(cfg.data_cache) / ds.name / fasta.filename
dest.parent.mkdir(parents=True, exist_ok=True)
_fetch_http(fasta, dest)
verify_or_raise(dest, fasta.sha256)
print("FASTA fetched and checksum verified:", dest)
PY
```
Expected: prints the path and "checksum verified" with no exception.

- [ ] **Step 6: Commit**

```bash
git add bench/fetch.py tests/test_fetch.py
git commit -m "feat: dataset fetch with rsync/http, checksum verify, sha pinning"
```

---

## Task 10: Docker build from the branch's Dockerfile

**Files:**
- Create: `bench/build.py`

**Interfaces:**
- Consumes: a worktree path (from `bench.gitref.checkout_worktree`).
- Produces: `build_image(worktree: Path, sha: str, threads: int) -> str` → runs `docker build` against the worktree's `dockerfiles/Dockerfile`, target `tools-thirdparty`, tag `openms-bench:<short-sha>`, returns the tag. Skips the build if the image already exists.

- [ ] **Step 1: Implement `bench/build.py`**

```python
import subprocess
from pathlib import Path


def _image_exists(tag: str) -> bool:
    res = subprocess.run(["docker", "image", "inspect", tag],
                         capture_output=True, text=True)
    return res.returncode == 0


def build_image(worktree: Path, sha: str, threads: int) -> str:
    worktree = Path(worktree)
    tag = f"openms-bench:{sha[:12]}"
    if _image_exists(tag):
        return tag
    dockerfile = worktree / "dockerfiles" / "Dockerfile"
    if not dockerfile.exists():
        raise FileNotFoundError(
            f"{dockerfile} missing — this ref cannot be containerized")
    subprocess.run(
        ["docker", "build",
         "-f", str(dockerfile),
         "--target", "tools-thirdparty",
         "--build-arg", f"NUM_BUILD_CORES={threads}",
         "-t", tag,
         str(worktree)],
        check=True,
    )
    return tag
```

- [ ] **Step 2: Verify the module imports and the no-Docker error path**

Run:
```bash
python - <<'PY'
from pathlib import Path
from bench.build import build_image
try:
    build_image(Path("nonexistent-worktree"), "deadbeefdeadbeef", 4)
except FileNotFoundError as e:
    print("expected FileNotFoundError:", e)
PY
```
Expected: prints "expected FileNotFoundError: …/dockerfiles/Dockerfile missing". (A real build is exercised in the Task 13 end-to-end smoke; it takes 30–90 min and needs Docker.)

- [ ] **Step 3: Commit**

```bash
git add bench/build.py
git commit -m "feat: docker build using the ref's own Dockerfile (tools-thirdparty)"
```

---

## Task 11: Run a workflow + measure wall-clock and peak memory

**Files:**
- Create: `bench/run.py`

**Interfaces:**
- Consumes: an image tag (Task 10), `bench.workflows.Workflow`, `bench.datasets.Dataset`, a fetched-data dir (Task 9), `bench.config.Config`.
- Produces:
  - `RunResult` dataclass: `out_dir: Path`, `wall_clock_s: float`, `peak_mem_bytes: float | None`, `returncode: int`.
  - `write_design_tsv(dataset: Dataset, data_dir: Path, dest: Path) -> None` → writes the OpenMS experimental-design TSV mapping each mzML to condition/replicate (consumed by `ProteomicsLFQ -design`).
  - `run_workflow(image: str, workflow: Workflow, dataset: Dataset, data_dir: Path, out_dir: Path, config: Config) -> RunResult`.

- [ ] **Step 1: Implement `bench/run.py`**

```python
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from bench.config import Config
from bench.datasets import Dataset
from bench.workflows import Workflow


@dataclass
class RunResult:
    out_dir: Path
    wall_clock_s: float
    peak_mem_bytes: float | None
    returncode: int


def write_design_tsv(dataset: Dataset, data_dir: Path, dest: Path) -> None:
    """OpenMS experimental design: maps each run to Fraction/Sample/Condition."""
    cond_of: dict[str, tuple[str, int]] = {}
    for entry in dataset.spectra():
        cond_of[entry.filename] = (entry.condition, entry.replicate)
    lines = ["Fraction_Group\tFraction\tSpectra_Filepath\tLabel\t"
             "Sample\tMSstats_Condition\tMSstats_BioReplicate"]
    for i, entry in enumerate(dataset.spectra(), start=1):
        cond, rep = cond_of[entry.filename]
        # In-container path is /data/<filename>.
        path = f"/data/{entry.filename}"
        lines.append(f"{i}\t1\t{path}\t1\t{i}\t{cond}\t{cond}_{rep}")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_workflow(image: str, workflow: Workflow, dataset: Dataset,
                 data_dir: Path, out_dir: Path, config: Config) -> RunResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    design = out_dir / "design.tsv"
    write_design_tsv(dataset, data_dir, design)

    repo_root = Path(__file__).resolve().parents[1]
    workflows_dir = repo_root / "workflows"
    fasta_name = dataset.fasta().filename
    rel_run = workflow.run_script.relative_to(workflows_dir).as_posix()

    # The container reads its own cgroup memory.peak as the final step.
    inner = (
        f'bash /work/{rel_run}; rc=$?; '
        f'cat /sys/fs/cgroup/memory.peak > /out/peak_mem_bytes.txt 2>/dev/null || '
        f'echo "" > /out/peak_mem_bytes.txt; exit $rc'
    )
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{workflows_dir}:/work:ro",
        "-v", f"{data_dir}:/data:ro",
        "-v", f"{out_dir}:/out",
        "-e", "INPUT_DIR=/data",
        "-e", f"FASTA=/data/{fasta_name}",
        "-e", "OUT_DIR=/out",
        "-e", f"THREADS={config.threads}",
        "-e", "OPENMS_BIN=/opt/OpenMS/bin",
        "-e", f"PREC_TOL_PPM={dataset.precursor_tol_ppm}",
        "-e", f"FRAG_TOL_DA={dataset.fragment_tol_da}",
        "-e", "DESIGN_TSV=/out/design.tsv",
        image, "bash", "-c", inner,
    ]
    start = time.monotonic()
    proc = subprocess.run(cmd)
    wall = time.monotonic() - start

    peak: float | None = None
    peak_file = out_dir / "peak_mem_bytes.txt"
    if peak_file.exists():
        txt = peak_file.read_text(encoding="utf-8").strip()
        if txt.isdigit():
            peak = float(txt)
    return RunResult(out_dir=out_dir, wall_clock_s=wall,
                     peak_mem_bytes=peak, returncode=proc.returncode)
```

- [ ] **Step 2: Write and run a unit test for `write_design_tsv`**

Append to a new `tests/test_run.py`:
```python
from pathlib import Path

from bench.datasets import load_dataset
from bench.run import write_design_tsv


def test_design_tsv_maps_conditions(tmp_path: Path):
    ds = load_dataset(Path("datasets/proteobench_module2"))
    dest = tmp_path / "design.tsv"
    write_design_tsv(ds, tmp_path, dest)
    lines = dest.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("Fraction_Group")
    assert len(lines) == 1 + 6  # header + 6 runs
    assert any("\tA\tA_1" in ln for ln in lines[1:])
    assert any("\tB\tB_3" in ln for ln in lines[1:])
    assert all(ln.split("\t")[2].startswith("/data/") for ln in lines[1:])
```

Run: `python -m pytest tests/test_run.py -v`
Expected: PASS (1 passed).

- [ ] **Step 3: Commit**

```bash
git add bench/run.py tests/test_run.py
git commit -m "feat: run workflow in container, measure wall-clock + cgroup memory.peak"
```

---

## Task 12: CLI wiring (end-to-end)

**Files:**
- Create: `bench/cli.py`, `bench/__main__.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: every prior module.
- Produces: `python -m bench --ref <branch-or-sha> [--workflow N ...] [--dataset N ...] [--instrument I ...] [--config config.toml]`. Builds the image once, fetches each applicable dataset, runs each `(workflow, dataset)` pair, scores, and appends rows. Also `host_cpu()` helper and `build_identity(...)`.

- [ ] **Step 1: Write the failing test for the pure helpers**

Create `tests/test_cli.py`:
```python
from bench.cli import build_identity, filter_matrix
from bench.workflows import Workflow
from pathlib import Path


def _wf(name, applies="lfq"):
    return Workflow(name=name, engine="e", type="lfq-quant",
                    applies_to=applies, run_script=Path("r"), dir=Path("d"))


def test_build_identity_has_all_columns():
    idn = build_identity(sha="a" * 40, tag="develop", workflow=_wf("lfq-sage"),
                         dataset_name="proteobench_module2",
                         instrument="QExactiveHF", threads=4,
                         host_cpu="cpu", timestamp="2026-06-19T00:00:00Z")
    assert idn["openms_sha"] == "a" * 40
    assert idn["workflow"] == "lfq-sage"
    assert idn["instrument"] == "QExactiveHF"
    assert idn["threads"] == "4"


def test_filter_matrix_by_workflow_name():
    pairs = [(_wf("lfq-sage"), "d1"), (_wf("lfq-comet"), "d1")]
    kept = filter_matrix(pairs, workflows=["lfq-sage"], datasets=None,
                         instruments=None)
    assert [w.name for w, _ in kept] == ["lfq-sage"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bench.cli'`.

- [ ] **Step 3: Implement `bench/cli.py`**

```python
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

    for wf, ds in pairs:
        data_dir = fetch_dataset(ds, cfg)
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
```

Create `bench/__main__.py`:
```python
from bench.cli import main

raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full unit suite**

Run: `python -m pytest -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add bench/cli.py bench/__main__.py tests/test_cli.py
git commit -m "feat: end-to-end CLI wiring (build, fetch, run, score, append)"
```

---

## Task 13: End-to-end smoke run (manual; requires Docker + network + time)

**Files:** none (verification task).

> This is the real integration gate. It builds OpenMS (~30–90 min) and downloads ~3 GB. Run it once against a known-good ref to confirm the whole pipeline produces rows.

- [ ] **Step 1: Create `config.toml` from the example and fill rsync creds (or leave the `[rsync]` section out to use HTTP)**

```bash
cp config.example.toml config.toml
# edit config.toml: set openms_repo = "OpenMS", threads, and [rsync] if you have the key
```

- [ ] **Step 2: Run a single workflow×dataset pair against develop**

Run:
```bash
python -m bench --ref develop --workflow lfq-sage --dataset proteobench_module2
```
Expected: stderr shows the build, then `[lfq-sage x proteobench_module2] rc=0 wall=…s`. No traceback.

- [ ] **Step 3: Verify rows landed in the TSV**

Run:
```bash
python - <<'PY'
import csv
from pathlib import Path
rows = list(csv.DictReader(Path("results/results.tsv").open(encoding="utf-8"),
                           delimiter="\t"))
names = {r["metric_name"] for r in rows}
print("metrics:", sorted(names))
assert "num_precursors_quantified" in names
assert "wall_clock_s" in names
assert "peak_container_mem_bytes" in names
print("rows:", len(rows), "OK")
PY
```
Expected: prints the metric names (including `num_precursors_quantified`, `mean_abs_error_overall`, `wall_clock_s`, `peak_container_mem_bytes`) and "OK".

- [ ] **Step 4: Sanity-check the quality numbers**

Run:
```bash
python - <<'PY'
import csv
from pathlib import Path
rows = list(csv.DictReader(Path("results/results.tsv").open(encoding="utf-8"),
                           delimiter="\t"))
m = {r["metric_name"]: float(r["metric_value"]) for r in rows}
print("precursors:", m["num_precursors_quantified"])
print("overall mean_abs_error (log2):", m["mean_abs_error_overall"])
# ProteoBench-grade results should quantify thousands of precursors and have
# overall error well under ~1 log2 unit. Flag if wildly off.
assert m["num_precursors_quantified"] > 1000, "suspiciously few precursors"
PY
```
Expected: thousands of precursors, overall error a small log2 value. If not, investigate the workflow params before proceeding (do not adjust expected ratios — they are pinned ground truth).

- [ ] **Step 5: Commit the pinned manifest (sha256 values filled in by the fetch)**

```bash
git add datasets/proteobench_module2/manifest.tsv
git commit -m "chore: pin ProteoBench Module 2 mzML checksums from first fetch"
```

---

## Task 14: `pivot.py` (wide view of the long TSV)

**Files:**
- Create: `pivot.py`
- Test: `tests/test_pivot.py`

**Interfaces:**
- Produces: `pivot(rows: list[dict]) -> tuple[list[str], list[dict]]` (returns column order + wide rows keyed by run identity, one column per metric) and a `__main__` that reads `results/results.tsv` and prints a TSV wide table.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pivot.py`:
```python
from pivot import pivot


def test_pivot_groups_by_run_identity():
    rows = [
        {"openms_sha": "a", "workflow": "w", "dataset": "d",
         "metric_name": "wall_clock_s", "metric_value": "10"},
        {"openms_sha": "a", "workflow": "w", "dataset": "d",
         "metric_name": "num_precursors_quantified", "metric_value": "5000"},
    ]
    cols, wide = pivot(rows)
    assert len(wide) == 1
    assert wide[0]["wall_clock_s"] == "10"
    assert wide[0]["num_precursors_quantified"] == "5000"
    assert "wall_clock_s" in cols
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_pivot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pivot'`.

- [ ] **Step 3: Implement `pivot.py`**

```python
import csv
import sys
from pathlib import Path

KEY = ["run_timestamp", "openms_sha", "openms_tag", "workflow", "engine",
       "dataset", "instrument", "threads", "host_cpu"]


def pivot(rows: list[dict]) -> tuple[list[str], list[dict]]:
    present_keys = [k for k in KEY if any(k in r for r in rows)]
    wide: dict[tuple, dict] = {}
    metric_cols: list[str] = []
    for r in rows:
        ident = tuple(r.get(k, "") for k in present_keys)
        bucket = wide.setdefault(ident, {k: r.get(k, "") for k in present_keys})
        name = r["metric_name"]
        if name not in metric_cols:
            metric_cols.append(name)
        bucket[name] = r["metric_value"]
    return present_keys + metric_cols, list(wide.values())


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("results/results.tsv")
    rows = list(csv.DictReader(src.open(encoding="utf-8"), delimiter="\t"))
    cols, wide = pivot(rows)
    w = csv.DictWriter(sys.stdout, fieldnames=cols, delimiter="\t",
                       extrasaction="ignore")
    w.writeheader()
    w.writerows(wide)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_pivot.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add pivot.py tests/test_pivot.py
git commit -m "feat: pivot long results TSV into a wide per-run view"
```

---

## Task 15: Second engine (`lfq-comet`) — proves pluggability

**Files:**
- Create: `workflows/lfq-comet/meta.yaml`, `workflows/lfq-comet/run.sh`

**Interfaces:**
- Consumes: `workflows/common.sh` (Task 7) — defines `run_search()` for Comet.
- Produces: a second `lfq-quant` workflow discovered automatically; no harness changes.

- [ ] **Step 1: Create `workflows/lfq-comet/meta.yaml`**

```yaml
name: lfq-comet
engine: comet
type: lfq-quant
applies_to: lfq
description: Label-free DDA quantification using the Comet search engine.
```

- [ ] **Step 2: Create `workflows/lfq-comet/run.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

# Same shared logical params as lfq-sage, mapped to CometAdapter flags.
run_search() {
  local mzml="$1" db="$2" out_id="$3"
  CometAdapter \
    -in "$mzml" -database "$db" -out "$out_id" \
    -enzyme Trypsin -allowed_missed_cleavages 2 \
    -fixed_modifications "Carbamidomethyl (C)" \
    -variable_modifications "Oxidation (M)" \
    -precursor_mass_tolerance "${PREC_TOL_PPM}" -precursor_error_units ppm \
    -fragment_mass_tolerance "${FRAG_TOL_DA}" -fragment_error_units Da \
    -threads "$THREADS"
}

# shellcheck source=/dev/null
source "$(dirname "$0")/../common.sh"
```

- [ ] **Step 3: Verify discovery picks it up (no harness change)**

Run:
```bash
python - <<'PY'
from pathlib import Path
from bench.workflows import discover_workflows
names = {w.name for w in discover_workflows(Path("workflows"))}
print(sorted(names))
assert {"lfq-sage", "lfq-comet"} <= names
PY
```
Expected: prints `['lfq-comet', 'lfq-sage']` and no assertion error.

- [ ] **Step 4: Verify bash syntax**

Run: `bash -n workflows/lfq-comet/run.sh && echo OK`
Expected: `OK`. (Functional comparison of the two engines happens by running the CLI with both; that's the Task 13 smoke extended with `--workflow lfq-comet`.)

- [ ] **Step 5: Commit**

```bash
git add workflows/lfq-comet
git commit -m "feat: add lfq-comet workflow (auto-discovered, proves pluggability)"
```

---

## Task 16: Placeholder dataset — proves the full matrix runs on fake truth

**Files:**
- Create: `datasets/lfq_velos_pxd001819/ground_truth.yaml`, `datasets/lfq_velos_pxd001819/manifest.tsv`

> Uses the real `lfq/LTQOrbitrapVelos/PXD001819` data on the archive but **obviously-absurd** ground truth (single `ALL` group, expected log2 = 99.0), so the matrix demonstrably runs across a second device and emits real coverage + perf with self-evidently garbage accuracy. No `status` field — the absurd 99.0 is the tell.

- [ ] **Step 1: List the archive folder to get the real filenames**

Run:
```bash
curl -sk "https://archive.openms.org/openms/benchmarks/pride-benchmarks/lfq/LTQOrbitrapVelos/PXD001819/" \
  | sed 's/<[^>]*>//g' | grep -iE '\.mzML' | awk '{print $1}'
```
Expected: a list of `.mzML` filenames. Record them for the manifest.

- [ ] **Step 2: Create `datasets/lfq_velos_pxd001819/ground_truth.yaml`**

```yaml
meta:
  name: lfq_velos_pxd001819
  category: lfq
  instrument: LTQOrbitrapVelos
  remote_dir: PXD001819
  http_base: https://archive.openms.org/openms/benchmarks/pride-benchmarks/
  precursor_tol_ppm: 20.0
  fragment_tol_da: 0.5
provenance:
  source: PLACEHOLDER — not authored from publication; values are deliberately fake
  retrieved: "2026-06-19"
ratio_direction: A_over_B
species_rule:
  exclude_regex: "Cont_"
  suffix_map:
    "": ALL            # catch-all: every non-contaminant protein -> ALL
expected_log2_ratio:
  ALL: 99.0            # absurd sentinel: no real ratio is 99
conditions:
  A: []                # fill from Step 1 filenames (first half)
  B: []                # fill from Step 1 filenames (second half)
```

- [ ] **Step 3: Create `datasets/lfq_velos_pxd001819/manifest.tsv`**

Fill `filename` rows from Step 1. Use a single FASTA appropriate to the dataset if one is staged; if none is staged, reuse the ProteoBench HYE FASTA path is **wrong** here — instead, since this is a placeholder, point the FASTA row at any staged FASTA on the archive for that folder, or omit quality expectations. For the demonstration, reuse a human FASTA already on the archive (`testfiles/human_sp.fasta`) by setting its `http_url` via a dedicated entry:
```
filename	role	condition	replicate	sha256
<file1>.mzML	spectra	A	1	PENDING
<file2>.mzML	spectra	B	1	PENDING
human_sp.fasta	fasta		PENDING
```
> Note: for a placeholder dataset the FASTA only needs to let the search run; species assignment collapses everything to `ALL` regardless. Add `meta.fasta_http_url: https://archive.openms.org/openms/testfiles/human_sp.fasta` and extend `bench/datasets.py` `load_dataset` to honor an explicit per-file `http_url` override when `meta.fasta_http_url` is set. (Implement that override now: if `role == "fasta"` and `meta.get("fasta_http_url")` is present, use it for `http_url` and set `rsync_path` to empty so fetch falls back to HTTP for the FASTA.)

- [ ] **Step 4: Implement the FASTA-URL override in `bench/datasets.py`**

In `load_dataset`, replace the single `files.append(FileEntry(...))` call with the version below. It honors an optional `meta.fasta_http_url`: when set, the FASTA entry uses that URL and an empty `rsync_path` (so fetch falls back to HTTP for it):
```python
            is_fasta = row["role"].strip() == "fasta"
            fasta_override = meta.get("fasta_http_url")
            if is_fasta and fasta_override:
                http_url = fasta_override
                rsync_path = ""
            else:
                http_url = f"{http_base}{rel}/{row['filename']}"
                rsync_path = f"/benchmarks/pride-benchmarks/{rel}/{row['filename']}"
            files.append(FileEntry(
                filename=row["filename"],
                rsync_path=rsync_path,
                http_url=http_url,
                sha256=row["sha256"].strip(),
                role=row["role"].strip(),
                condition=(row["condition"].strip() or None),
                replicate=(int(row["replicate"]) if row["replicate"].strip() else None),
            ))
```
And in `bench/fetch.py` `fetch_dataset`, force HTTP for entries with empty `rsync_path`:
```python
            if use_rsync and entry.rsync_path:
                _fetch_rsync(entry, dest, config)
            else:
                _fetch_http(entry, dest)
```

- [ ] **Step 5: Verify the placeholder dataset loads and matrixes**

Run:
```bash
python - <<'PY'
from pathlib import Path
from bench.datasets import discover_datasets
from bench.workflows import discover_workflows, expand_matrix
ds = discover_datasets(Path("datasets"))
wf = discover_workflows(Path("workflows"))
pairs = expand_matrix(wf, ds)
print("datasets:", sorted(d.name for d in ds))
print("pairs:", sorted((w.name, d.name) for w, d in pairs))
ph = next(d for d in ds if d.name == "lfq_velos_pxd001819")
assert ph.ground_truth.expected_log2["ALL"] == 99.0
PY
```
Expected: both datasets listed; pairs include the placeholder × both engines; assertion passes.

- [ ] **Step 6: Run the existing unit suite to confirm no regressions**

Run: `python -m pytest -v`
Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add datasets/lfq_velos_pxd001819 bench/datasets.py bench/fetch.py
git commit -m "feat: placeholder LTQOrbitrapVelos dataset; full matrix runs on fake truth"
```

---

## Self-Review

**Spec coverage** (against the design in project memory):
- Build SHA in Docker using branch's own Dockerfile → Tasks 2, 10. ✓
- Bind-mounted scripts/data, image = OpenMS only → Task 11. ✓
- mzML input, rsync-primary + HTTP fallback, download-once, checksum pin → Task 9. ✓
- Pluggable workflows, `common.sh` + per-engine `run.sh`, `meta.yaml` → Tasks 5, 7, 15. ✓
- Shared logical params + dataset tolerances + per-engine adapter mapping, MBR off → Task 7, 15. ✓
- Modular scoring (type + registry), `lfq-quant` precursor-level with `Cont_` exclusion + cross-species drop + expected-ratio errors, `perf-only` → Tasks 3, 8. ✓
- Per-workflow wall-clock + cgroup `memory.peak` (incl. cache), honest column name → Task 11. ✓
- Append-only long/tidy TSV + pivot → Tasks 6, 14. ✓
- Single ref per invocation, manual/cron trigger (CLI), filters → Task 12. ✓
- Multi-device matrix, self-describing datasets, category `applies_to` → Tasks 4, 5, 16. ✓
- Placeholder ground truth (absurd sentinel, no status column) → Task 16. ✓
- Ground truth pinned from ProteoBench with provenance → Task 4. ✓
- **Deferred to separate plans (out of scope here):** the `add-benchmark` skill (Tier A/B); the `register-dataset` automation (Task 16 does it by hand to prove the shape — the skill/subcommand generalizes it later); ccache build optimization; a `plot.py`.

**Placeholder scan:** Task 16 Step 3–4 carries genuine implementation (FASTA-URL override) rather than a TODO; the `conditions: A/B []` lists are explicitly "fill from Step 1" with the command that produces the values — acceptable because the filenames are environment-derived and the step shows exactly how to obtain them.

**Type consistency:** `Metric = (name, value, unit)` is consistent across `results.py`, `scoring/*`. `FileEntry`/`GroundTruth`/`Dataset` fields match between `datasets.py`, `fetch.py`, `run.py`, `scoring/lfq_quant.py`. `Workflow` fields match between `workflows.py` and `cli.py`. Env-var names (`INPUT_DIR/FASTA/OUT_DIR/THREADS/PREC_TOL_PPM/FRAG_TOL_DA/DESIGN_TSV`) match between `run.py` and `common.sh`.
