import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from bench.config import Config
from bench.datasets import Dataset
from bench.workflows import Workflow


def _host_path(p: Path) -> str:
    """Docker Desktop on Windows wants forward-slash host paths in -v mounts."""
    return str(Path(p).resolve()).replace("\\", "/")


def _container_name(sha: str, workflow: str, dataset: str) -> str:
    raw = f"bench-{sha[:12]}-{workflow}-{dataset}"
    return re.sub(r"[^A-Za-z0-9_.-]", "-", raw)[:120]


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
        # In-container path is /data/<filename> (decompressed, .gz stripped).
        consumed = entry.filename[:-3] if entry.filename.endswith(".gz") else entry.filename
        path = f"/data/{consumed}"
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
    name = _container_name(image.split(":")[-1], workflow.name, dataset.name)
    cmd = [
        "docker", "run", "--rm",
        "--name", name,
        "-v", f"{_host_path(workflows_dir)}:/work:ro",
        "-v", f"{_host_path(data_dir)}:/data:ro",
        "-v", f"{_host_path(out_dir)}:/out",
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
    try:
        proc = subprocess.run(cmd, timeout=config.run_timeout_s)
        returncode = proc.returncode
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", name], capture_output=True)
        wall = time.monotonic() - start
        return RunResult(out_dir=out_dir, wall_clock_s=wall,
                         peak_mem_bytes=None, returncode=124)
    wall = time.monotonic() - start

    peak: float | None = None
    peak_file = out_dir / "peak_mem_bytes.txt"
    if peak_file.exists():
        txt = peak_file.read_text(encoding="utf-8").strip()
        try:
            peak = float(txt)
        except ValueError:
            peak = None
    return RunResult(out_dir=out_dir, wall_clock_s=wall,
                     peak_mem_bytes=peak, returncode=returncode)
